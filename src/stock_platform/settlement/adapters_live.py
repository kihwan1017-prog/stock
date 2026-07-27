"""STEP 8-5-17 — Kiwoom/Upbit Settlement Adapter (UBA Binding + Freshness)."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from stock_platform.broker.account_repository import (
    BrokerAccountSnapshotRepository,
)
from stock_platform.broker.snapshot_freshness import (
    evaluate_snapshot_freshness,
)
from stock_platform.common.settings import get_settings
from stock_platform.settlement.broker_adapter import (
    SettlementBrokerBundle,
    SettlementCashSnapshot,
    SettlementPositionSnapshot,
)
from stock_platform.settlement.pnl import d
from stock_platform.trading.account_models import UserBrokerAccount


class _LiveSnapshotSettlementAdapter:
    """UBA FK로만 Snapshot 조회 — broker 최신 휴리스틱 금지."""

    broker_code: str

    def __init__(
        self,
        session: Session,
        *,
        user_broker_account_id: int,
        broker_code: str,
    ) -> None:
        self._session = session
        self._uba_id = int(user_broker_account_id)
        self.broker_code = broker_code.upper()

    def fetch_bundle(self) -> SettlementBrokerBundle:
        now = datetime.now(timezone.utc)
        broker = self.broker_code
        settings = get_settings()
        uba = self._session.get(UserBrokerAccount, self._uba_id)
        if uba is None:
            return SettlementBrokerBundle(
                broker_code=broker,
                fetched_at=now,
                cash=SettlementCashSnapshot(),
                sync_ok=False,
                sync_error="UBA_NOT_FOUND",
            )
        if str(uba.broker_code).upper() != broker:
            return SettlementBrokerBundle(
                broker_code=broker,
                fetched_at=now,
                cash=SettlementCashSnapshot(),
                sync_ok=False,
                sync_error="SNAPSHOT_BROKER_MISMATCH",
                meta={"uba_id": self._uba_id},
            )

        repo = BrokerAccountSnapshotRepository(self._session)
        snap, positions_rows = repo.get_active_by_uba(self._uba_id)
        freshness = evaluate_snapshot_freshness(
            snapshot=snap,
            expected_uba_id=self._uba_id,
            expected_broker_code=broker,
            max_age_seconds=int(
                settings.settlement_price_max_age_seconds
            ),
            now=now,
        )
        if not freshness.ok:
            return SettlementBrokerBundle(
                broker_code=broker,
                fetched_at=now,
                cash=SettlementCashSnapshot(),
                sync_ok=False,
                sync_error=freshness.reason
                or "BROKER_DATA_UNAVAILABLE",
                meta={
                    "uba_id": self._uba_id,
                    "freshness": {
                        "age_seconds": freshness.age_seconds,
                        "max_age_seconds": freshness.max_age_seconds,
                        "snapshot_status": freshness.snapshot_status,
                        "snapshot_generation": (
                            freshness.snapshot_generation
                        ),
                        "snapshot_hash": freshness.snapshot_hash,
                    },
                },
            )

        assert snap is not None
        positions = [
            SettlementPositionSnapshot(
                exchange_code=str(
                    getattr(p, "exchange_code", None) or broker
                ),
                symbol=str(p.symbol),
                quantity=d(p.quantity),
                average_price=d(p.average_purchase_price),
                evaluation_amount=d(p.evaluation_amount),
                unrealized_pnl=d(p.profit_loss),
            )
            for p in positions_rows
        ]
        cash = SettlementCashSnapshot(
            available=d(snap.available_order_amount),
            total=d(snap.deposit_amount),
            buying_power=d(snap.available_order_amount),
        )
        return SettlementBrokerBundle(
            broker_code=broker,
            fetched_at=now,
            cash=cash,
            positions=positions,
            equity=d(snap.total_evaluation_amount),
            meta={
                "broker_account_snapshot_id": int(
                    snap.broker_account_snapshot_id
                ),
                "synchronized_at": snap.synchronized_at.isoformat()
                if snap.synchronized_at
                else None,
                "snapshot_time": snap.snapshot_time.isoformat()
                if snap.snapshot_time
                else None,
                "snapshot_generation": int(snap.snapshot_generation),
                "snapshot_version": int(snap.snapshot_version),
                "snapshot_hash": snap.snapshot_hash,
                "snapshot_status": snap.snapshot_status,
                "source": "broker_account_snapshot_uba_bound",
                "uba_id": self._uba_id,
                "freshness_age_seconds": freshness.age_seconds,
            },
            sync_ok=True,
        )


class KiwoomSettlementAdapter(_LiveSnapshotSettlementAdapter):
    def __init__(
        self, session: Session, *, user_broker_account_id: int
    ) -> None:
        super().__init__(
            session,
            user_broker_account_id=user_broker_account_id,
            broker_code="KIWOOM",
        )


class UpbitSettlementAdapter(_LiveSnapshotSettlementAdapter):
    def __init__(
        self, session: Session, *, user_broker_account_id: int
    ) -> None:
        super().__init__(
            session,
            user_broker_account_id=user_broker_account_id,
            broker_code="UPBIT",
        )


def build_live_settlement_adapter(
    session: Session,
    *,
    user_broker_account_id: int,
    broker_code: str,
) -> _LiveSnapshotSettlementAdapter:
    code = broker_code.upper()
    if code == "UPBIT":
        return UpbitSettlementAdapter(
            session, user_broker_account_id=user_broker_account_id
        )
    return KiwoomSettlementAdapter(
        session, user_broker_account_id=user_broker_account_id
    )
