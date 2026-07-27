"""STEP 8-3 — 전략 소유권·접근 검사."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from stock_platform.auth.account_ownership import (
    assert_broker_account_access,
    assert_paper_account_access,
)
from stock_platform.auth.deps import AuthenticatedUser
from stock_platform.strategy_deployment.definition_entities import (
    AccountStrategyLinkEntity,
    StrategyDefinitionEntity,
)


class StrategyOwnershipError(ValueError):
    """도메인 검증 오류."""


_STOCK_MARKETS = frozenset({"KRX", "KOSPI", "KOSDAQ", "STOCK", "PAPER"})
_CRYPTO_MARKETS = frozenset({"UPBIT", "CRYPTO", "KRW", "BTC", "PAPER_CRYPTO"})


def market_compatible(*, market_type: str, account_broker: str) -> bool:
    """주식/암호화폐 전략·계좌 호환성."""

    mt = (market_type or "STOCK").upper()
    broker = (account_broker or "").upper()
    if mt == "ALL":
        return True
    if mt == "STOCK":
        return broker in {
            "KIWOOM",
            "PAPER",
            "PAPER_STOCK",
            "KRX",
        } or broker in _STOCK_MARKETS
    if mt == "CRYPTO":
        return broker in {"UPBIT", "PAPER_CRYPTO"} or broker in {
            "UPBIT",
            "CRYPTO",
            "PAPER_CRYPTO",
        }
    return False


def assert_strategy_readable(
    user: AuthenticatedUser,
    strategy: StrategyDefinitionEntity,
) -> None:
    """조회: 본인 개인 OR 공개(활성·미삭제)."""

    if strategy.deleted_at is not None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Strategy not found",
        )
    if user.is_admin:
        return
    if (
        strategy.owner_type == "USER"
        and strategy.user_id is not None
        and int(strategy.user_id) == int(user.user_id)
    ):
        return
    if (
        strategy.visibility == "PUBLIC"
        and bool(strategy.is_active)
    ):
        return
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="해당 전략에 대한 권한이 없습니다.",
    )


def assert_strategy_writable(
    user: AuthenticatedUser,
    strategy: StrategyDefinitionEntity,
) -> None:
    """수정·삭제: 본인 USER 개인 전략만 (공개 원본·SYSTEM 불가)."""

    if strategy.deleted_at is not None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Strategy not found",
        )
    if user.is_admin:
        return
    if strategy.owner_type != "USER":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="시스템·공개 전략 원본은 수정할 수 없습니다.",
        )
    if strategy.visibility == "PUBLIC":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="공개 전략 원본은 수정할 수 없습니다. 복제 후 사용하세요.",
        )
    if int(strategy.user_id or 0) != int(user.user_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="본인 전략만 수정·삭제할 수 있습니다.",
        )


def user_visible_filter(user: AuthenticatedUser):
    """목록용 SQL 조건: 본인 OR 공개."""

    return or_(
        StrategyDefinitionEntity.user_id == int(user.user_id),
        StrategyDefinitionEntity.visibility == "PUBLIC",
    )


class StrategyDefinitionService:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, strategy_id: int) -> StrategyDefinitionEntity | None:
        return self._session.get(StrategyDefinitionEntity, strategy_id)

    def require(
        self, strategy_id: int
    ) -> StrategyDefinitionEntity:
        row = self.get(strategy_id)
        if row is None or row.deleted_at is not None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Strategy not found",
            )
        return row

    def list_for_user(
        self,
        user: AuthenticatedUser,
        *,
        scope: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[StrategyDefinitionEntity]:
        stmt = select(StrategyDefinitionEntity).where(
            StrategyDefinitionEntity.deleted_at.is_(None)
        )
        if not user.is_admin:
            stmt = stmt.where(user_visible_filter(user))
            # 공개는 활성만, 본인 비활성 개인 전략은 조회 가능
            stmt = stmt.where(
                or_(
                    StrategyDefinitionEntity.user_id == int(user.user_id),
                    StrategyDefinitionEntity.is_active.is_(True),
                )
            )
        scope_key = (scope or "").strip().upper()
        if scope_key == "MINE":
            stmt = stmt.where(
                StrategyDefinitionEntity.owner_type == "USER",
                StrategyDefinitionEntity.user_id == int(user.user_id),
            )
        elif scope_key == "PUBLIC":
            stmt = stmt.where(
                StrategyDefinitionEntity.visibility == "PUBLIC",
                StrategyDefinitionEntity.is_active.is_(True),
            )
        return list(
            self._session.scalars(
                stmt.order_by(
                    StrategyDefinitionEntity.strategy_id.desc()
                )
                .offset(offset)
                .limit(limit)
            )
        )

    def create_user_strategy(
        self,
        user: AuthenticatedUser,
        *,
        strategy_code: str,
        name: str,
        description: str | None,
        market_type: str,
        parameter_payload: dict[str, Any] | None,
        actor: str,
    ) -> StrategyDefinitionEntity:
        # Body의 user_id/owner_type/visibility 는 신뢰하지 않음
        code = strategy_code.strip()
        if not code:
            raise StrategyOwnershipError("strategy_code required")
        mt = (market_type or "STOCK").strip().upper()
        if mt not in {"STOCK", "CRYPTO", "ALL"}:
            raise StrategyOwnershipError("invalid market_type")
        row = StrategyDefinitionEntity(
            strategy_code=code,
            name=(name or code).strip(),
            description=description,
            market_type=mt,
            owner_type="USER",
            user_id=int(user.user_id),
            visibility="PRIVATE",
            is_active=False,
            parameter_payload=dict(parameter_payload or {}),
            created_by=actor,
            updated_by=actor,
        )
        self._session.add(row)
        self._session.flush()
        return row

    def update_user_strategy(
        self,
        user: AuthenticatedUser,
        strategy_id: int,
        *,
        payload: dict[str, Any],
        actor: str,
    ) -> StrategyDefinitionEntity:
        row = self.require(strategy_id)
        assert_strategy_writable(user, row)
        for key in (
            "name",
            "description",
            "market_type",
            "parameter_payload",
            "is_active",
        ):
            if key in payload and payload[key] is not None:
                if key == "market_type":
                    mt = str(payload[key]).upper()
                    if mt not in {"STOCK", "CRYPTO", "ALL"}:
                        raise StrategyOwnershipError("invalid market_type")
                    row.market_type = mt
                else:
                    setattr(row, key, payload[key])
        # 소유·공개 강제 유지
        row.owner_type = "USER"
        row.user_id = int(user.user_id) if not user.is_admin else row.user_id
        if not user.is_admin:
            row.visibility = "PRIVATE"
        row.updated_by = actor
        self._session.flush()
        return row

    def soft_delete_user_strategy(
        self,
        user: AuthenticatedUser,
        strategy_id: int,
        *,
        actor: str,
    ) -> StrategyDefinitionEntity:
        row = self.require(strategy_id)
        assert_strategy_writable(user, row)
        # 활성 계좌 연결 있으면 차단
        active_links = self._session.scalar(
            select(AccountStrategyLinkEntity).where(
                AccountStrategyLinkEntity.strategy_id == strategy_id,
                AccountStrategyLinkEntity.is_active.is_(True),
            ).limit(1)
        )
        if active_links is not None:
            raise StrategyOwnershipError(
                "활성 계좌 연결이 있어 삭제할 수 없습니다. 연결 해제 후 삭제하세요."
            )
        if row.visibility == "PUBLIC" and not user.is_admin:
            raise StrategyOwnershipError(
                "공개 전략은 사용자가 삭제할 수 없습니다."
            )
        row.is_active = False
        row.deleted_at = datetime.now(timezone.utc)
        row.updated_by = actor
        self._session.flush()
        return row

    def clone_strategy(
        self,
        user: AuthenticatedUser,
        strategy_id: int,
        *,
        actor: str,
        name: str | None = None,
    ) -> StrategyDefinitionEntity:
        source = self.require(strategy_id)
        assert_strategy_readable(user, source)
        # 공개 또는 본인만 복제
        # 복제 코드 충돌 방지
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        clone = StrategyDefinitionEntity(
            strategy_code=f"{source.strategy_code}_COPY_{user.user_id}_{stamp}",
            name=name or f"{source.name} (복사)",
            description=source.description,
            market_type=source.market_type,
            owner_type="USER",
            user_id=int(user.user_id),
            visibility="PRIVATE",
            is_active=False,
            parameter_payload=dict(source.parameter_payload or {}),
            created_by=actor,
            updated_by=actor,
            approved_by=None,
            approved_at=None,
            published_by=None,
            published_at=None,
            source_strategy_id=int(source.strategy_id),
        )
        self._session.add(clone)
        self._session.flush()
        return clone

    def link_to_account(
        self,
        user: AuthenticatedUser,
        *,
        strategy_id: int,
        paper_account_id: int | None,
        user_broker_account_id: int | None,
        account_broker: str,
        actor: str,
    ) -> AccountStrategyLinkEntity:
        strategy = self.require(strategy_id)
        assert_strategy_readable(user, strategy)
        # 비활성·삭제 전략 연결 차단 (SYSTEM backfill은 is_active=true)
        if not strategy.is_active:
            raise StrategyOwnershipError("비활성 전략은 연결할 수 없습니다.")
        # USER가 PUBLIC으로 올린 미승인 전략 연결 차단
        if (
            strategy.visibility == "PUBLIC"
            and strategy.owner_type == "USER"
            and strategy.approved_at is None
        ):
            raise StrategyOwnershipError(
                "미승인 공개 전략은 계좌에 연결할 수 없습니다."
            )

        if not market_compatible(
            market_type=strategy.market_type,
            account_broker=account_broker,
        ):
            raise StrategyOwnershipError(
                "전략 시장 유형과 계좌 브로커가 호환되지 않습니다."
            )

        if paper_account_id is not None:
            assert_paper_account_access(
                user, paper_account_id, self._session
            )
            uba_id = None
            pid = paper_account_id
        elif user_broker_account_id is not None:
            assert_broker_account_access(
                user, user_broker_account_id, self._session
            )
            pid = None
            uba_id = user_broker_account_id
        else:
            raise StrategyOwnershipError(
                "paper_account_id 또는 user_broker_account_id 필요"
            )

        # 전략 접근: 본인 OR PUBLIC (이미 readable)
        link = AccountStrategyLinkEntity(
            strategy_id=int(strategy.strategy_id),
            user_id=int(user.user_id),
            paper_account_id=pid,
            user_broker_account_id=uba_id,
            is_active=True,
            created_by=actor,
        )
        self._session.add(link)
        self._session.flush()
        return link

    def unlink(
        self,
        user: AuthenticatedUser,
        *,
        strategy_id: int,
        paper_account_id: int | None,
        user_broker_account_id: int | None,
    ) -> None:
        stmt = select(AccountStrategyLinkEntity).where(
            AccountStrategyLinkEntity.strategy_id == strategy_id,
            AccountStrategyLinkEntity.user_id == int(user.user_id),
            AccountStrategyLinkEntity.is_active.is_(True),
        )
        if paper_account_id is not None:
            stmt = stmt.where(
                AccountStrategyLinkEntity.paper_account_id
                == paper_account_id
            )
        if user_broker_account_id is not None:
            stmt = stmt.where(
                AccountStrategyLinkEntity.user_broker_account_id
                == user_broker_account_id
            )
        row = self._session.scalar(stmt.limit(1))
        if row is None:
            raise HTTPException(status_code=404, detail="Link not found")
        row.is_active = False
        self._session.flush()

    # ---- ADMIN ----
    def admin_set_visibility(
        self,
        strategy_id: int,
        *,
        visibility: str,
        actor: str,
    ) -> StrategyDefinitionEntity:
        row = self.require(strategy_id)
        vis = visibility.upper()
        if vis not in {"PRIVATE", "PUBLIC"}:
            raise StrategyOwnershipError("invalid visibility")
        row.visibility = vis
        if vis == "PUBLIC":
            row.published_by = actor
            row.published_at = datetime.now(timezone.utc)
            row.is_active = True
        else:
            row.published_by = None
            row.published_at = None
        row.updated_by = actor
        self._session.flush()
        return row

    def admin_approve(
        self,
        strategy_id: int,
        *,
        actor: str,
        approve: bool,
    ) -> StrategyDefinitionEntity:
        row = self.require(strategy_id)
        if approve:
            row.approved_by = actor
            row.approved_at = datetime.now(timezone.utc)
        else:
            row.approved_by = None
            row.approved_at = None
            if row.visibility == "PUBLIC":
                row.visibility = "PRIVATE"
        row.updated_by = actor
        self._session.flush()
        return row

    def admin_set_active(
        self,
        strategy_id: int,
        *,
        is_active: bool,
        actor: str,
    ) -> StrategyDefinitionEntity:
        row = self.require(strategy_id)
        row.is_active = is_active
        row.updated_by = actor
        self._session.flush()
        return row

    def as_dict(self, row: StrategyDefinitionEntity) -> dict[str, Any]:
        return {
            "strategy_id": int(row.strategy_id),
            "strategy_code": row.strategy_code,
            "name": row.name,
            "description": row.description,
            "market_type": row.market_type,
            "owner_type": row.owner_type,
            "user_id": row.user_id,
            "visibility": row.visibility,
            "is_active": bool(row.is_active),
            "parameter_payload": row.parameter_payload or {},
            "created_by": row.created_by,
            "updated_by": row.updated_by,
            "approved_by": row.approved_by,
            "approved_at": row.approved_at,
            "published_by": row.published_by,
            "published_at": row.published_at,
            "source_strategy_id": row.source_strategy_id,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }
