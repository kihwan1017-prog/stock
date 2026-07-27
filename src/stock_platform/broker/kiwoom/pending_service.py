from sqlalchemy.orm import Session

from stock_platform.broker.credential_vault_service import (
    BrokerCredentialVaultError,
    BrokerCredentialVaultService,
)
from stock_platform.broker.kiwoom.pending_mapper import KiwoomPendingOrderMapper
from stock_platform.broker.pending_repository import BrokerPendingOrderRepository
from stock_platform.trading.account_identity import (
    AccountIdentityError,
    AccountIdentityErrorCode,
)
from stock_platform.trading.account_masking import mask_account_number
from stock_platform.trading.account_models import UserBrokerAccount


class KiwoomPendingOrderService:
    def __init__(self, session: Session, client) -> None:
        self.client = client
        self.session = session
        self.repo = BrokerPendingOrderRepository(session)

    def _resolve_broker_account_number(self, uba_id: int) -> str:
        try:
            resolved = BrokerCredentialVaultService(
                self.session
            ).resolve_for_runtime(
                uba_id,
                expected_broker="KIWOOM",
                require_verified=False,
                touch_last_used=False,
            )
            acct = str(
                (resolved.payload or {}).get("account_number") or ""
            ).strip()
            if acct:
                return acct
        except (BrokerCredentialVaultError, AttributeError):
            pass
        # vault 없으면 클라이언트 기본 계좌 (어댑터 경계)
        if hasattr(self.client, "default_account_number"):
            acct = str(self.client.default_account_number or "").strip()
            if acct:
                return acct
        raise AccountIdentityError(
            AccountIdentityErrorCode.ACCOUNT_CONTEXT_MISSING,
            "cannot resolve broker account_number for pending sync",
        )

    async def synchronize(
        self,
        *,
        user_broker_account_id: int,
        account_number: str | None = None,
    ):
        """UBA 필수. account_number는 Broker API 전용(선택)."""

        uba_id = int(user_broker_account_id)
        uba = self.session.get(UserBrokerAccount, uba_id)
        if uba is None:
            raise AccountIdentityError(
                AccountIdentityErrorCode.UBA_REQUIRED,
                f"UBA not found: {uba_id}",
            )
        if str(uba.broker_code).upper() != "KIWOOM":
            raise AccountIdentityError(
                AccountIdentityErrorCode.ACCOUNT_RESOURCE_MISMATCH,
                "UBA broker must be KIWOOM",
            )

        broker_acct = (account_number or "").strip() or self._resolve_broker_account_number(
            uba_id
        )
        payload = await self.client.get_pending_orders(broker_acct)
        rows = KiwoomPendingOrderMapper.map_list(broker_acct, payload)
        count = self.repo.replace_for_uba(
            broker_code="KIWOOM",
            user_broker_account_id=uba_id,
            rows=rows,
            broker_account_number=broker_acct,
        )
        return {
            "broker_code": "KIWOOM",
            "user_broker_account_id": uba_id,
            "masked_account_ref": mask_account_number(broker_acct),
            "pending_order_count": count,
        }

    async def modify(self, **kwargs):
        return await self.client.modify_order(**kwargs)

    async def cancel(self, **kwargs):
        return await self.client.cancel_order(**kwargs)
