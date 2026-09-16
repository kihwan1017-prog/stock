"""STEP 8-5-4 — Upbit 주문 대조 + remote-only 탐지."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.broker.upbit.order_client import UpbitOrderRestClient
from stock_platform.common.json_safe import to_jsonable
from stock_platform.common.settings import get_settings
from stock_platform.order.entities import TradingOrderEntity
from stock_platform.order.models import OrderStatus
from stock_platform.order.repository import TradingOrderRepository


# Snapshot에 허용하는 Upbit 주문 필드만 (Secret 금지)
_ALLOWED_REMOTE_KEYS = frozenset(
    {
        "uuid",
        "market",
        "side",
        "ord_type",
        "state",
        "created_at",
        "volume",
        "remaining_volume",
        "executed_volume",
        "price",
        "avg_price",
        "paid_fee",
        "trades_count",
        "time_in_force",
    }
)


def sanitize_upbit_order_snapshot(remote: dict[str, Any]) -> dict[str, Any]:
    """외부 응답에서 허용 필드만 추출. trades는 id/price/volume/funds/fee만.

    Decimal 등은 JSONB 저장을 위해 to_jsonable로 변환한다 (금액은 str 보존).
    """

    out: dict[str, Any] = {}
    for key in _ALLOWED_REMOTE_KEYS:
        if key in remote:
            out[key] = remote[key]
    trades = remote.get("trades")
    if isinstance(trades, list):
        cleaned_trades = []
        for trade in trades[:100]:
            if not isinstance(trade, dict):
                continue
            cleaned_trades.append(
                {
                    k: trade.get(k)
                    for k in (
                        "uuid",
                        "price",
                        "volume",
                        "funds",
                        "side",
                        "created_at",
                    )
                    if k in trade
                }
            )
        out["trades"] = cleaned_trades
    # fail-closed: 직렬화 불가 타입이면 TypeError
    return to_jsonable(out)


def mask_external_uuid(value: str | None) -> str:
    if not value:
        return "****"
    text = str(value).strip()
    if len(text) <= 8:
        return "****"
    return text[:4] + "…" + text[-4:]


class UpbitOrderReconcileService:
    """
    업비트 미체결/체결 REST 폴링 동기화.

    remote-only(외부에만 존재)는 자동 내부 생성하지 않고 목록으로 반환한다.
    """

    def __init__(
        self,
        session: Session,
        *,
        order_client: UpbitOrderRestClient | None = None,
    ) -> None:
        self._session = session
        self._settings = get_settings()
        self._client = order_client or UpbitOrderRestClient(
            settings=self._settings
        )
        self._orders = TradingOrderRepository(session)

    def reconcile_open_orders(
        self,
        *,
        limit: int = 50,
        user_broker_account_id: int | None = None,
    ) -> dict[str, Any]:
        if bool(self._client._settings.upbit_use_mock):  # noqa: SLF001
            return {
                "mode": "mock",
                "checked": 0,
                "updated": 0,
                "remote_only": 0,
                "conflicts": 0,
                "remote_only_orders": [],
                "message": "UPBIT_USE_MOCK=true — reconcile skipped",
            }

        remote_orders = self._client.list_orders(
            state="wait",
            limit=limit,
        )
        done_orders = self._client.list_orders(
            state="done",
            limit=min(limit, 20),
        )
        cancel_orders = self._client.list_orders(
            state="cancel",
            limit=min(limit, 20),
        )
        by_uuid = {
            str(row.get("uuid")): row
            for row in remote_orders + done_orders + cancel_orders
            if row.get("uuid")
        }

        updated = 0
        checked = 0
        stmt = select(TradingOrderEntity).where(
            TradingOrderEntity.broker_code == "UPBIT",
            TradingOrderEntity.status_code.in_(
                [
                    OrderStatus.PENDING.value,
                    OrderStatus.SUBMITTING.value,
                    OrderStatus.SENT.value,
                    OrderStatus.ACCEPTED.value,
                    OrderStatus.PARTIALLY_FILLED.value,
                ]
            ),
        )
        if user_broker_account_id is not None:
            stmt = stmt.where(
                TradingOrderEntity.user_broker_account_id
                == int(user_broker_account_id)
            )
        rows = list(self._session.scalars(stmt.limit(limit)))

        local_uuids: set[str] = set()
        # 전체 로컬 UUID 집합 (open + 과거) — 오탐 방지
        local_stmt = select(TradingOrderEntity.broker_order_id).where(
            TradingOrderEntity.broker_code == "UPBIT",
            TradingOrderEntity.broker_order_id.is_not(None),
        )
        if user_broker_account_id is not None:
            local_stmt = local_stmt.where(
                TradingOrderEntity.user_broker_account_id
                == int(user_broker_account_id)
            )
        for broker_id in self._session.scalars(local_stmt):
            if broker_id:
                local_uuids.add(str(broker_id))

        from stock_platform.broker.upbit.fill_sync_service import (
            UpbitFillSyncService,
        )

        # UBA scope면 vault 클라이언트 우선 — env 기본키로 오조회 방지
        scoped_client = self._client
        if user_broker_account_id is not None:
            try:
                from stock_platform.broker.credential_adapter_factory import (
                    build_upbit_adapter_for_uba,
                )

                scoped_client = build_upbit_adapter_for_uba(
                    self._session, int(user_broker_account_id)
                )._client  # noqa: SLF001
            except Exception:  # noqa: BLE001
                scoped_client = self._client

        fill_sync = UpbitFillSyncService(
            self._session, order_client=scoped_client
        )
        fill_results: list[dict[str, Any]] = []

        for entity in rows:
            checked += 1
            broker_id = entity.broker_order_id
            if not broker_id:
                continue
            remote = by_uuid.get(str(broker_id))
            before = entity.status_code
            try:
                # list에 없어도 UBA vault GET으로 terminal sync (재주문 없음)
                result = fill_sync.sync_by_order_id(
                    int(entity.order_id),
                    actor="UPBIT_RECONCILE",
                    remote=remote,
                )
            except Exception:
                continue
            if result.order_status != before or result.new_executions:
                updated += 1
            fill_results.append(
                {
                    "order_id": result.order_id,
                    "status": result.order_status,
                    "new_executions": result.new_executions,
                    "post_fill": result.post_fill_enqueued,
                }
            )

        if updated:
            self._session.flush()

        # remote-only: wait 목록 기준 (진행 중 외부 주문) + done 중 미매칭
        remote_only_orders: list[dict[str, Any]] = []
        for uuid, remote in by_uuid.items():
            if uuid in local_uuids:
                continue
            # 취소만 된 오래된 주문은 High risk로 유지하되 목록에 포함
            remote_only_orders.append(
                sanitize_upbit_order_snapshot(remote)
            )

        return {
            "mode": "live",
            "checked": checked,
            "updated": updated,
            "remote_open": len(remote_orders),
            "remote_only": len(remote_only_orders),
            "unmatched_remote": len(remote_only_orders),
            "conflicts": len(remote_only_orders),
            "remote_only_orders": remote_only_orders,
            "fill_sync": fill_results,
        }

    @staticmethod
    def _map_state(remote: dict[str, Any]) -> OrderStatus | None:
        from stock_platform.broker.upbit.order_status import (
            normalize_upbit_order_status,
        )

        return normalize_upbit_order_status(remote)


def mask_external_order_id(value: str | None) -> str:
    return mask_external_uuid(value)
