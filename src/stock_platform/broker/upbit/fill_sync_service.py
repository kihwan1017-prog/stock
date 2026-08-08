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
    _dec_str,
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
        else:
            # trades_count>0 인데 trades[] 누락 → fee-inclusive avg_price 위험
            # 공식 GET으로 재조회 (WRITE 없음)
            payload = self._ensure_trades_payload(
                order=order,
                payload=payload,
                broker_uuid=broker_uuid,
            )

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

        # 이미 최종 상태면 execution 멱등 보강 + fill 필드 재동기화.
        # (과거 fee-inclusive avg / synthetic execution 정합화 포함)
        current = OrderStatus(order.status_code)
        if current in {OrderStatus.FILLED, OrderStatus.CANCELLED} and (
            current == target
        ):
            dup, new_ids = self._upsert_trades(
                order=order, remote=remote, actor=actor
            )
            self._apply_fill_fields(
                order=order, summary=summary, target=target
            )
            self._sync_live_validation_run(
                order=order, summary=summary, remote=remote, actor=actor
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

        self._apply_fill_fields(order=order, summary=summary, target=target)
        self._sync_live_validation_run(
            order=order, summary=summary, remote=remote, actor=actor
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

        executed = summary["executed_volume"]
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
            # Upbit avg_price는 fee 포함일 수 있어 사용 금지
            executed = _dec(remote.get("executed_volume"))
            if executed <= ZERO:
                return 0, []
            broker_uuid = str(remote.get("uuid") or order.broker_order_id)
            synthetic_id = f"{broker_uuid}:executed:{executed}"
            ord_type = str(remote.get("ord_type") or "").strip().lower()
            unit = _dec(remote.get("price"))
            # limit 단가만 신뢰. 시장가(price/market)는 trades 재조회 대기
            price = unit if ord_type == "limit" and unit > ZERO else ZERO
            return self._insert_one(
                order=order,
                broker_order_id=broker_uuid,
                broker_execution_id=synthetic_id,
                price=price,
                quantity=executed,
                executed_at=datetime.now(timezone.utc),
                raw={
                    "source": "executed_volume",
                    "remote": _safe_remote(remote),
                    "synthetic": True,
                    "note": "trades_missing_fallback",
                },
            )

        dup = 0
        new_ids: list[int] = []
        broker_uuid = str(remote.get("uuid") or order.broker_order_id)
        real_trade_uuids: list[str] = []
        for trade in trades:
            if not isinstance(trade, dict):
                continue
            trade_uuid = str(trade.get("uuid") or "").strip()
            if not trade_uuid:
                # trade UUID 없을 때만 합성 fallback
                trade_uuid = (
                    f"{broker_uuid}:{trade.get('created_at')}:"
                    f"{trade.get('volume')}:{trade.get('price')}"
                )
            else:
                real_trade_uuids.append(trade_uuid)
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
                    # order-level fee만 참고 저장 (trade별 분할 금지)
                    "order_paid_fee": remote.get("paid_fee"),
                    "actor": actor,
                },
            )
            dup += d
            new_ids.extend(ids)

        if real_trade_uuids:
            self._supersede_synthetic_executions(
                order=order,
                broker_uuid=broker_uuid,
                real_trade_uuids=real_trade_uuids,
            )
        return dup, new_ids

    def _apply_fill_fields(
        self,
        *,
        order: Any,
        summary: dict[str, Any],
        target: OrderStatus,
    ) -> None:
        """average_fill_price=fee 제외 VWAP, filled_amount=Σ funds."""

        executed = summary["executed_volume"]
        avg = summary["avg_price"]
        funds = summary["funds"]
        paid_fee = summary["paid_fee"]
        if executed <= ZERO:
            return

        order.filled_quantity = executed
        order_qty = Decimal(str(order.order_quantity or 0))
        if target == OrderStatus.FILLED:
            order.remaining_quantity = ZERO
        else:
            order.remaining_quantity = max(ZERO, order_qty - executed)

        if avg > ZERO:
            order.average_fill_price = avg
        if funds > ZERO:
            order.filled_amount = funds
        elif avg > ZERO:
            order.filled_amount = executed * avg

        # fee는 주문 컬럼이 없으므로 metadata에 공식 값 보관
        meta = dict(getattr(order, "metadata_payload", None) or {})
        meta["upbit_paid_fee"] = _dec_str(paid_fee)
        meta["upbit_fill_funds"] = _dec_str(funds)
        if avg > ZERO:
            meta["upbit_avg_fill_price"] = _dec_str(avg)
        # total_cost = funds + fee (참고용)
        meta["upbit_total_cost"] = _dec_str(funds + paid_fee)
        order.metadata_payload = meta
        try:
            from sqlalchemy.orm.attributes import flag_modified

            flag_modified(order, "metadata_payload")
        except Exception:  # noqa: BLE001
            pass

    def _supersede_synthetic_executions(
        self,
        *,
        order: Any,
        broker_uuid: str,
        real_trade_uuids: list[str],
    ) -> None:
        """실 trade UUID가 오면 synthetic row는 hard delete 대신 supersede."""

        prefix = f"{broker_uuid}:executed:"
        listed = self._executions.list_by_order_id(int(order.order_id))
        if not isinstance(listed, (list, tuple)):
            return
        rows = listed
        now = datetime.now(timezone.utc).isoformat()
        for row in rows:
            eid = str(getattr(row, "broker_execution_id", "") or "")
            if not eid.startswith(prefix):
                continue
            raw = dict(getattr(row, "raw_json", None) or {})
            if raw.get("superseded"):
                continue
            raw["superseded"] = True
            raw["superseded_at"] = now
            raw["superseded_by"] = list(real_trade_uuids)
            raw["supersede_reason"] = "REAL_TRADE_UUID_AVAILABLE"
            row.raw_json = raw
        self._session.flush()

    def _sync_live_validation_run(
        self,
        *,
        order: Any,
        summary: dict[str, Any],
        remote: dict[str, Any],
        actor: str,
    ) -> None:
        """FILLED run에 filled_qty/amount/avg/fee 동기화 (기존 컬럼 재사용)."""

        meta = getattr(order, "metadata_payload", None) or {}
        smoke_run_id = str(meta.get("smoke_run_id") or "").strip()
        if not smoke_run_id:
            return
        try:
            from sqlalchemy import select

            from stock_platform.trading.live_validation_entities import (
                LiveValidationRunEntity,
            )

            # PK는 live_validation_run_pk — run_id로 조회
            with self._session.begin_nested():
                run = self._session.scalar(
                    select(LiveValidationRunEntity).where(
                        LiveValidationRunEntity.run_id == smoke_run_id
                    )
                )
                if run is None:
                    return
                executed = summary["executed_volume"]
                avg = summary["avg_price"]
                funds = summary["funds"]
                paid_fee = summary["paid_fee"]
                if executed > ZERO:
                    run.filled_quantity = executed
                if avg > ZERO:
                    run.avg_fill_price = avg
                if funds > ZERO:
                    run.filled_amount = funds
                elif executed > ZERO and avg > ZERO:
                    run.filled_amount = executed * avg
                if paid_fee >= ZERO and summary.get("paid_fee") is not None:
                    run.fee_amount = paid_fee
                uuid = str(
                    remote.get("uuid") or order.broker_order_id or ""
                ).strip()
                if uuid:
                    run.broker_order_uuid = uuid
                if OrderStatus(order.status_code) == OrderStatus.FILLED:
                    run.broker_order_status = "FILLED"
                    run.order_status = OrderStatus.FILLED.value
                detail = dict(run.detail or {})
                detail["fill_sync"] = {
                    "actor": actor,
                    "avg_fill_price": _dec_str(avg) if avg > ZERO else None,
                    "filled_amount": _dec_str(funds) if funds > ZERO else None,
                    "paid_fee": _dec_str(paid_fee),
                    "executed_volume": _dec_str(executed),
                }
                run.detail = detail
                from sqlalchemy.orm.attributes import flag_modified

                flag_modified(run, "detail")
                self._session.flush()
        except Exception:  # noqa: BLE001
            return

    def _ensure_trades_payload(
        self,
        *,
        order: Any,
        payload: dict[str, Any],
        broker_uuid: str,
    ) -> dict[str, Any]:
        if not isinstance(payload, dict):
            return payload
        trades = payload.get("trades")
        trades_count = int(payload.get("trades_count") or 0)
        has_trades = isinstance(trades, list) and bool(trades)
        if has_trades or trades_count <= 0 or not broker_uuid:
            return payload
        try:
            client = self._resolve_client(order)
            refreshed = client.get_order(uuid=broker_uuid)
            if isinstance(refreshed, dict):
                return refreshed
        except Exception:  # noqa: BLE001
            pass
        return payload

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

            # savepoint — post-fill 실패가 fill sync commit을 깨지 않게
            with self._session.begin_nested():
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
            try:
                with self._session.begin_nested():
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
            except Exception:  # noqa: BLE001
                pass
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
            out[key] = _dec_str(value)
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
