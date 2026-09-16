from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import text as sql_text
from sqlalchemy.orm import Session

from stock_platform.broker.account_repository import (
    BrokerAccountSnapshotRepository,
    BrokerSnapshotBindingError,
)
from stock_platform.broker.upbit.account_mapper import (
    UpbitAccountMapper,
)
from stock_platform.broker.upbit.private_client import (
    UpbitPrivateClient,
)
from stock_platform.trading.account_models import UserBrokerAccount


class UpbitAccountSyncService:
    def __init__(
        self,
        *,
        session: Session,
        private_client: UpbitPrivateClient,
        user_broker_account_id: int | None = None,
    ) -> None:
        self._session = session
        self._client = private_client
        self._uba_id = (
            int(user_broker_account_id)
            if user_broker_account_id is not None
            else None
        )
        self._repository = BrokerAccountSnapshotRepository(session)

    def _resolve_uba_id(self, account_number: str) -> int:
        # STEP 8-5-18 — UBA 필수 (해시 휴리스틱 폴백 제거)
        if self._uba_id is None:
            raise BrokerSnapshotBindingError(
                "UPBIT sync requires user_broker_account_id"
            )
        uba = self._session.get(UserBrokerAccount, self._uba_id)
        if uba is None:
            raise BrokerSnapshotBindingError(
                f"UBA not found: {self._uba_id}"
            )
        if str(uba.broker_code).upper() != "UPBIT":
            raise BrokerSnapshotBindingError(
                "UBA broker_code must be UPBIT"
            )
        return int(self._uba_id)

    async def synchronize(
        self, *, user_broker_account_id: int | None = None
    ) -> dict:
        if user_broker_account_id is not None:
            self._uba_id = int(user_broker_account_id)
        accounts = await self._client.list_accounts()
        markets = [
            f"{str(row.get('unit_currency') or 'KRW').upper()}-"
            f"{str(row.get('currency') or '').upper()}"
            for row in accounts
            if isinstance(row, dict)
            and str(row.get("currency") or "").upper() not in ("", "KRW")
        ]
        tickers = await self._client.list_tickers(markets)
        tickers_by_market = {
            str(row.get("market") or "").upper(): row
            for row in tickers
            if row.get("market")
        }

        account_number = self._client.account_ref
        uba_id = self._resolve_uba_id(account_number)
        # UBA별 고유 account_number 저장 (MAIN 공유 충돌 방지)
        bound_account_number = f"UBA:{uba_id}"

        result = UpbitAccountMapper.map(
            account_number=bound_account_number,
            accounts=accounts,
            tickers_by_market=tickers_by_market,
        )
        entity = self._repository.save(
            result, user_broker_account_id=uba_id
        )

        # 스냅샷 저장과 별도로 UBA last_synced_at 갱신 (ops BALANCE_SYNC SoT)
        # text UPDATE: 부분 metadata(auth.user FK 미로드) 환경에서도 안전
        synced_at = result.synchronized_at
        if synced_at is None:
            synced_at = datetime.now(timezone.utc)
        self._session.execute(
            sql_text(
                """
                UPDATE trading.user_broker_account
                SET last_synced_at = :ts,
                    connection_status = 'CONNECTED',
                    updated_at = :ts
                WHERE user_broker_account_id = :uba
                """
            ),
            {"ts": synced_at, "uba": uba_id},
        )
        # repository.save가 이미 commit했을 수 있으므로 재커밋
        self._session.commit()

        return {
            "broker_account_snapshot_id": (
                entity.broker_account_snapshot_id
            ),
            "user_broker_account_id": uba_id,
            "broker_code": result.broker_code,
            "account_number": result.account_number,
            "deposit_amount": result.deposit_amount,
            "available_order_amount": (
                result.available_order_amount
            ),
            "total_evaluation_amount": (
                result.total_evaluation_amount
            ),
            "total_profit_loss": result.total_profit_loss,
            "position_count": len(result.positions),
            "synchronized_at": result.synchronized_at,
            "last_synced_at": (
                synced_at.isoformat()
                if hasattr(synced_at, "isoformat")
                else synced_at
            ),
            "snapshot_generation": int(entity.snapshot_generation),
            "snapshot_hash": entity.snapshot_hash,
            "snapshot_status": entity.snapshot_status,
            "mode": "mock" if self._client.use_mock else "live",
        }
