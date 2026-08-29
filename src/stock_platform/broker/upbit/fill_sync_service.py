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
            # 과거 Upbit 경로 binding 누락 복구 (멱등)
            if target == OrderStatus.FILLED and getattr(
                order, "user_broker_account_id", None
            ):
                self._apply_strategy_owned_binding(
                    order=order, remote=remote, actor=actor
                )
                # EXIT monitor 등 strategy_id 누락 SELL도 finalizer로 복구
                self._finalize_filled_exit_if_needed(
                    order=order, remote=remote, actor=actor
                )
                self._reconcile_portfolio_slot_after_fill(
                    order=order, actor=actor
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

        # 원장을 post-fill 검증보다 먼저 반영 — 스냅샷 race 완화
        if new_ids and getattr(order, "user_broker_account_id", None):
            self._apply_live_fill_ledger(
                order=order,
                remote=remote,
                new_execution_ids=new_ids,
                actor=actor,
            )
        elif (
            target in {OrderStatus.FILLED, OrderStatus.PARTIALLY_FILLED}
            and executed > ZERO
            and getattr(order, "user_broker_account_id", None)
        ):
            # execution 이미 있거나 synthetic 없이 상태만 승격된 경우에도 binding 반영
            self._apply_strategy_owned_binding(
                order=order, remote=remote, actor=actor
            )
            if target == OrderStatus.FILLED:
                self._finalize_filled_exit_if_needed(
                    order=order, remote=remote, actor=actor
                )
                self._reconcile_portfolio_slot_after_fill(
                    order=order, actor=actor
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
        # 오분류 FAILED + broker_order_id 존재 시 fill-sync 전 ACCEPTED로 복구
        if status == OrderStatus.FAILED and str(
            getattr(order, "broker_order_id", None) or ""
        ).strip():
            self._orders.change_status(
                entity=order,
                new_status=OrderStatus.ACCEPTED,
                actor=actor,
                reason_code="UPBIT_FILL_NORMALIZE_FAILED_RECOVERY",
                message="broker_order_id present; recover FAILED before fill apply",
                commit=False,
            )
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
        """신규 Upbit 체결 → LiveFillLedger + StrategyOwned binding."""

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

        # Kiwoom과 동일 — strategy-owned binding OPEN/CLOSED
        self._apply_strategy_owned_binding(
            order=order, remote=remote, actor=actor
        )
        self._finalize_filled_exit_if_needed(
            order=order, remote=remote, actor=actor
        )
        self._reconcile_portfolio_slot_after_fill(order=order, actor=actor)

    def _finalize_filled_exit_if_needed(
        self,
        *,
        order: Any,
        remote: dict[str, Any],
        actor: str,
    ) -> None:
        """SELL FILLED → canonical binding/slot finalizer (멱등)."""

        try:
            from stock_platform.broker.upbit.filled_exit_finalizer import (
                finalize_filled_exit,
                is_protective_or_auto_exit_sell,
            )

            if not is_protective_or_auto_exit_sell(order):
                return
            if str(getattr(order, "status_code", "") or "").upper() != "FILLED":
                return
            finalize_filled_exit(
                self._session,
                order=order,
                remote=remote if isinstance(remote, dict) else {},
                actor=f"FILL_SYNC:{actor}",
            )
        except Exception:  # noqa: BLE001
            pass

    def _reconcile_portfolio_slot_after_fill(
        self, *, order: Any, actor: str
    ) -> None:
        """UPBIT portfolio mode — slot/binding lifecycle 동기화 (멱등)."""

        uba_id = getattr(order, "user_broker_account_id", None)
        if uba_id is None:
            return
        if str(getattr(order, "broker_code", "") or "").upper() != "UPBIT":
            return
        try:
            from stock_platform.operation.upbit_full_market.constants import (
                is_full_market_portfolio,
            )
            from stock_platform.operation.upbit_full_market.portfolio_lifecycle_sync import (
                reconcile_portfolio_slot_lifecycle,
            )
            from stock_platform.operation.upbit_full_market.service import (
                UpbitFullMarketAssignmentService,
            )

            assignment = UpbitFullMarketAssignmentService(
                self._session
            ).get_or_create(int(uba_id))
            if not is_full_market_portfolio(assignment.mode):
                return
            reconcile_portfolio_slot_lifecycle(
                self._session,
                user_broker_account_id=int(uba_id),
                symbol=str(getattr(order, "symbol", "") or ""),
                actor=actor,
            )
        except Exception:  # noqa: BLE001
            pass

    def _apply_strategy_owned_binding(
        self,
        *,
        order: Any,
        remote: dict[str, Any],
        actor: str,
    ) -> None:
        """Upbit fill → StrategyOwnedRiskService binding (BUY OPEN / SELL CLOSE)."""

        uba_id = getattr(order, "user_broker_account_id", None)
        strategy_id = getattr(order, "strategy_id", None)
        if uba_id is None or strategy_id is None:
            meta = getattr(order, "metadata_payload", None) or {}
            if strategy_id is None and meta.get("strategy_id") is not None:
                try:
                    strategy_id = int(meta["strategy_id"])
                except (TypeError, ValueError):
                    strategy_id = None
        # EXIT monitor 등: OPEN binding에서 strategy_id 복구
        if strategy_id is None and uba_id is not None:
            try:
                from stock_platform.broker.upbit.filled_exit_finalizer import (
                    resolve_strategy_id_for_exit,
                    stamp_strategy_id_on_order,
                )

                strategy_id = resolve_strategy_id_for_exit(
                    self._session, order=order
                )
                if strategy_id is not None:
                    stamp_strategy_id_on_order(
                        self._session,
                        order=order,
                        strategy_id=int(strategy_id),
                    )
            except Exception:  # noqa: BLE001
                strategy_id = None
        if uba_id is None or strategy_id is None:
            return

        try:
            from stock_platform.broker.upbit.order_status import (
                upbit_fill_summary,
            )
            from stock_platform.risk_engine.strategy_owned_risk_service import (
                StrategyOwnedRiskService,
            )

            summary = upbit_fill_summary(remote)
            qty = Decimal(str(summary.get("executed_volume") or 0))
            if qty <= ZERO:
                qty = Decimal(str(order.filled_quantity or 0))
            px = Decimal(str(summary.get("avg_price") or 0))
            if px <= ZERO:
                px = Decimal(str(order.average_fill_price or 0))
            fees = Decimal(str(summary.get("paid_fee") or 0))
            side = str(order.side_code or "").upper()
            # SELL 청산 시 entry fee가 binding에 없으면 BUY meta에서 보강
            if side == "SELL":
                try:
                    from stock_platform.order.entities import TradingOrderEntity
                    from stock_platform.risk_engine.strategy_owned_entities import (
                        BINDING_STATUS_OPEN,
                        StrategyPositionBindingEntity,
                    )
                    from sqlalchemy import select

                    opens = list(
                        self._session.scalars(
                            select(StrategyPositionBindingEntity).where(
                                StrategyPositionBindingEntity.user_broker_account_id
                                == int(uba_id),
                                StrategyPositionBindingEntity.broker_code
                                == BROKER_CODE,
                                StrategyPositionBindingEntity.strategy_id
                                == int(strategy_id),
                                StrategyPositionBindingEntity.symbol
                                == str(order.symbol or "").upper(),
                                StrategyPositionBindingEntity.status
                                == BINDING_STATUS_OPEN,
                            )
                        )
                    )
                    for row in opens:
                        if Decimal(str(row.fees or 0)) > ZERO:
                            continue
                        eid = getattr(row, "entry_order_id", None)
                        if eid is None:
                            continue
                        buy = self._session.get(TradingOrderEntity, int(eid))
                        if buy is None:
                            continue
                        buy_meta = dict(
                            getattr(buy, "metadata_payload", None) or {}
                        )
                        entry_fee = Decimal(
                            str(buy_meta.get("upbit_paid_fee") or 0)
                        )
                        if entry_fee > ZERO:
                            row.fees = entry_fee
                except Exception:  # noqa: BLE001
                    pass
            filled_at = getattr(order, "filled_at", None)
            if filled_at is None:
                trades = remote.get("trades") if isinstance(remote, dict) else None
                if isinstance(trades, list) and trades:
                    filled_at = _parse_dt(trades[-1].get("created_at"))
            # broker trade 시각 우선 (reconcile 시각으로 덮어쓰지 않음)
            trades = remote.get("trades") if isinstance(remote, dict) else None
            if isinstance(trades, list) and trades:
                trade_ts = _parse_dt(trades[-1].get("created_at"))
                if trade_ts is not None:
                    filled_at = trade_ts
                    if getattr(order, "filled_at", None) is None or (
                        order.filled_at is not None
                        and abs(
                            (order.filled_at - trade_ts).total_seconds()
                        )
                        > 60
                    ):
                        # ACCEPTED 후 지연 체결 — broker SoT timestamp 반영
                        order.filled_at = trade_ts

            svc = StrategyOwnedRiskService(self._session)
            binding = svc.ensure_binding_from_fill(
                user_broker_account_id=int(uba_id),
                broker_code=BROKER_CODE,
                strategy_id=int(strategy_id),
                deployment_id=getattr(order, "strategy_deployment_id", None),
                symbol=str(order.symbol or ""),
                entry_order_id=(
                    int(order.order_id) if side == "BUY" else None
                ),
                broker_order_id=str(order.broker_order_id or "") or None,
                quantity=qty,
                entry_price=px if side == "BUY" else None,
                side=side,
                fees=fees,
                fill_price=px if side == "SELL" else None,
                exit_order_id=(
                    int(order.order_id) if side == "SELL" else None
                ),
                filled_at=filled_at,
            )
            # research-only entry observation (REAL gate 미사용)
            if side == "BUY" and binding is not None:
                try:
                    meta_o = dict(getattr(order, "metadata_payload", None) or {})
                    meta_b = dict(binding.meta_json or {})
                    entry_obs = dict(meta_b.get("entry_observation") or {})
                    entry_obs.update(
                        {
                            "entry_order_id": int(order.order_id),
                            "entry_reason": str(
                                meta_o.get("signal_reason")
                                or meta_o.get("entry_reason")
                                or "NOT_RECORDED"
                            ),
                            "entry_price": float(px) if px > ZERO else None,
                            "entry_at": filled_at.isoformat()
                            if filled_at is not None
                            and hasattr(filled_at, "isoformat")
                            else None,
                            "scanner_score": meta_o.get("scanner_score", "NOT_RECORDED"),
                            "scanner_rank": meta_o.get("scanner_rank", "NOT_RECORDED"),
                            "analysis_recommendation": meta_o.get(
                                "analysis_recommendation", "NOT_RECORDED"
                            ),
                            "trading_shadow_recommendation": meta_o.get(
                                "trading_shadow_recommendation", "NOT_RECORDED"
                            ),
                        }
                    )
                    meta_b["entry_observation"] = entry_obs
                    binding.meta_json = meta_b
                except Exception:  # noqa: BLE001
                    pass
            svc.compute_and_persist(
                user_broker_account_id=int(uba_id),
                broker_code=BROKER_CODE,
                strategy_id=int(strategy_id),
                deployment_id=getattr(order, "strategy_deployment_id", None),
            )
            self._session.flush()
            self._emit_fill_lifecycle_notifications(
                order=order,
                remote=remote,
                binding=binding,
                actor=actor,
            )
        except Exception:  # noqa: BLE001
            pass

    def _emit_fill_lifecycle_notifications(
        self,
        *,
        order: Any,
        remote: dict[str, Any],
        binding: Any,
        actor: str,
    ) -> None:
        """ORDER_FILLED (+ SELL 시 POSITION_CLOSED / REALIZED_PNL). 멱등 dedupe_key."""

        status = str(getattr(order, "status_code", "") or "").upper()
        if status not in {OrderStatus.FILLED.value, "FILLED"}:
            return
        try:
            from stock_platform.broker.upbit.order_status import (
                upbit_fill_summary,
            )
            from stock_platform.order.live_safety_audit import (
                emit_live_order_telegram,
            )
            from sqlalchemy.orm.attributes import flag_modified

            meta = dict(getattr(order, "metadata_payload", None) or {})
            if meta.get("fill_lifecycle_notified"):
                return

            summary = upbit_fill_summary(remote)
            qty = _dec_str(summary.get("executed_volume") or order.filled_quantity)
            avg = _dec_str(
                summary.get("avg_price") or order.average_fill_price or 0
            )
            fee = _dec_str(summary.get("paid_fee") or 0)
            symbol = str(order.symbol or "")
            side = str(order.side_code or "").upper()
            oid = int(order.order_id)
            signal_reason = str(
                meta.get("signal_reason")
                or meta.get("exit_reason")
                or ""
            ).upper()
            # AUTO provenance — Alert V2 (MANUAL/TEST 혼합 금지)
            order_source = str(
                getattr(order, "order_source", None)
                or meta.get("order_source")
                or ""
            ).upper()
            strategy_id = getattr(order, "strategy_id", None)
            deployment_id = getattr(order, "strategy_deployment_id", None)
            try:
                avg_d = Decimal(str(avg or 0))
                qty_d = Decimal(str(qty or 0))
                gross = (
                    str(avg_d * qty_d)
                    if avg_d > ZERO and qty_d > ZERO
                    else None
                )
            except Exception:  # noqa: BLE001
                gross = None

            binding_closed = (
                side == "SELL"
                and binding is not None
                and str(getattr(binding, "status", "")).upper() == "CLOSED"
            )
            # SELL+CLOSED는 POSITION_CLOSED 한 통으로 (ORDER_FILLED 중복 방지)
            if not binding_closed:
                emit_live_order_telegram(
                    event_type="ORDER_FILLED",
                    title=("매수 체결" if side == "BUY" else "매도 체결"),
                    message="",  # Alert V2 formatter가 본문 생성
                    detail={
                        "order_id": oid,
                        "symbol": symbol,
                        "symbol_name": meta.get("symbol_name")
                        or meta.get("korean_name"),
                        "side": side,
                        "filled_qty": qty,
                        "filled_quantity": qty,
                        "avg_fill_price": avg,
                        "average_fill_price": avg,
                        "fee": fee,
                        "gross_amount": gross,
                        "amount_krw": gross,
                        "broker_code": "UPBIT",
                        "market": "UPBIT",
                        "broker_order_id": order.broker_order_id,
                        "actor": actor,
                        "order_source": order_source or None,
                        "strategy_id": strategy_id,
                        "strategy_deployment_id": deployment_id,
                        "entry_reason": meta.get("entry_reason")
                        or meta.get("signal_reason"),
                        "ai_recommendation": meta.get("ai_recommendation"),
                        "ai_confidence": meta.get("ai_confidence")
                        or meta.get("confidence"),
                        "auto_slot_used": meta.get("auto_slot_used"),
                        "auto_slot_limit": meta.get("auto_slot_limit"),
                        "daily_entry_used": meta.get("daily_entry_used"),
                        "daily_entry_limit": meta.get("daily_entry_limit"),
                        "filled_at": getattr(order, "filled_at", None),
                        "dedupe_key": f"BUY_FILLED:{oid}"
                        if side == "BUY"
                        else f"SELL_FILLED:{oid}",
                    },
                )

            if binding_closed:
                    realized = Decimal(
                        str(getattr(binding, "realized_pnl", 0) or 0)
                    )
                    fees_b = Decimal(str(getattr(binding, "fees", 0) or 0))
                    net = realized - fees_b
                    entry = Decimal(
                        str(getattr(binding, "entry_price", 0) or 0)
                    )
                    sold = Decimal(
                        str(summary.get("executed_volume") or 0)
                    )
                    entry_cost = (
                        entry * sold if entry > ZERO and sold > ZERO else ZERO
                    )
                    pct = (
                        (net / entry_cost * Decimal("100"))
                        if entry_cost > ZERO
                        else ZERO
                    )
                    reason_ko = "전략 신호"
                    if (
                        "DEAD_CROSS" in signal_reason
                        or "MA_DEAD" in signal_reason
                    ):
                        reason_ko = "이동평균 데드크로스"
                    elif "STOP" in signal_reason:
                        reason_ko = "손절"
                    elif "TAKE" in signal_reason or "PROFIT" in signal_reason:
                        reason_ko = "목표수익 도달"
                    elif "TRAIL" in signal_reason:
                        reason_ko = "트레일링 스탑"
                    # reason_ko는 exit_reason 보강용 (formatter도 mapping 수행)
                    if not signal_reason and reason_ko:
                        signal_reason = "STRATEGY_SIGNAL"

                    hold_sec = None
                    try:
                        opened = getattr(binding, "opened_at", None)
                        closed = getattr(binding, "closed_at", None)
                        if opened is not None and closed is not None:
                            oa = opened
                            ca = closed
                            if getattr(oa, "tzinfo", None) is None:
                                from datetime import timezone as _tz

                                oa = oa.replace(tzinfo=_tz.utc)
                            if getattr(ca, "tzinfo", None) is None:
                                from datetime import timezone as _tz

                                ca = ca.replace(tzinfo=_tz.utc)
                            hold_sec = max(0, int((ca - oa).total_seconds()))
                    except Exception:  # noqa: BLE001
                        hold_sec = None

                    emit_live_order_telegram(
                        event_type="POSITION_CLOSED",
                        title="매도 체결",
                        message="",  # Alert V2 formatter
                        detail={
                            "order_id": oid,
                            "binding_id": getattr(
                                binding, "binding_id", None
                            ),
                            "symbol": symbol,
                            "symbol_name": meta.get("symbol_name")
                            or meta.get("korean_name"),
                            "side": "SELL",
                            "broker_code": "UPBIT",
                            "market": "UPBIT",
                            "entry_price": str(entry),
                            "exit_price": str(avg),
                            "filled_qty": qty,
                            "filled_quantity": qty,
                            "buy_amount": str(entry_cost)
                            if entry_cost > ZERO
                            else None,
                            "sell_amount": gross,
                            "realized_pnl": str(net),
                            "realized_pnl_pct": str(pct),
                            "fees": str(fees_b),
                            "total_fee": str(fees_b),
                            "exit_reason": signal_reason
                            or "STRATEGY_SIGNAL",
                            "holding_seconds": hold_sec,
                            "opened_at": getattr(binding, "opened_at", None),
                            "closed_at": getattr(binding, "closed_at", None),
                            "order_source": order_source or None,
                            "strategy_id": strategy_id,
                            "strategy_deployment_id": deployment_id,
                            "dedupe_key": f"SELL_FILLED:{oid}",
                        },
                    )
                    # REALIZED_PNL 별도 알림은 allowlist에서 제외 — POSITION_CLOSED에 포함

            meta["fill_lifecycle_notified"] = True
            order.metadata_payload = meta
            flag_modified(order, "metadata_payload")
        except Exception:  # noqa: BLE001
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
