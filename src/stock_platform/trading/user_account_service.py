"""회원 계좌(Paper + Broker 연결) 서비스 — STEP65."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Literal

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from stock_platform.trading.account_masking import (
    hash_account_ref,
    mask_account_number,
)
from stock_platform.trading.account_models import (
    PaperAccount,
    UserBrokerAccount,
)
from stock_platform.trading.account_repository import (
    PaperAccountRepository,
)
from stock_platform.trading.account_service import (
    PaperAccountError,
    PaperAccountService,
)


AccountType = Literal["PAPER", "KIWOOM", "UPBIT"]
ConnectionStatus = Literal[
    "CONNECTED",
    "DISCONNECTED",
    "PENDING",
    "ERROR",
]

_BROKER_TYPES: frozenset[str] = frozenset({"KIWOOM", "UPBIT"})
_DEFAULT_PAPER_CASH = Decimal("10000000")


class UserAccountError(ValueError):
    """도메인 오류 — Router에서 4xx로 변환."""


@dataclass(frozen=True, slots=True)
class UserAccountView:
    account_id: int
    user_id: int
    account_type: str
    broker_code: str
    account_name: str
    masked_account_number: str | None
    currency_code: str
    is_default: bool
    is_active: bool
    connection_status: str
    created_at: datetime | None
    updated_at: datetime | None
    last_synced_at: datetime | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "account_id": self.account_id,
            "user_id": self.user_id,
            "account_type": self.account_type,
            "broker_code": self.broker_code,
            "account_name": self.account_name,
            "masked_account_number": self.masked_account_number,
            "currency_code": self.currency_code,
            "is_default": self.is_default,
            "is_active": self.is_active,
            "connection_status": self.connection_status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "last_synced_at": self.last_synced_at,
        }


def paper_to_view(account: PaperAccount) -> UserAccountView:
    return UserAccountView(
        account_id=int(account.account_id),
        user_id=int(account.user_id or 0),
        account_type="PAPER",
        broker_code="PAPER",
        account_name=account.account_name,
        masked_account_number=None,
        currency_code=account.currency_code,
        is_default=bool(account.is_default),
        is_active=bool(account.is_active),
        connection_status=(
            "CONNECTED" if account.is_active else "DISCONNECTED"
        ),
        created_at=account.created_at,
        updated_at=account.updated_at,
        last_synced_at=None,
    )


def broker_to_view(row: UserBrokerAccount) -> UserAccountView:
    return UserAccountView(
        account_id=int(row.user_broker_account_id),
        user_id=int(row.user_id),
        account_type=row.broker_code.upper(),
        broker_code=row.broker_code.upper(),
        account_name=row.account_alias,
        masked_account_number=row.masked_account_number,
        currency_code=row.currency_code,
        is_default=bool(row.is_default),
        is_active=bool(row.is_active),
        connection_status=row.connection_status,
        created_at=row.created_at,
        updated_at=row.updated_at,
        last_synced_at=row.last_synced_at,
    )


class UserAccountService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._paper_repo = PaperAccountRepository(session)
        self._paper_service = PaperAccountService(self._paper_repo)

    def list_accounts(
        self,
        user_id: int,
        *,
        default_only: bool = False,
        include_inactive: bool = False,
    ) -> list[UserAccountView]:
        paper_rows = self._list_paper(
            user_id,
            default_only=default_only,
            include_inactive=include_inactive,
        )
        broker_rows = self._list_broker(
            user_id,
            default_only=default_only,
            include_inactive=include_inactive,
        )
        views = [paper_to_view(r) for r in paper_rows] + [
            broker_to_view(r) for r in broker_rows
        ]
        views.sort(
            key=lambda v: (
                not v.is_default,
                v.account_type,
                v.account_id,
            )
        )
        return views

    def get_account(
        self,
        user_id: int,
        account_id: int,
        *,
        account_type: str | None = None,
    ) -> UserAccountView:
        resolved = self._resolve_owned(
            user_id, account_id, account_type=account_type
        )
        if isinstance(resolved, PaperAccount):
            return paper_to_view(resolved)
        return broker_to_view(resolved)

    def create_account(
        self,
        user_id: int,
        *,
        account_type: str,
        account_name: str | None = None,
        initial_cash: Decimal | None = None,
        currency_code: str = "KRW",
        account_number: str | None = None,
        is_default: bool = False,
    ) -> UserAccountView:
        kind = (account_type or "").strip().upper()
        if kind == "PAPER":
            return self._create_paper(
                user_id,
                account_name=account_name,
                initial_cash=initial_cash,
                currency_code=currency_code,
                is_default=is_default,
            )
        if kind in _BROKER_TYPES:
            return self._create_broker(
                user_id,
                broker_code=kind,
                account_alias=account_name,
                account_number=account_number,
                currency_code=currency_code,
                is_default=is_default,
            )
        raise UserAccountError(
            f"지원하지 않는 account_type: {account_type}"
        )

    def update_account(
        self,
        user_id: int,
        account_id: int,
        *,
        account_type: str | None = None,
        account_name: str | None = None,
        is_active: bool | None = None,
    ) -> UserAccountView:
        resolved = self._resolve_owned(
            user_id, account_id, account_type=account_type
        )
        if isinstance(resolved, PaperAccount):
            if account_name is not None:
                name = account_name.strip()
                if not name:
                    raise UserAccountError("account_name is required")
                resolved.account_name = name
            if is_active is not None:
                resolved.is_active = is_active
                if not is_active:
                    resolved.is_default = False
            self._session.commit()
            self._session.refresh(resolved)
            return paper_to_view(resolved)

        if account_name is not None:
            alias = account_name.strip()
            if not alias:
                raise UserAccountError("account_name is required")
            resolved.account_alias = alias
        if is_active is not None:
            resolved.is_active = is_active
            if not is_active:
                resolved.is_default = False
                resolved.connection_status = "DISCONNECTED"
        self._session.commit()
        self._session.refresh(resolved)
        return broker_to_view(resolved)

    def delete_account(
        self,
        user_id: int,
        account_id: int,
        *,
        account_type: str | None = None,
    ) -> dict[str, Any]:
        """
        Paper: 비활성(소프트 삭제). Broker: 연결 행 삭제(실계좌 자체 삭제 아님).
        """

        resolved = self._resolve_owned(
            user_id, account_id, account_type=account_type
        )
        if isinstance(resolved, PaperAccount):
            if resolved.is_default:
                raise UserAccountError(
                    "기본 Paper 계좌는 삭제할 수 없습니다. "
                    "다른 계좌를 기본으로 지정한 뒤 다시 시도하세요."
                )
            resolved.is_active = False
            resolved.is_default = False
            self._session.commit()
            return {
                "deleted": True,
                "account_type": "PAPER",
                "account_id": int(resolved.account_id),
                "mode": "soft_deactivate",
            }

        broker_id = int(resolved.user_broker_account_id)
        self._session.delete(resolved)
        self._session.commit()
        return {
            "deleted": True,
            "account_type": "BROKER",
            "account_id": broker_id,
            "mode": "unlink",
            "message": "플랫폼 연결 정보만 제거했습니다. 실계좌는 삭제되지 않습니다.",
        }

    def set_default(
        self,
        user_id: int,
        account_id: int,
        *,
        account_type: str | None = None,
    ) -> UserAccountView:
        resolved = self._resolve_owned(
            user_id, account_id, account_type=account_type
        )
        if isinstance(resolved, PaperAccount):
            if not resolved.is_active:
                raise UserAccountError("비활성 계좌는 기본으로 지정할 수 없습니다.")
            self._clear_paper_defaults(user_id)
            resolved.is_default = True
            self._session.commit()
            self._session.refresh(resolved)
            return paper_to_view(resolved)

        if not resolved.is_active:
            raise UserAccountError("비활성 계좌는 기본으로 지정할 수 없습니다.")
        self._clear_broker_defaults(user_id, resolved.broker_code)
        resolved.is_default = True
        self._session.commit()
        self._session.refresh(resolved)
        return broker_to_view(resolved)

    def connect(
        self,
        user_id: int,
        account_id: int,
        *,
        account_type: str | None = None,
    ) -> UserAccountView:
        resolved = self._resolve_owned(
            user_id, account_id, account_type=account_type
        )
        if isinstance(resolved, PaperAccount):
            resolved.is_active = True
            self._session.commit()
            self._session.refresh(resolved)
            return paper_to_view(resolved)
        resolved.is_active = True
        resolved.connection_status = "CONNECTED"
        self._session.commit()
        self._session.refresh(resolved)
        return broker_to_view(resolved)

    def disconnect(
        self,
        user_id: int,
        account_id: int,
        *,
        account_type: str | None = None,
    ) -> UserAccountView:
        resolved = self._resolve_owned(
            user_id, account_id, account_type=account_type
        )
        if isinstance(resolved, PaperAccount):
            if resolved.is_default:
                raise UserAccountError(
                    "기본 Paper 계좌는 연결 해제할 수 없습니다."
                )
            resolved.is_active = False
            resolved.is_default = False
            self._session.commit()
            self._session.refresh(resolved)
            return paper_to_view(resolved)
        resolved.connection_status = "DISCONNECTED"
        resolved.is_default = False
        self._session.commit()
        self._session.refresh(resolved)
        return broker_to_view(resolved)

    def sync(
        self,
        user_id: int,
        account_id: int,
        *,
        account_type: str | None = None,
    ) -> UserAccountView:
        """
        Paper: 메타 갱신만.
        Broker: last_synced_at 갱신.
        키움 실동기화는 서버 공용 credential 사용 — 별도 admin sync 참고.
        """

        resolved = self._resolve_owned(
            user_id, account_id, account_type=account_type
        )
        now = datetime.now(timezone.utc)
        if isinstance(resolved, PaperAccount):
            resolved.updated_at = now
            self._session.commit()
            self._session.refresh(resolved)
            return paper_to_view(resolved)
        resolved.last_synced_at = now
        resolved.connection_status = "CONNECTED"
        resolved.updated_at = now
        self._session.commit()
        self._session.refresh(resolved)
        return broker_to_view(resolved)

    def ensure_default_paper(self, user_id: int) -> UserAccountView:
        """기본 Paper 없으면 lazy 생성 (중복은 DB unique로 방지)."""

        existing = self._paper_repo.get_primary_for_user(user_id)
        if existing is not None:
            if not existing.is_default:
                try:
                    self._clear_paper_defaults(user_id)
                    existing.is_default = True
                    self._session.commit()
                    self._session.refresh(existing)
                except IntegrityError as exc:
                    self._session.rollback()
                    raise UserAccountError(
                        "기본 Paper 계좌 설정에 실패했습니다."
                    ) from exc
            return paper_to_view(existing)

        try:
            created = self._paper_service.create_account(
                account_name=f"user-{user_id}-default",
                initial_cash=_DEFAULT_PAPER_CASH,
                currency_code="KRW",
                user_id=user_id,
                is_default=True,
            )
        except PaperAccountError as exc:
            # 동시 생성 레이스 — 재조회
            existing = self._paper_repo.get_primary_for_user(user_id)
            if existing is not None:
                return paper_to_view(existing)
            raise UserAccountError(str(exc)) from exc
        except IntegrityError as exc:
            self._session.rollback()
            existing = self._paper_repo.get_primary_for_user(user_id)
            if existing is not None:
                return paper_to_view(existing)
            raise UserAccountError(
                "기본 Paper 계좌 생성에 실패했습니다."
            ) from exc
        return paper_to_view(created)

    def _create_paper(
        self,
        user_id: int,
        *,
        account_name: str | None,
        initial_cash: Decimal | None,
        currency_code: str,
        is_default: bool,
    ) -> UserAccountView:
        name = (account_name or "").strip() or f"user-{user_id}-paper"
        cash = initial_cash if initial_cash is not None else _DEFAULT_PAPER_CASH
        make_default = is_default or (
            self._paper_repo.get_primary_for_user(user_id) is None
        )
        if make_default:
            self._clear_paper_defaults(user_id)
        try:
            account = self._paper_service.create_account(
                account_name=name,
                initial_cash=cash,
                currency_code=currency_code,
                user_id=user_id,
                is_default=make_default,
            )
        except PaperAccountError as exc:
            raise UserAccountError(str(exc)) from exc
        except IntegrityError as exc:
            self._session.rollback()
            raise UserAccountError(
                "Paper 계좌 생성에 실패했습니다 (이름 또는 기본 계좌 중복)."
            ) from exc
        return paper_to_view(account)

    def _create_broker(
        self,
        user_id: int,
        *,
        broker_code: str,
        account_alias: str | None,
        account_number: str | None,
        currency_code: str,
        is_default: bool,
    ) -> UserAccountView:
        if not account_number or not account_number.strip():
            raise UserAccountError(
                "Broker 계좌 연결에는 account_number 가 필요합니다."
            )
        alias = (account_alias or "").strip() or f"{broker_code} 계좌"
        try:
            ref_hash = hash_account_ref(account_number)
            masked = mask_account_number(account_number)
        except ValueError as exc:
            raise UserAccountError(str(exc)) from exc

        make_default = is_default
        if make_default:
            self._clear_broker_defaults(user_id, broker_code)

        row = UserBrokerAccount(
            user_id=user_id,
            broker_code=broker_code,
            account_alias=alias,
            account_ref_hash=ref_hash,
            masked_account_number=masked,
            currency_code=(currency_code or "KRW").upper(),
            is_default=make_default,
            is_active=True,
            connection_status="PENDING",
        )
        self._session.add(row)
        try:
            self._session.commit()
            self._session.refresh(row)
        except IntegrityError as exc:
            self._session.rollback()
            raise UserAccountError(
                "이미 연결된 Broker 계좌입니다."
            ) from exc
        return broker_to_view(row)

    def _list_paper(
        self,
        user_id: int,
        *,
        default_only: bool,
        include_inactive: bool,
    ) -> list[PaperAccount]:
        stmt = select(PaperAccount).where(PaperAccount.user_id == user_id)
        if not include_inactive:
            stmt = stmt.where(PaperAccount.is_active.is_(True))
        if default_only:
            stmt = stmt.where(PaperAccount.is_default.is_(True))
        stmt = stmt.order_by(
            PaperAccount.is_default.desc(),
            PaperAccount.account_id.asc(),
        )
        return list(self._session.scalars(stmt))

    def _list_broker(
        self,
        user_id: int,
        *,
        default_only: bool,
        include_inactive: bool,
    ) -> list[UserBrokerAccount]:
        stmt = select(UserBrokerAccount).where(
            UserBrokerAccount.user_id == user_id
        )
        if not include_inactive:
            stmt = stmt.where(UserBrokerAccount.is_active.is_(True))
        if default_only:
            stmt = stmt.where(UserBrokerAccount.is_default.is_(True))
        stmt = stmt.order_by(
            UserBrokerAccount.is_default.desc(),
            UserBrokerAccount.user_broker_account_id.asc(),
        )
        return list(self._session.scalars(stmt))

    def _resolve_owned(
        self,
        user_id: int,
        account_id: int,
        *,
        account_type: str | None,
    ) -> PaperAccount | UserBrokerAccount:
        kind = (account_type or "").strip().upper() or None
        if kind is None or kind == "PAPER":
            paper = self._paper_repo.get_account(account_id)
            if paper is not None:
                if (
                    paper.user_id is not None
                    and int(paper.user_id) == int(user_id)
                ):
                    return paper
                raise UserAccountError("계좌를 찾을 수 없습니다.")

        if kind is None or kind in _BROKER_TYPES:
            broker = self._session.get(UserBrokerAccount, account_id)
            if (
                broker is not None
                and int(broker.user_id) == int(user_id)
                and (kind is None or broker.broker_code.upper() == kind)
            ):
                return broker
            if kind in _BROKER_TYPES:
                raise UserAccountError("계좌를 찾을 수 없습니다.")

        raise UserAccountError("계좌를 찾을 수 없습니다.")

    def _clear_paper_defaults(self, user_id: int) -> None:
        self._session.execute(
            update(PaperAccount)
            .where(
                PaperAccount.user_id == user_id,
                PaperAccount.is_default.is_(True),
            )
            .values(is_default=False)
        )
        self._session.flush()

    def _clear_broker_defaults(
        self, user_id: int, broker_code: str
    ) -> None:
        self._session.execute(
            update(UserBrokerAccount)
            .where(
                UserBrokerAccount.user_id == user_id,
                UserBrokerAccount.broker_code == broker_code.upper(),
                UserBrokerAccount.is_default.is_(True),
            )
            .values(is_default=False)
        )
        self._session.flush()
