"""외부 주문·체결 이력 멱등 보존 서비스."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.broker.external_order_history_entities import (
    BrokerExternalOrderHistoryEntity,
    BrokerExternalTradeHistoryEntity,
)
from stock_platform.broker.recovery_conflict_entities import (
    BrokerRecoveryConflictEntity,
)
from stock_platform.broker.upbit.order_reconcile_service import (
    mask_external_uuid,
    sanitize_upbit_order_snapshot,
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _dec(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except Exception:  # noqa: BLE001
        return None


def _parse_dt(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


class ExternalOrderHistoryService:
    """PRESERVE_REMOTE_HISTORY용 — trading_order 미생성."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def upsert_from_conflict(
        self,
        conflict: BrokerRecoveryConflictEntity,
        *,
        actor: str,
        import_policy: str = "PRESERVE_REMOTE_HISTORY",
    ) -> dict[str, Any]:
        """Conflict remote_snapshot 기반 멱등 저장."""

        broker = str(conflict.broker_code or "UPBIT").upper()
        uuid = str(conflict.external_order_id)
        snap = sanitize_upbit_order_snapshot(
            dict(conflict.remote_snapshot or {})
        )
        existing = self._session.scalar(
            select(BrokerExternalOrderHistoryEntity)
            .where(
                BrokerExternalOrderHistoryEntity.broker_code == broker,
                BrokerExternalOrderHistoryEntity.external_order_id == uuid,
            )
            .limit(1)
        )
        now = _utcnow()
        created = False
        if existing is None:
            existing = BrokerExternalOrderHistoryEntity(
                broker_code=broker,
                external_order_id=uuid,
            )
            self._session.add(existing)
            created = True

        existing.user_broker_account_id = conflict.user_broker_account_id
        existing.user_id = conflict.user_id
        existing.external_order_id_masked = (
            conflict.external_order_id_masked
            or mask_external_uuid(uuid)
        )
        existing.market_code = conflict.market_code or snap.get("market")
        existing.side_code = conflict.side_code
        existing.order_type_code = conflict.order_type_code
        existing.order_price = conflict.order_price or _dec(snap.get("price"))
        existing.requested_quantity = conflict.requested_quantity or _dec(
            snap.get("volume")
        )
        existing.executed_quantity = conflict.executed_quantity or _dec(
            snap.get("executed_volume")
        )
        existing.remaining_quantity = conflict.remaining_quantity or _dec(
            snap.get("remaining_volume")
        )
        existing.paid_fee = conflict.paid_fee or _dec(snap.get("paid_fee"))
        existing.locked_amount = _dec(snap.get("locked"))
        existing.external_status = conflict.external_status or snap.get(
            "state"
        )
        existing.external_created_at = (
            conflict.external_created_at
            or _parse_dt(snap.get("created_at"))
        )
        existing.external_done_at = _parse_dt(
            snap.get("done_at") or snap.get("updated_at")
        )
        existing.raw_snapshot = snap
        existing.import_policy = import_policy
        existing.source_conflict_id = int(
            conflict.broker_recovery_conflict_id
        )
        existing.imported_by = actor
        existing.imported_at = now
        existing.updated_at = now

        trades_saved = 0
        trades = snap.get("trades")
        if isinstance(trades, list):
            for trade in trades:
                if not isinstance(trade, dict):
                    continue
                trade_id = str(
                    trade.get("uuid")
                    or trade.get("trade_id")
                    or ""
                ).strip()
                if not trade_id:
                    # uuid 없으면 order+price+volume+time 합성 키
                    trade_id = (
                        f"{uuid}:"
                        f"{trade.get('price')}:"
                        f"{trade.get('volume')}:"
                        f"{trade.get('created_at')}"
                    )
                trades_saved += int(
                    self._upsert_trade(
                        broker=broker,
                        uba_id=conflict.user_broker_account_id,
                        order_id=uuid,
                        trade_id=trade_id,
                        trade=trade,
                        market=existing.market_code,
                        side=existing.side_code,
                        conflict_id=int(
                            conflict.broker_recovery_conflict_id
                        ),
                        actor=actor,
                    )
                )

        self._session.flush()
        return {
            "external_order_id_masked": existing.external_order_id_masked,
            "order_created": created,
            "trades_upserted": trades_saved,
            "source_conflict_id": int(
                conflict.broker_recovery_conflict_id
            ),
            "trading_order_created": False,
        }

    def _upsert_trade(
        self,
        *,
        broker: str,
        uba_id: int | None,
        order_id: str,
        trade_id: str,
        trade: dict[str, Any],
        market: str | None,
        side: str | None,
        conflict_id: int,
        actor: str,
    ) -> bool:
        existing = self._session.scalar(
            select(BrokerExternalTradeHistoryEntity)
            .where(
                BrokerExternalTradeHistoryEntity.broker_code == broker,
                BrokerExternalTradeHistoryEntity.external_trade_id
                == trade_id,
            )
            .limit(1)
        )
        created = False
        if existing is None:
            existing = BrokerExternalTradeHistoryEntity(
                broker_code=broker,
                external_trade_id=trade_id,
                external_order_id=order_id,
            )
            self._session.add(existing)
            created = True
        clean = {
            k: v
            for k, v in trade.items()
            if str(k).lower()
            not in {
                "access_key",
                "secret_key",
                "authorization",
                "credential",
            }
        }
        existing.user_broker_account_id = uba_id
        existing.market_code = market or trade.get("market")
        existing.side_code = side or trade.get("side")
        existing.trade_price = _dec(trade.get("price"))
        existing.trade_volume = _dec(trade.get("volume"))
        existing.funds = _dec(trade.get("funds"))
        existing.fee = _dec(trade.get("fee") or trade.get("paid_fee"))
        existing.executed_at = _parse_dt(
            trade.get("created_at") or trade.get("executed_at")
        )
        existing.raw_snapshot = clean
        existing.source_conflict_id = conflict_id
        existing.imported_by = actor
        existing.imported_at = _utcnow()
        return created
