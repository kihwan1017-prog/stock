"""STEP 10-1 — Upbit 체결 동기화 → Execution 멱등 저장 → Post-fill enqueue.

실주문 재제출 없음. Broker get_order 조회만 수행.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from stock_platform.broker.upbit.order_status import (
    ZERO,
    _dec,
    normalize_upbit_order_status,
    upbit_fill_summary,
)
from stock_platform.order.live_safety_audit import emit_live_safety_audit
from stock_platform.order.models import OrderStatus
from stock_platform.order.repository import TradingOrderRepository
from stock_platform.trading.execution_repository import (
    TradingExecutionRepository,
)

BROKER_CODE = "UPBIT"


@dataclass(frozen=True, slots=True)
class UpbitFillSyncResult:
    order_id: int
    duplicate_executions: int
    new_executions: int
    order_status: str | None
    post_fill_enqueued: bool
    already_processed: bool
    detail: dict[str, Any]


class UpbitFillSyncService:
    """원격 Upbit 주문 → DB order/execution/post-fill 단일 진입점."""

    def __init__(
        self,
        session: Session,
        *,
        order_client: Any | None = None,
    ) -> None:
        self._session = session
        self._orders = TradingOrderRepository(session)
        self._executions = TradingExecutionRepository(session)
        self._order_client = order_client

    def sync_by_order_id(
        self,
        order_id: int,
        *,
        actor: str = "UPBIT_FILL_SYNC",
        remote: dict[str, Any] | None = None,
    ) -> UpbitFillSyncResult:
        order = self._orders.get(int(order_id))
        if order is None:
            return UpbitFillSyncResult(
                order_id=int(order_id),
                duplicate_executions=0,
                new_executions=0,
                order_status=None,
                post_fill_enqueued=False,
                already_processed=False,
                detail={"error": "ORDER_NOT_FOUND"},
            )
        if str(order.broker_code or "").upper() != BROKER_CODE:
            return UpbitFillSyncResult(
                order_id=int(order_id),
                duplicate_executions=0,
                new_executions=0,
                order_status=order.status_code,
                post_fill_enqueued=False,
                already_processed=False,
                detail={"error": "NOT_UPBIT"},
            )

        broker_uuid = str(order.broker_order_id or "").strip()
        if not broker_uuid and remote is None:
            return UpbitFillSyncResult(
                order_id=int(order_id),
                duplicate_executions=0,
                new_executions=0,
                order_status=order.status_code,
                post_fill_enqueued=False,
                already_processed=False,
                detail={"error": "BROKER_ORDER_ID_MISSING"},
            )

        payload = remote
        if payload is None:
            client = self._resolve_client(order)
            payload = client.get_order(uuid=broker_uuid)

        return self.apply_remote(
            order=order,
            remote=payload,
            actor=actor,
        )

    def apply_remote(
        self,
        *,
        order: Any,
        remote: dict[str, Any],
        actor: str = "UPBIT_FILL_SYNC",
    ) -> UpbitFillSyncResult:
        target = normalize_upbit_order_status(remote)
        summary = upbit_fill_summary(remote)
        if target is None:
            return UpbitFillSyncResult(
                order_id=int(order.order_id),
                duplicate_executions=0,
                new_executions=0,
                order_status=order.status_code,
                post_fill_enqueued=False,
                already_processed=False,
                detail={"error": "UNMAPPED_STATE", "summary": _jsonable(summary)},
            )

        # 이미 최종 상태면 execution만 멱등 보강.
        # STEP 9-6처럼 수동 Reconcile만 FILLED 된 경우 Post-fill이
        # 없을 수 있으므로, 체결이 있으면 Post-fill을 멱등 enqueue 한다.
        current = OrderStatus(order.status_code)
        if current in {OrderStatus.FILLED, OrderStatus.CANCELLED} and (
            current == target
        ):
            dup, new_ids = self._upsert_trades(
                order=order, remote=remote, actor=actor
            )
            post_fill = False
            if target in {
                OrderStatus.FILLED,
                OrderStatus.PARTIALLY_FILLED,
            } and (summary["executed_volume"] > ZERO or new_ids):
                post_fill = self._enqueue_post_fill(
                    order=order,
                    execution_id=new_ids[-1] if new_ids else None,
                    actor=actor,
                )
            return UpbitFillSyncResult(
                order_id=int(order.order_id),
                duplicate_executions=dup,
                new_executions=len(new_ids),
                order_status=order.status_code,
                post_fill_enqueued=post_fill,
                already_processed=True,
                detail={"summary": _jsonable(summary)},
            )

        self._ensure_accepted(order=order, actor=actor)

        uuid = str(
            remote.get("uuid") or order.broker_order_id or ""
        ).strip()
        if uuid and not order.broker_order_id:
            order.broker_order_id = uuid

        identifier = remote.get("identifier")
        if identifier and hasattr(order, "upbit_client_identifier"):
            order.upbit_client_identifier = str(identifier)

        dup, new_ids = self._upsert_trades(
            order=order, remote=remote, actor=actor
        )

        executed = summary["executed_volume"]
        avg = summary["avg_price"]
        if executed > ZERO:
            order.filled_quantity = executed
            order_qty = Decimal(str(order.order_quantity or 0))
            # 시장가 매수는 order_quantity placeholder일 수 있음 → remaining=0
            if target == OrderStatus.FILLED:
                order.remaining_quantity = ZERO
            else:
                order.remaining_quantity = max(ZERO, order_qty - executed)
            if avg > ZERO:
                order.average_fill_price = avg
            order.filled_amount = (
                Decimal(str(order.filled_quantity))
                * Decimal(str(order.average_fill_price or avg or 0))
            )

        if OrderStatus(order.status_code) != target:
            # CANCELLED→FILLED 등 잘못된 선행 매핑은 허용하지 않음
            # SUBMITTING/ACCEPTED→FILLED 정상 경로만
            self._orders.change_status(
                entity=order,
                new_status=target,
                actor=actor,
                reason_code="UPBIT_FILL_SYNC",
                message=(
                    f"state={summary['state']} "
                    f"executed={summary['executed_volume']}"
                ),
                commit=False,
            )

        self._session.flush()
        emit_live_safety_audit(
            self._session,
            event_type="EXECUTION_RECORDED",
            actor=actor,
            run_id=None,
            user_id=getattr(order, "user_id", None),
            account_id=getattr(order, "user_broker_account_id", None),
            strategy_id=None,
            detail={
                "order_id": int(order.order_id),
                "broker_code": BROKER_CODE,
                "new_executions": len(new_ids),
                "duplicate_executions": dup,
                "order_status": order.status_code,
                "executed_volume": str(summary["executed_volume"]),
            },
            commit=False,
        )

        post_fill = False
        if target in {OrderStatus.FILLED, OrderStatus.PARTIALLY_FILLED} and (
            executed > ZERO or new_ids
        ):
            post_fill = self._enqueue_post_fill(
                order=order,
                execution_id=new_ids[-1] if new_ids else None,
                actor=actor,
            )

        # LIVE/UBA 원장 — 신규 체결만 Position/Cash 반영
        if new_ids and getattr(order, "user_broker_account_id", None):
            self._apply_live_fill_ledger(
                order=order,
                remote=remote,
                new_execution_ids=new_ids,
                actor=actor,
            )

        return UpbitFillSyncResult(
            order_id=int(order.order_id),
            duplicate_executions=dup,
            new_executions=len(new_ids),
            order_status=order.status_code,
            post_fill_enqueued=post_fill,
            already_processed=False,
            detail={"summary": _jsonable(summary)},
        )

    def _upsert_trades(
        self,
        *,
        order: Any,
        remote: dict[str, Any],
        actor: str,
    ) -> tuple[int, list[int]]:
        trades = remote.get("trades")
        if not isinstance(trades, list) or not trades:
            # trades 없으면 executed_volume 기반 synthetic id
            executed = _dec(remote.get("executed_volume"))
            if executed <= ZERO:
                return 0, []
            broker_uuid = str(remote.get("uuid") or order.broker_order_id)
            synthetic_id = f"{broker_uuid}:executed:{executed}"
            return self._insert_one(
                order=order,
                broker_order_id=broker_uuid,
                broker_execution_id=synthetic_id,
                price=_dec(remote.get("avg_price"))
                or _dec(remote.get("price")),
                quantity=executed,
                executed_at=datetime.now(timezone.utc),
                raw={"source": "executed_volume", "remote": _safe_remote(remote)},
            )

        dup = 0
        new_ids: list[int] = []
        broker_uuid = str(remote.get("uuid") or order.broker_order_id)
        for trade in trades:
            if not isinstance(trade, dict):
                continue
            trade_uuid = str(trade.get("uuid") or "").strip()
            if not trade_uuid:
                trade_uuid = (
                    f"{broker_uuid}:{trade.get('created_at')}:"
                    f"{trade.get('volume')}:{trade.get('price')}"
                )
            d, ids = self._insert_one(
                order=order,
                broker_order_id=broker_uuid,
                broker_execution_id=trade_uuid,
                price=_dec(trade.get("price")),
                quantity=_dec(trade.get("volume")),
                executed_at=_parse_dt(trade.get("created_at")),
                raw={
                    "source": "trade",
                    "trade": {
                        k: trade.get(k)
                        for k in (
                            "uuid",
                            "price",
                            "volume",
                            "funds",
                            "side",
                            "created_at",
                            "market",
                        )
                        if k in trade
                    },
                    "paid_fee": remote.get("paid_fee"),
                    "actor": actor,
                },
            )
            dup += d
            new_ids.extend(ids)
        return dup, new_ids

    def _insert_one(
        self,
        *,
        order: Any,
        broker_order_id: str,
        broker_execution_id: str,
        price: Decimal,
        quantity: Decimal,
        executed_at: datetime,
        raw: dict[str, Any],
    ) -> tuple[int, list[int]]:
        if quantity <= ZERO:
            return 0, []
        if self._executions.exists(
            broker_code=BROKER_CODE,
            broker_execution_id=str(broker_execution_id),
        ):
            return 1, []
        try:
            with self._session.begin_nested():
                entity = self._executions.create_raw(
                    order_id=int(order.order_id),
                    broker_code=BROKER_CODE,
                    broker_order_id=str(broker_order_id),
                    broker_execution_id=str(broker_execution_id),
                    symbol=str(order.symbol),
                    side_code=(
                        str(order.side_code) if order.side_code else None
                    ),
                    execution_price=price if price > ZERO else Decimal("0"),
                    execution_quantity=quantity,
                    executed_at=executed_at,
                    raw_json=raw,
                )
                self._session.flush()
            return 0, [int(entity.execution_id)]
        except IntegrityError:
            return 1, []

    def _enqueue_post_fill(
        self,
        *,
        order: Any,
        execution_id: int | None,
        actor: str,
    ) -> bool:
        try:
            from stock_platform.order.post_fill_runner import (
                PostFillVerifyRunner,
            )

            PostFillVerifyRunner(self._session).verify_after_order_fill(
                order=order,
                execution_id=execution_id,
                actor=actor,
            )
            emit_live_safety_audit(
                self._session,
                event_type="POST_FILL_STARTED",
                actor=actor,
                run_id=None,
                user_id=getattr(order, "user_id", None),
                account_id=getattr(order, "user_broker_account_id", None),
                strategy_id=None,
                detail={"order_id": int(order.order_id)},
                commit=False,
            )
            return True
        except Exception as exc:  # noqa: BLE001
            emit_live_safety_audit(
                self._session,
                event_type="POST_FILL_FAILED",
                actor=actor,
                run_id=None,
                user_id=getattr(order, "user_id", None),
                account_id=getattr(order, "user_broker_account_id", None),
                strategy_id=None,
                detail={
                    "order_id": int(order.order_id),
                    "error": f"{type(exc).__name__}:{exc}"[:300],
                },
                commit=False,
            )
            return False

    def _ensure_accepted(self, *, order: Any, actor: str) -> None:
        status = OrderStatus(order.status_code)
        if status in {
            OrderStatus.ACCEPTED,
            OrderStatus.PARTIALLY_FILLED,
            OrderStatus.FILLED,
            OrderStatus.CANCELLED,
        }:
            return
        # CREATED/PENDING/SUBMITTING/SENT → ACCEPTED
        if status == OrderStatus.CREATED:
            self._orders.change_status(
                entity=order,
                new_status=OrderStatus.PENDING,
                actor=actor,
                reason_code="UPBIT_FILL_NORMALIZE",
                commit=False,
            )
            status = OrderStatus.PENDING
        if status == OrderStatus.PENDING:
            self._orders.change_status(
                entity=order,
                new_status=OrderStatus.SENT,
                actor=actor,
                reason_code="UPBIT_FILL_NORMALIZE",
                commit=False,
            )
            status = OrderStatus.SENT
        if status == OrderStatus.SUBMITTING:
            self._orders.change_status(
                entity=order,
                new_status=OrderStatus.ACCEPTED,
                actor=actor,
                reason_code="UPBIT_FILL_NORMALIZE",
                commit=False,
            )
            return
        if status == OrderStatus.SENT:
            self._orders.change_status(
                entity=order,
                new_status=OrderStatus.ACCEPTED,
                actor=actor,
                reason_code="UPBIT_FILL_NORMALIZE",
                commit=False,
            )

    def _apply_live_fill_ledger(
        self,
        *,
        order: Any,
        remote: dict[str, Any],
        new_execution_ids: list[int],
        actor: str,
    ) -> None:
        """신규 Upbit 체결 → LiveFillLedgerService (Position/Cash)."""

        try:
            from stock_platform.broker.kiwoom.execution_models import (
                KiwoomExecutionEvent,
            )
            from stock_platform.broker.live_fill_ledger_service import (
                LiveFillLedgerService,
            )
            from stock_platform.trading.execution_entities import (
                TradingExecution,
            )

            ledger = LiveFillLedgerService(self._session)
            for eid in new_execution_ids:
                row = self._session.get(TradingExecution, int(eid))
                if row is None:
                    continue
                qty = Decimal(str(row.execution_quantity or 0))
                price = Decimal(str(row.execution_price or 0))
                if qty <= ZERO or price <= ZERO:
                    continue
                event = KiwoomExecutionEvent(
                    broker_order_id=str(
                        row.broker_order_id or order.broker_order_id or ""
                    ),
                    broker_execution_id=str(row.broker_execution_id),
                    symbol=str(order.symbol),
                    side_code=str(order.side_code or ""),
                    execution_price=price,
                    execution_quantity=qty,
                    remaining_quantity=Decimal(
                        str(order.remaining_quantity or 0)
                    ),
                    executed_at=row.executed_at
                    or datetime.now(timezone.utc),
                    raw_payload={
                        "source": "UPBIT_FILL_SYNC",
                        "remote": _safe_remote(remote),
                    },
                )
                ledger.apply_execution(
                    order=order, event=event, actor=actor
                )
            self._session.flush()
        except Exception:  # noqa: BLE001
            # 원장 실패가 fill sync 성공을 롤백하지 않음
            pass

    def _resolve_client(self, order: Any) -> Any:
        if self._order_client is not None:
            return self._order_client
        uba_id = getattr(order, "user_broker_account_id", None)
        if uba_id is None:
            raise ValueError("UBA_REQUIRED_FOR_UPBIT_FILL_SYNC")
        from stock_platform.broker.credential_adapter_factory import (
            build_upbit_adapter_for_uba,
        )

        return build_upbit_adapter_for_uba(
            self._session, int(uba_id)
        )._client  # noqa: SLF001


def _parse_dt(value: Any) -> datetime:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value
    text = str(value or "").strip()
    if not text:
        return datetime.now(timezone.utc)
    try:
        # 2026-07-27T13:22:53+09:00
        return datetime.fromisoformat(text)
    except ValueError:
        return datetime.now(timezone.utc)


def _jsonable(payload: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in payload.items():
        if isinstance(value, Decimal):
            out[key] = str(value)
        else:
            out[key] = value
    return out


def _safe_remote(remote: dict[str, Any]) -> dict[str, Any]:
    allowed = {
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
        "identifier",
    }
    return {k: remote.get(k) for k in allowed if k in remote}
