from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.broker.kiwoom.execution_models import (
    KiwoomExecutionEvent,
)
from stock_platform.broker.kiwoom.fill_position_write import (
    apply_kiwoom_fill_position_write,
    ensure_kiwoom_position_after_sync,
)
from stock_platform.broker.kiwoom.inquiry_client import (
    KiwoomOrderInquiryClient,
)
from stock_platform.broker.kiwoom.inquiry_models import (
    KiwoomExecution,
)
from stock_platform.order.entities import TradingOrderEntity
from stock_platform.order.models import OrderStatus
from stock_platform.order.repository import (
    TradingOrderRepository,
)
from stock_platform.trading.execution_sync_service import (
    ExecutionSyncService,
)

_KST = ZoneInfo("Asia/Seoul")

_OPEN_STATUSES = (
    OrderStatus.PENDING.value,
    OrderStatus.SENT.value,
    OrderStatus.ACCEPTED.value,
    OrderStatus.PARTIALLY_FILLED.value,
)


@dataclass(frozen=True, slots=True)
class KiwoomRecoverySummary:
    inspected_pending: int
    matched_orders: int
    missing_local_orders: int
    position_writes: int = 0
    inspected_executions: int = 0
    reconciled_from_executions: int = 0
    new_executions: int = 0


def _norm_broker_order_id(value: Any) -> str:
    """선행 0 무시 비교용 (0048830 == 48830)."""

    text = str(value or "").strip()
    if not text:
        return ""
    stripped = text.lstrip("0")
    return stripped or "0"


def _parse_ord_tm(raw: dict[str, Any]) -> datetime:
    """ord_tm(HHMMSS) → 당일 KST → UTC. 없으면 now."""

    tm = str(raw.get("ord_tm") or raw.get("cntr_tm") or "").strip()
    digits = "".join(ch for ch in tm if ch.isdigit())
    if len(digits) >= 6:
        hh = int(digits[0:2])
        mm = int(digits[2:4])
        ss = int(digits[4:6])
        if 0 <= hh <= 23 and 0 <= mm <= 59 and 0 <= ss <= 59:
            local = datetime.now(_KST).replace(
                hour=hh,
                minute=mm,
                second=ss,
                microsecond=0,
            )
            return local.astimezone(timezone.utc)
    return datetime.now(timezone.utc)


def _side_from_raw(raw: dict[str, Any], fallback: str | None) -> str | None:
    text = str(
        raw.get("io_tp_nm")
        or raw.get("side_code")
        or fallback
        or ""
    ).upper()
    if "매도" in text or text in {"SELL", "S", "-"}:
        return "SELL"
    if "매수" in text or text in {"BUY", "B", "+"}:
        return "BUY"
    return fallback


class KiwoomOrderRecoveryService:
    def __init__(
        self,
        *,
        session: Session,
        inquiry_client: KiwoomOrderInquiryClient,
    ) -> None:
        self._session = session
        self._repository = TradingOrderRepository(session)
        self._inquiry_client = inquiry_client

    def recover_pending_orders(
        self,
        *,
        account_number: str,
        actor: str = "KIWOOM_RECOVERY",
    ) -> KiwoomRecoverySummary:
        inspected = 0
        matched = 0
        missing = 0
        position_writes = 0
        next_key: str | None = None

        while True:
            page = self._inquiry_client.get_pending_orders(
                account_number=account_number,
                continuation_key=next_key,
            )

            for pending in page.items:
                inspected += 1
                entity = self._repository.get_by_broker_order_id(
                    broker_code="KIWOOM",
                    broker_order_id=pending.broker_order_id,
                )

                if entity is None:
                    missing += 1
                    continue

                matched += 1
                local_filled = Decimal(str(entity.filled_quantity or 0))
                remote_filled = Decimal(str(pending.filled_quantity or 0))
                remaining = Decimal(str(pending.remaining_quantity or 0))
                entity.filled_quantity = remote_filled
                entity.remaining_quantity = remaining

                current = OrderStatus(entity.status_code)

                # 전량 체결 → FILLED / 부분 체결 → PARTIALLY_FILLED
                if remote_filled > 0 and remaining <= 0:
                    if current in {
                        OrderStatus.ACCEPTED,
                        OrderStatus.PARTIALLY_FILLED,
                    }:
                        self._repository.change_status(
                            entity=entity,
                            new_status=OrderStatus.FILLED,
                            actor=actor,
                            reason_code="RECOVERED_FULL_FILL",
                            commit=False,
                        )
                elif (
                    remote_filled > 0
                    and remaining > 0
                    and current == OrderStatus.ACCEPTED
                ):
                    self._repository.change_status(
                        entity=entity,
                        new_status=OrderStatus.PARTIALLY_FILLED,
                        actor=actor,
                        reason_code="RECOVERED_PARTIAL_FILL",
                        commit=False,
                    )

                # P0-2 — 증분 체결만 FILL_DRIVEN position 반영
                delta = remote_filled - local_filled
                fill_px = (
                    getattr(entity, "average_fill_price", None)
                    or pending.order_price
                )
                if (
                    delta > 0
                    and fill_px is not None
                    and Decimal(str(fill_px)) > 0
                    and entity.user_broker_account_id is not None
                ):
                    exec_id = (
                        f"RECOVERY:{pending.broker_order_id}:{remote_filled}"
                    )
                    side = str(
                        getattr(entity, "side_code", None)
                        or pending.side_code
                        or ""
                    ).upper()
                    event = KiwoomExecutionEvent(
                        broker_order_id=str(pending.broker_order_id),
                        broker_execution_id=exec_id,
                        symbol=str(
                            entity.symbol or pending.symbol or ""
                        ).upper(),
                        side_code=side or None,
                        execution_price=Decimal(str(fill_px)),
                        execution_quantity=delta,
                        remaining_quantity=Decimal(
                            str(pending.remaining_quantity or 0)
                        ),
                        executed_at=datetime.now(timezone.utc),
                        raw_payload={
                            "source": "KIWOOM_RECOVERY",
                            "account_number": account_number,
                        },
                    )
                    applied = apply_kiwoom_fill_position_write(
                        self._session,
                        order=entity,
                        event=event,
                        actor=actor,
                        commit=False,
                    )
                    if applied.get("applied"):
                        position_writes += 1

            if not page.has_next or not page.next_key:
                break

            next_key = page.next_key

        self._session.commit()
        return KiwoomRecoverySummary(
            inspected_pending=inspected,
            matched_orders=matched,
            missing_local_orders=missing,
            position_writes=position_writes,
        )

    def recover_open_orders_from_executions(
        self,
        *,
        account_number: str,
        user_broker_account_id: int | None = None,
        actor: str = "KIWOOM_EXECUTION_RECOVERY",
        max_pages: int = 30,
    ) -> KiwoomRecoverySummary:
        """pending에서 빠진 전량체결 주문을 ka10076로 ACCEPTED→FILLED 정합.

        BUY/SELL 공통. broker_order_id 매칭. ExecutionSync + ledger idempotent.
        """

        open_orders = self._list_open_kiwoom_orders(
            user_broker_account_id=user_broker_account_id,
        )
        if not open_orders:
            return KiwoomRecoverySummary(
                inspected_pending=0,
                matched_orders=0,
                missing_local_orders=0,
            )

        by_norm_id = {
            _norm_broker_order_id(o.broker_order_id): o
            for o in open_orders
            if o.broker_order_id
        }

        executions = self._fetch_all_executions(
            account_number=account_number,
            max_pages=max_pages,
        )
        # 동일 주문번호가 여러 행이면 최신(가장 큰 체결수량) 우선
        best_by_ord: dict[str, KiwoomExecution] = {}
        for item in executions:
            key = _norm_broker_order_id(item.broker_order_id)
            if not key:
                continue
            prev = best_by_ord.get(key)
            if prev is None or item.execution_quantity >= prev.execution_quantity:
                best_by_ord[key] = item

        matched = 0
        reconciled = 0
        new_executions = 0
        position_writes = 0

        for norm_id, order in by_norm_id.items():
            remote = best_by_ord.get(norm_id)
            if remote is None:
                continue
            matched += 1
            result = self._apply_execution_snapshot(
                order=order,
                remote=remote,
                actor=actor,
            )
            if result.get("reconciled"):
                reconciled += 1
            new_executions += int(result.get("new_executions") or 0)
            position_writes += int(result.get("position_writes") or 0)

        return KiwoomRecoverySummary(
            inspected_pending=0,
            matched_orders=matched,
            missing_local_orders=0,
            position_writes=position_writes,
            inspected_executions=len(executions),
            reconciled_from_executions=reconciled,
            new_executions=new_executions,
        )

    def reconcile_order_from_broker(
        self,
        *,
        order_id: int,
        account_number: str,
        actor: str = "KIWOOM_ORDER_RECONCILE",
        max_pages: int = 30,
    ) -> dict[str, Any]:
        """단일 TradingOrder를 ka10076 SoT로 정합 (공식 경로)."""

        order = self._repository.get(int(order_id))
        if order is None:
            return {"ok": False, "reason": "ORDER_NOT_FOUND"}
        if str(order.broker_code or "").upper() != "KIWOOM":
            return {"ok": False, "reason": "NOT_KIWOOM"}
        broker_order_id = str(order.broker_order_id or "").strip()
        if not broker_order_id:
            return {"ok": False, "reason": "BROKER_ORDER_ID_MISSING"}

        before = {
            "status": str(order.status_code),
            "filled_quantity": str(order.filled_quantity or 0),
            "remaining_quantity": str(order.remaining_quantity or 0),
        }

        target = _norm_broker_order_id(broker_order_id)
        remote: KiwoomExecution | None = None
        # 종목 필터로 조회량 축소 (가능하면)
        extra: dict[str, Any] = {"qry_tp": "0", "sell_tp": "0", "stex_tp": "0"}
        sym = str(order.symbol or "").replace("A", "").strip()
        if sym:
            extra = {
                "qry_tp": "1",
                "stk_cd": sym,
                "sell_tp": "0",
                "stex_tp": "0",
            }

        next_key: str | None = None
        inspected = 0
        for _ in range(max(1, int(max_pages))):
            page = self._inquiry_client.get_executions(
                account_number=account_number,
                continuation_key=next_key,
                extra_body=extra,
            )
            for item in page.items:
                inspected += 1
                if _norm_broker_order_id(item.broker_order_id) == target:
                    if (
                        remote is None
                        or item.execution_quantity
                        >= remote.execution_quantity
                    ):
                        remote = item
            if not page.has_next or not page.next_key:
                break
            next_key = page.next_key

        if remote is None:
            return {
                "ok": False,
                "reason": "BROKER_EXECUTION_NOT_FOUND",
                "BROKER_FINAL_STATUS": "NOT_FOUND",
                "before": before,
                "inspected_executions": inspected,
            }

        raw = dict(remote.raw_payload or {})
        remaining = Decimal(
            str(
                raw.get("oso_qty")
                if raw.get("oso_qty") not in (None, "")
                else max(
                    Decimal(str(order.order_quantity or 0))
                    - Decimal(str(remote.execution_quantity or 0)),
                    Decimal("0"),
                )
            )
        )
        filled = Decimal(str(remote.execution_quantity or 0))
        if filled > 0 and remaining <= 0:
            broker_status = "FILLED"
        elif filled > 0:
            broker_status = "PARTIAL"
        else:
            broker_status = "WAIT"

        applied = self._apply_execution_snapshot(
            order=order,
            remote=remote,
            actor=actor,
        )
        self._session.refresh(order)
        after = {
            "status": str(order.status_code),
            "filled_quantity": str(order.filled_quantity or 0),
            "remaining_quantity": str(order.remaining_quantity or 0),
            "average_fill_price": (
                str(order.average_fill_price)
                if order.average_fill_price is not None
                else None
            ),
        }
        return {
            "ok": True,
            "BROKER_FINAL_STATUS": broker_status,
            "broker_order_id": broker_order_id,
            "broker_filled_qty": str(filled),
            "broker_remaining": str(remaining),
            "broker_fill_price": str(remote.execution_price),
            "broker_fill_time": str(raw.get("ord_tm") or ""),
            "before": before,
            "after": after,
            "inspected_executions": inspected,
            **applied,
        }

    def _list_open_kiwoom_orders(
        self,
        *,
        user_broker_account_id: int | None,
        limit: int = 200,
    ) -> list[TradingOrderEntity]:
        stmt = (
            select(TradingOrderEntity)
            .where(
                TradingOrderEntity.broker_code == "KIWOOM",
                TradingOrderEntity.status_code.in_(_OPEN_STATUSES),
                TradingOrderEntity.broker_order_id.is_not(None),
            )
            .order_by(TradingOrderEntity.updated_at.asc())
            .limit(max(1, int(limit)))
        )
        if user_broker_account_id is not None:
            stmt = stmt.where(
                TradingOrderEntity.user_broker_account_id
                == int(user_broker_account_id)
            )
        return list(self._session.scalars(stmt).all())

    def _fetch_all_executions(
        self,
        *,
        account_number: str,
        max_pages: int,
    ) -> list[KiwoomExecution]:
        items: list[KiwoomExecution] = []
        next_key: str | None = None
        for _ in range(max(1, int(max_pages))):
            page = self._inquiry_client.get_executions(
                account_number=account_number,
                continuation_key=next_key,
            )
            items.extend(page.items)
            if not page.has_next or not page.next_key:
                break
            next_key = page.next_key
        return items

    def _apply_execution_snapshot(
        self,
        *,
        order: TradingOrderEntity,
        remote: KiwoomExecution,
        actor: str,
    ) -> dict[str, Any]:
        local_filled = Decimal(str(order.filled_quantity or 0))
        remote_filled = Decimal(str(remote.execution_quantity or 0))
        raw = dict(remote.raw_payload or {})
        remaining = Decimal(
            str(
                raw.get("oso_qty")
                if raw.get("oso_qty") not in (None, "")
                else max(
                    Decimal(str(order.order_quantity or 0)) - remote_filled,
                    Decimal("0"),
                )
            )
        )
        delta = remote_filled - local_filled
        if delta <= 0:
            # 이미 ExecutionSync된 경우에도 position ledger 누락 가능 → idempotent 재적용
            if remote_filled <= 0:
                return {
                    "reconciled": False,
                    "reason": "NO_DELTA",
                    "new_executions": 0,
                    "position_writes": 0,
                }
            fill_px = remote.execution_price
            if fill_px is None or Decimal(str(fill_px)) <= 0:
                return {
                    "reconciled": bool(
                        OrderStatus(order.status_code) == OrderStatus.FILLED
                    ),
                    "reason": "NO_FILL_PRICE",
                    "new_executions": 0,
                    "position_writes": 0,
                }
            exec_num = remote.execution_number
            broker_execution_id = str(
                exec_num
                or f"KA10076:{remote.broker_order_id}:{remote_filled}:{fill_px}"
            )
            side = _side_from_raw(
                raw,
                str(getattr(order, "side_code", None) or "") or None,
            )
            event = KiwoomExecutionEvent(
                broker_order_id=str(
                    order.broker_order_id or remote.broker_order_id
                ),
                broker_execution_id=broker_execution_id,
                symbol=str(order.symbol or remote.symbol or "").upper(),
                side_code=side,
                execution_price=Decimal(str(fill_px)),
                execution_quantity=remote_filled,
                remaining_quantity=remaining,
                executed_at=_parse_ord_tm(raw),
                raw_payload={
                    **raw,
                    "source": "KIWOOM_EXECUTION_RECOVERY_LEDGER_RETRY",
                },
            )
            position: dict[str, Any] = {"applied": False}
            try:
                position = ensure_kiwoom_position_after_sync(
                    self._session,
                    order=order,
                    event=event,
                    actor=actor,
                )
            except Exception as exc:  # noqa: BLE001
                try:
                    self._session.rollback()
                except Exception:  # noqa: BLE001
                    pass
                position = {
                    "applied": False,
                    "reason": "ENSURE_FAILED",
                    "error": type(exc).__name__,
                }
            return {
                "reconciled": True,
                "reason": "ALREADY_SYNCED_LEDGER_RETRY",
                "new_executions": 0,
                "position_writes": 1 if position.get("applied") else 0,
                "position_reason": position.get("reason"),
                "execution_id": None,
                "order_status": str(order.status_code),
            }

        fill_px = remote.execution_price
        if fill_px is None or Decimal(str(fill_px)) <= 0:
            return {
                "reconciled": False,
                "reason": "NO_FILL_PRICE",
                "new_executions": 0,
                "position_writes": 0,
            }

        exec_num = remote.execution_number
        broker_execution_id = str(
            exec_num
            or f"KA10076:{remote.broker_order_id}:{remote_filled}:{fill_px}"
        )
        side = _side_from_raw(
            raw,
            str(getattr(order, "side_code", None) or "") or None,
        )
        event = KiwoomExecutionEvent(
            broker_order_id=str(order.broker_order_id or remote.broker_order_id),
            broker_execution_id=broker_execution_id,
            symbol=str(order.symbol or remote.symbol or "").upper(),
            side_code=side,
            execution_price=Decimal(str(fill_px)),
            execution_quantity=delta,
            remaining_quantity=remaining,
            executed_at=_parse_ord_tm(raw),
            raw_payload={
                **raw,
                "source": "KIWOOM_EXECUTION_RECOVERY",
                "remote_filled": str(remote_filled),
            },
        )

        sync = ExecutionSyncService(self._session).synchronize(
            event,
            actor=actor,
        )
        # ExecutionSync 내부 ledger 실패 시에만 재적용 (이미 성공하면 DUPLICATE)
        position: dict[str, Any] = {"applied": False, "reason": "SKIPPED"}
        try:
            position = ensure_kiwoom_position_after_sync(
                self._session,
                order=order,
                event=event,
                actor=actor,
            )
        except Exception as exc:  # noqa: BLE001
            try:
                self._session.rollback()
            except Exception:  # noqa: BLE001
                pass
            position = {
                "applied": False,
                "reason": "ENSURE_FAILED",
                "error": type(exc).__name__,
            }
        return {
            "reconciled": bool(sync.order_found)
            and (not sync.duplicate or sync.order_status is not None),
            "reason": "OK" if sync.order_found else "ORDER_NOT_FOUND",
            "duplicate": sync.duplicate,
            "execution_id": sync.execution_id,
            "order_status": sync.order_status,
            "new_executions": 0 if sync.duplicate else (1 if sync.execution_id else 0),
            "position_writes": 1 if position.get("applied") else 0,
            "position_reason": position.get("reason"),
        }

