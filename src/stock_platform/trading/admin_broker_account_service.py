"""STEP 8-9C — Admin UserBrokerAccount CRUD (UPBIT/KIWOOM).

실주문·ARM·LIVE ON은 이 모듈에서 수행하지 않는다.
UPBIT 생성 시 권장 Risk(5000/1/1)만 계좌 오버레이로 적용한다.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from stock_platform.auth.repository import AuthRepository
from stock_platform.risk_engine.resolved_policy import (
    ResolvedRiskPolicyResolver,
)
from stock_platform.risk_engine.user_risk_service import (
    UserRiskSettingService,
)
from stock_platform.trading.account_masking import hash_account_ref
from stock_platform.trading.account_models import UserBrokerAccount
from stock_platform.trading.upbit_live_ops_constants import (
    upbit_live_recommended_risk_payload,
)
from stock_platform.trading.user_account_service import (
    UserAccountError,
    UserAccountService,
    broker_to_view,
)


_BROKER_TYPES = frozenset({"KIWOOM", "UPBIT"})


class AdminBrokerAccountService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._accounts = UserAccountService(session)

    def list_accounts(
        self,
        *,
        broker_code: str | None = None,
        owner_user_id: int | None = None,
        include_inactive: bool = True,
        include_deleted: bool = False,
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, Any]:
        stmt = select(UserBrokerAccount)
        if broker_code:
            code = broker_code.strip().upper()
            if code not in _BROKER_TYPES:
                raise UserAccountError(f"unsupported broker_code: {code}")
            stmt = stmt.where(
                func.upper(UserBrokerAccount.broker_code) == code
            )
        if owner_user_id is not None:
            stmt = stmt.where(
                UserBrokerAccount.user_id == int(owner_user_id)
            )
        if not include_inactive:
            stmt = stmt.where(UserBrokerAccount.is_active.is_(True))
        # STEP 2-5-1 — 관리자 목록은 기본적으로 삭제 계좌를 제외하고,
        # include_deleted=True를 명시했을 때만 포함한다.
        if not include_deleted:
            stmt = stmt.where(UserBrokerAccount.deleted_at.is_(None))
        total = int(
            self._session.scalar(
                select(func.count()).select_from(stmt.subquery())
            )
            or 0
        )
        rows = list(
            self._session.scalars(
                stmt.order_by(UserBrokerAccount.user_broker_account_id)
                .offset(max(0, offset))
                .limit(min(max(limit, 1), 500))
            ).all()
        )
        items = [self._enrich(broker_to_view(r).as_dict(), r) for r in rows]
        return {"items": items, "total": total}

    def get_account(self, uba_id: int) -> dict[str, Any]:
        row = self._session.get(UserBrokerAccount, int(uba_id))
        if row is None:
            raise UserAccountError("User broker account not found")
        return self._enrich(broker_to_view(row).as_dict(), row)

    def create_account(
        self,
        *,
        owner_user_id: int,
        broker_code: str,
        account_alias: str | None,
        account_number: str,
        currency_code: str = "KRW",
        is_default: bool = False,
        apply_recommended_risk: bool = True,
        actor: str,
    ) -> dict[str, Any]:
        code = (broker_code or "").strip().upper()
        if code not in _BROKER_TYPES:
            raise UserAccountError(f"unsupported broker_code: {code}")

        owner = AuthRepository(self._session).get_by_id(int(owner_user_id))
        if owner is None or getattr(owner, "deleted_at", None) is not None:
            raise UserAccountError("Owner user not found")

        # 중복을 선검사해 409로 명확히 반환 (부분 커밋 방지)
        try:
            ref_hash = hash_account_ref(account_number)
        except ValueError as exc:
            raise UserAccountError(str(exc)) from exc
        # STEP 2-5-1 — 삭제(soft-deleted)된 행은 "이미 연결됨"으로 보지 않는다.
        # (동일 계좌 재연결은 아래 _accounts.create_account → _create_broker의
        # revive 로직이 처리한다.)
        dup = self._session.scalar(
            select(UserBrokerAccount).where(
                UserBrokerAccount.user_id == int(owner_user_id),
                func.upper(UserBrokerAccount.broker_code) == code,
                UserBrokerAccount.account_ref_hash == ref_hash,
                UserBrokerAccount.deleted_at.is_(None),
            )
        )
        if dup is not None:
            raise UserAccountError("이미 연결된 Broker 계좌입니다.")

        # UBA + 권장 Risk 를 동일 트랜잭션에서 flush (라우터가 commit)
        try:
            view = self._accounts.create_account(
                int(owner_user_id),
                account_type=code,
                account_name=account_alias,
                account_number=account_number,
                currency_code=currency_code,
                is_default=is_default,
                auto_commit=False,
            )
            uba_id = int(view.account_id)
            risk_applied = False
            if apply_recommended_risk and code == "UPBIT":
                UserRiskSettingService(self._session).upsert_account(
                    uba_id,
                    upbit_live_recommended_risk_payload(),
                    actor=actor,
                )
                risk_applied = True
            row = self._session.get(UserBrokerAccount, uba_id)
            if row is None:
                raise UserAccountError("User broker account not found")
            # LIVE ON / ARM 금지 — 생성 시점 강제 OFF
            if bool(row.live_order_enabled) or bool(row.live_armed):
                row.live_order_enabled = False
                row.live_armed = False
                row.arm_token_hash = None
                row.arm_expires_at = None
                self._session.flush()
            out = self._enrich(broker_to_view(row).as_dict(), row)
            out["recommended_risk_applied"] = risk_applied
            out["created_by"] = actor
            return out
        except UserAccountError:
            self._session.rollback()
            raise
        except Exception as exc:  # noqa: BLE001
            self._session.rollback()
            raise UserAccountError(
                "Broker account create failed"
            ) from exc

    def update_account(
        self,
        uba_id: int,
        *,
        account_alias: str | None = None,
        is_active: bool | None = None,
        actor: str,
    ) -> dict[str, Any]:
        row = self._session.get(UserBrokerAccount, int(uba_id))
        if row is None:
            raise UserAccountError("User broker account not found")
        view = self._accounts.update_account(
            int(row.user_id),
            int(uba_id),
            account_type=str(row.broker_code).upper(),
            account_name=account_alias,
            is_active=is_active,
        )
        refreshed = self._session.get(UserBrokerAccount, int(uba_id))
        assert refreshed is not None
        out = self._enrich(view.as_dict(), refreshed)
        out["updated_by"] = actor
        return out

    def delete_account(self, uba_id: int, *, actor: str) -> dict[str, Any]:
        """Broker 연결 행 unlink (실계좌 자체 삭제 아님). LIVE/ARM 강제 OFF."""

        row = self._session.get(UserBrokerAccount, int(uba_id))
        if row is None:
            raise UserAccountError("User broker account not found")
        owner_id = int(row.user_id)
        broker = str(row.broker_code).upper()
        # 삭제 전 LIVE/ARM 정리
        row.live_order_enabled = False
        row.live_armed = False
        row.arm_token_hash = None
        row.arm_expires_at = None
        self._session.flush()
        result = self._accounts.delete_account(
            owner_id,
            int(uba_id),
            account_type=broker,
        )
        result["deleted_by"] = actor
        result["live_forced_off"] = True
        return result

    def apply_recommended_risk(
        self, uba_id: int, *, actor: str
    ) -> dict[str, Any]:
        row = self._session.get(UserBrokerAccount, int(uba_id))
        if row is None:
            raise UserAccountError("User broker account not found")
        if str(row.broker_code).upper() != "UPBIT":
            raise UserAccountError(
                "recommended risk applies to UPBIT accounts only"
            )
        UserRiskSettingService(self._session).upsert_account(
            int(uba_id),
            upbit_live_recommended_risk_payload(),
            actor=actor,
        )
        self._session.commit()
        return self.get_account(int(uba_id))

    def _enrich(
        self, base: dict[str, Any], row: UserBrokerAccount
    ) -> dict[str, Any]:
        out = dict(base)
        out["user_broker_account_id"] = int(row.user_broker_account_id)
        # STEP 2-5-1 — 관리자 조회 전용 필드(순수 추가, 기존 필드 무변경)
        out["deleted_at"] = (
            row.deleted_at.isoformat() if row.deleted_at else None
        )
        out["live_order_enabled"] = bool(row.live_order_enabled)
        out["live_armed"] = bool(row.live_armed)
        out["arm_expires_at"] = (
            row.arm_expires_at.isoformat() if row.arm_expires_at else None
        )
        try:
            policy = ResolvedRiskPolicyResolver(self._session).resolve(
                user_id=int(row.user_id),
                user_broker_account_id=int(row.user_broker_account_id),
            )
            out["risk"] = {
                "max_order_amount": str(policy.max_order_amount),
                "max_order_quantity": str(policy.max_order_quantity),
                "max_open_orders": int(policy.max_open_orders),
                "daily_order_limit": int(policy.daily_order_limit),
            }
        except Exception:  # noqa: BLE001
            out["risk"] = None
        try:
            from stock_platform.broker.credential_vault_service import (
                BrokerCredentialVaultService,
            )

            cred = BrokerCredentialVaultService(self._session).status(
                int(row.user_broker_account_id),
                broker_code=str(row.broker_code).upper(),
            )
            out["credential"] = {
                "registered": bool(cred.connected),
                "verification_status": cred.verification_status,
                "masked_identifier": cred.masked_identifier,
                "vault_available": bool(cred.vault_available),
            }
        except Exception:  # noqa: BLE001
            out["credential"] = {
                "registered": False,
                "verification_status": None,
                "masked_identifier": None,
                "vault_available": False,
            }
        return out
