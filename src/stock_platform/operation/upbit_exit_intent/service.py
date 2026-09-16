# -*- coding: utf-8 -*-
"""Durable Exit Intent service — create / link / cooldown / revalidate / retry.

DB가 SoT. Historical backfill 금지. MA threshold/entry 변경 없음.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from stock_platform.common.settings import get_settings
from stock_platform.operation.upbit_exit_intent.constants import (
    ACTIVE_STATUSES,
    ATTEMPT_INITIAL,
    ATTEMPT_RETRY,
    DEFAULT_COOLDOWN_SECONDS,
    DEFAULT_MAX_RETRIES,
    EVT_BLOCKED,
    EVT_COMPLETED,
    EVT_CONDITION_CLEARED,
    EVT_COOLDOWN,
    EVT_CREATED,
    EVT_DETERMINISTIC_REJECT,
    EVT_EXHAUSTED,
    EVT_ORDER_LINKED,
    EVT_PARTIAL_FILL,
    EVT_RECOVERED,
    EVT_RETRY_SUBMITTED,
    EVT_REVALIDATED,
    EVT_ZERO_FILL_CANCELLED,
    EXIT_REASON_MA_DEAD_CROSS,
    DETERMINISTIC_REJECT_COOLDOWN_SECONDS,
    STATUS_BLOCKED,
    STATUS_COMPLETED,
    STATUS_CONDITION_CLEARED,
    STATUS_CONFIRMED,
    STATUS_COOLDOWN,
    STATUS_EXHAUSTED,
    STATUS_ORDER_PENDING,
    STATUS_REVALIDATING,
)
from stock_platform.operation.upbit_exit_intent.entities import (
    UpbitExitIntentEntity,
)
from stock_platform.realtime.ma_exit_policy import (
    is_dead_cross_confirmed,
    load_ma_exit_thresholds,
    ma_separation_pct,
)

ZERO = Decimal("0")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _settings_retries() -> tuple[int, int]:
    s = get_settings()
    cooldown = int(
        getattr(s, "upbit_exit_intent_retry_cooldown_seconds", None)
        or DEFAULT_COOLDOWN_SECONDS
    )
    max_r = int(
        getattr(s, "upbit_exit_intent_max_retries", None)
        or DEFAULT_MAX_RETRIES
    )
    return max(1, cooldown), max(0, max_r)


def feature_enabled() -> bool:
    s = get_settings()
    return bool(getattr(s, "upbit_exit_intent_retry_enabled", True))


class UpbitExitIntentService:
    """Canonical Exit Intent lifecycle (WRK-014)."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_active(
        self,
        *,
        user_broker_account_id: int,
        symbol: str,
        for_update: bool = False,
    ) -> UpbitExitIntentEntity | None:
        q = select(UpbitExitIntentEntity).where(
            UpbitExitIntentEntity.user_broker_account_id
            == int(user_broker_account_id),
            UpbitExitIntentEntity.symbol == str(symbol).upper(),
            UpbitExitIntentEntity.status.in_(tuple(ACTIVE_STATUSES)),
        )
        if for_update:
            q = q.with_for_update()
        return self._session.scalar(q.limit(1))

    def get_by_id(
        self, exit_intent_id: int, *, for_update: bool = False
    ) -> UpbitExitIntentEntity | None:
        q = select(UpbitExitIntentEntity).where(
            UpbitExitIntentEntity.exit_intent_id == int(exit_intent_id)
        )
        if for_update:
            q = q.with_for_update()
        return self._session.scalar(q.limit(1))

    def get_active_for_binding(
        self, binding_id: int
    ) -> UpbitExitIntentEntity | None:
        return self._session.scalar(
            select(UpbitExitIntentEntity)
            .where(
                UpbitExitIntentEntity.binding_id == int(binding_id),
                UpbitExitIntentEntity.status.in_(tuple(ACTIVE_STATUSES)),
            )
            .limit(1)
        )

    def create_on_confirmed(
        self,
        *,
        user_broker_account_id: int,
        symbol: str,
        exit_reason: str = EXIT_REASON_MA_DEAD_CROSS,
        binding_id: int | None = None,
        slot_id: int | None = None,
        strategy_id: int | None = None,
        strategy_version: str | None = None,
        signal_id: str | None = None,
        quantity: Decimal | None = None,
        detail: dict[str, Any] | None = None,
    ) -> UpbitExitIntentEntity | None:
        """MA confirmed → intent. Active 있으면 재사용(idempotent). No historical backfill."""

        if not feature_enabled():
            return None
        if str(exit_reason or "").upper() != EXIT_REASON_MA_DEAD_CROSS:
            return None

        sym = str(symbol).upper()
        existing = self.get_active(
            user_broker_account_id=int(user_broker_account_id),
            symbol=sym,
            for_update=True,
        )
        if existing is not None:
            return existing

        cooldown_s, max_r = _settings_retries()
        row = UpbitExitIntentEntity(
            user_broker_account_id=int(user_broker_account_id),
            symbol=sym,
            exit_reason=EXIT_REASON_MA_DEAD_CROSS,
            binding_id=binding_id,
            slot_id=slot_id,
            strategy_id=strategy_id,
            strategy_version=strategy_version,
            status=STATUS_CONFIRMED,
            initial_signal_id=signal_id,
            initial_confirmed_at=_now(),
            retry_count=0,
            max_retry_count=max_r,
            initial_quantity=quantity,
            remaining_quantity=quantity,
            detail_json={
                **(detail or {}),
                "cooldown_seconds": cooldown_s,
                "attempt_semantics": "INITIAL=0 RETRY=1..max",
            },
            event_log_json=[],
        )
        self._session.add(row)
        self._session.flush()
        self._append_event(row, EVT_CREATED, {"signal_id": signal_id})
        return row

    def link_order(
        self,
        *,
        exit_intent_id: int | None = None,
        user_broker_account_id: int | None = None,
        symbol: str | None = None,
        order_id: int,
        signal_id: str | None = None,
        is_retry: bool = False,
    ) -> UpbitExitIntentEntity | None:
        """Order persist 성공 시 link. retry면 retry_count+=1."""

        row = None
        if exit_intent_id is not None:
            row = self.get_by_id(int(exit_intent_id), for_update=True)
        elif user_broker_account_id is not None and symbol:
            row = self.get_active(
                user_broker_account_id=int(user_broker_account_id),
                symbol=str(symbol).upper(),
                for_update=True,
            )
        if row is None:
            return None

        oid = int(order_id)
        if row.initial_order_id is None:
            row.initial_order_id = oid
            if signal_id and not row.initial_signal_id:
                row.initial_signal_id = signal_id
        row.last_order_id = oid
        row.last_attempt_at = _now()
        row.status = STATUS_ORDER_PENDING
        row.last_block_reason = None
        if is_retry:
            row.retry_count = int(row.retry_count or 0) + 1
            self._append_event(
                row,
                EVT_RETRY_SUBMITTED,
                {"order_id": oid, "retry_count": row.retry_count},
            )
        else:
            self._append_event(
                row, EVT_ORDER_LINKED, {"order_id": oid, "kind": ATTEMPT_INITIAL}
            )
        row.updated_at = _now()
        return row

    def on_terminal_sell_cancel(
        self,
        *,
        order_id: int,
        user_broker_account_id: int,
        symbol: str,
        filled_quantity: Decimal | None = None,
        remaining_quantity: Decimal | None = None,
        cancel_at: datetime | None = None,
    ) -> UpbitExitIntentEntity | None:
        """Zero/partial fill cancel → COOLDOWN (intent 유지)."""

        if not feature_enabled():
            return None
        row = self.get_active(
            user_broker_account_id=int(user_broker_account_id),
            symbol=str(symbol).upper(),
            for_update=True,
        )
        if row is None:
            # last_order 매칭만 — active 없으면 historical 생성 금지
            return None
        if row.last_order_id is not None and int(row.last_order_id) != int(
            order_id
        ):
            if row.initial_order_id is None or int(
                row.initial_order_id
            ) != int(order_id):
                return None

        filled = filled_quantity if filled_quantity is not None else ZERO
        rem = remaining_quantity
        if rem is None:
            rem = self._broker_qty(
                int(user_broker_account_id), str(symbol).upper()
            )
        if rem is not None and rem <= ZERO:
            return self.mark_completed(row, remaining_quantity=ZERO)

        row.remaining_quantity = rem
        when = cancel_at or _now()
        cooldown_s, _ = _settings_retries()
        row.status = STATUS_COOLDOWN
        row.next_retry_at = when + timedelta(seconds=cooldown_s)
        row.updated_at = _now()
        evt = (
            EVT_PARTIAL_FILL
            if filled > ZERO
            else EVT_ZERO_FILL_CANCELLED
        )
        self._append_event(
            row,
            evt,
            {
                "order_id": int(order_id),
                "filled": str(filled),
                "remaining": str(rem) if rem is not None else None,
                "next_retry_at": row.next_retry_at.isoformat(),
            },
        )
        self._append_event(
            row,
            EVT_COOLDOWN,
            {"next_retry_at": row.next_retry_at.isoformat()},
        )
        return row

    def mark_completed(
        self,
        row: UpbitExitIntentEntity,
        *,
        remaining_quantity: Decimal | None = ZERO,
    ) -> UpbitExitIntentEntity:
        row.status = STATUS_COMPLETED
        row.remaining_quantity = remaining_quantity
        row.completed_at = _now()
        row.next_retry_at = None
        row.updated_at = _now()
        self._append_event(row, EVT_COMPLETED, {})
        return row

    def mark_condition_cleared(
        self, row: UpbitExitIntentEntity, *, detail: dict | None = None
    ) -> UpbitExitIntentEntity:
        row.status = STATUS_CONDITION_CLEARED
        row.completed_at = _now()
        row.next_retry_at = None
        row.last_condition_result = "FALSE"
        row.last_condition_checked_at = _now()
        row.updated_at = _now()
        self._append_event(row, EVT_CONDITION_CLEARED, detail or {})
        return row

    def mark_exhausted(
        self, row: UpbitExitIntentEntity
    ) -> UpbitExitIntentEntity:
        row.status = STATUS_EXHAUSTED
        row.completed_at = _now()
        row.next_retry_at = None
        row.updated_at = _now()
        self._append_event(
            row,
            EVT_EXHAUSTED,
            {"retry_count": int(row.retry_count or 0)},
        )
        self._notify_exhausted(row)
        return row

    def mark_blocked(
        self, row: UpbitExitIntentEntity, reason: str
    ) -> UpbitExitIntentEntity:
        row.status = STATUS_BLOCKED
        row.last_block_reason = str(reason or "BLOCKED")[:80]
        row.updated_at = _now()
        self._append_event(
            row, EVT_BLOCKED, {"reason": row.last_block_reason}
        )
        return row

    def note_deterministic_qty_reject(
        self,
        row: UpbitExitIntentEntity,
        *,
        reason_code: str,
        fingerprint: str,
        detail: dict[str, Any] | None = None,
    ) -> UpbitExitIntentEntity:
        """동일 상태에서 성공할 수 없는 reject — cooldown + fingerprint.

        상태(지문)가 바뀌기 전에는 재제출을 억제한다.
        """

        fp = str(fingerprint or "")[:200]
        detail_json = dict(row.detail_json or {})
        prev_fp = str(detail_json.get("deterministic_reject_fp") or "")
        same = bool(fp) and fp == prev_fp
        detail_json["deterministic_reject_fp"] = fp
        detail_json["deterministic_reject_reason"] = str(reason_code)[:80]
        detail_json["deterministic_reject_at"] = _now().isoformat()
        row.detail_json = detail_json
        flag_modified(row, "detail_json")
        row.last_block_reason = str(reason_code or "ORDER_QTY_EXCEEDED")[:80]
        row.status = STATUS_BLOCKED
        # 동일 지문이면 쿨다운 연장만; 새 지문이면 새 쿨다운
        row.next_retry_at = _now() + timedelta(
            seconds=DETERMINISTIC_REJECT_COOLDOWN_SECONDS
        )
        row.updated_at = _now()
        self._append_event(
            row,
            EVT_DETERMINISTIC_REJECT,
            {
                "reason": row.last_block_reason,
                "fingerprint": fp,
                "same_fingerprint": same,
                **(detail or {}),
            },
        )
        return row

    def should_suppress_sell_emit(
        self,
        *,
        user_broker_account_id: int,
        symbol: str,
        current_fingerprint: str | None = None,
    ) -> tuple[bool, str | None]:
        """deterministic reject cooldown 중이면 MA SELL 재발행 억제."""

        row = self.get_active(
            user_broker_account_id=int(user_broker_account_id),
            symbol=str(symbol).upper(),
            for_update=False,
        )
        if row is None:
            return False, None
        if row.status != STATUS_BLOCKED:
            return False, None
        reason = str(row.last_block_reason or "")
        if reason != "ORDER_QTY_EXCEEDED":
            return False, None
        detail = dict(row.detail_json or {})
        stored_fp = str(detail.get("deterministic_reject_fp") or "")
        if (
            current_fingerprint
            and stored_fp
            and str(current_fingerprint) != stored_fp
        ):
            # 수량 상태 변화 → 재평가 허용
            return False, None
        if row.next_retry_at and row.next_retry_at > _now():
            return True, "DETERMINISTIC_QTY_REJECT_COOLDOWN"
        return False, None

    def state_condition_still_true(
        self,
        *,
        short_ma: Decimal | None,
        long_ma: Decimal | None,
        risk_group_policy_json: dict[str, Any] | None = None,
    ) -> tuple[bool, dict[str, Any]]:
        """Retry용 STATE 재검증 — 새 edge 불필요."""

        th = load_ma_exit_thresholds(
            settings=get_settings(),
            risk_group_policy_json=risk_group_policy_json,
        )
        sep = ma_separation_pct(short_ma, long_ma)
        ok = is_dead_cross_confirmed(
            short_ma=short_ma,
            long_ma=long_ma,
            exit_min_ma_separation_pct=th.exit_min_ma_separation_pct,
        )
        return ok, {
            "short_ma": str(short_ma) if short_ma is not None else None,
            "long_ma": str(long_ma) if long_ma is not None else None,
            "gap_pct": sep,
            "threshold": th.exit_min_ma_separation_pct,
            "confirmed": ok,
        }

    def prepare_retry_or_none(
        self,
        *,
        user_broker_account_id: int,
        symbol: str,
        short_ma: Decimal | None,
        long_ma: Decimal | None,
        risk_group_policy_json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Tick 경로: due cooldown → revalidate → emit 허용 여부.

        Returns action dict:
          skip | cleared | exhausted | blocked_open_sell | emit_retry | wait
        """

        if not feature_enabled():
            return {"action": "skip", "reason": "FEATURE_OFF"}

        row = self.get_active(
            user_broker_account_id=int(user_broker_account_id),
            symbol=str(symbol).upper(),
            for_update=True,
        )
        if row is None:
            return {"action": "skip", "reason": "NO_ACTIVE_INTENT"}

        # ORDER_PENDING — open SELL reconcile only
        if row.status == STATUS_ORDER_PENDING:
            if self._has_open_sell(
                int(user_broker_account_id), str(symbol).upper()
            ):
                return {
                    "action": "blocked_open_sell",
                    "exit_intent_id": int(row.exit_intent_id),
                    "reason": "OPEN_SELL_EXISTS",
                }
            # order gone without cancel hook — treat as cooldown candidate
            rem = self._broker_qty(
                int(user_broker_account_id), str(symbol).upper()
            )
            if rem is None or rem <= ZERO:
                self.mark_completed(row, remaining_quantity=ZERO)
                return {
                    "action": "completed",
                    "exit_intent_id": int(row.exit_intent_id),
                }
            cooldown_s, _ = _settings_retries()
            row.status = STATUS_COOLDOWN
            row.next_retry_at = _now() + timedelta(seconds=cooldown_s)
            row.remaining_quantity = rem
            row.updated_at = _now()
            self._append_event(
                row,
                EVT_COOLDOWN,
                {"reason": "ORDER_PENDING_NO_OPEN_SELL"},
            )

        if row.status == STATUS_BLOCKED:
            # safety 회복 후 재평가 — due면 revalidate
            if row.next_retry_at and row.next_retry_at > _now():
                return {
                    "action": "wait",
                    "exit_intent_id": int(row.exit_intent_id),
                    "next_retry_at": row.next_retry_at.isoformat(),
                }

        if row.status == STATUS_COOLDOWN:
            if row.next_retry_at and row.next_retry_at > _now():
                return {
                    "action": "wait",
                    "exit_intent_id": int(row.exit_intent_id),
                    "next_retry_at": row.next_retry_at.isoformat(),
                    "retry_count": int(row.retry_count or 0),
                    "max_retry_count": int(row.max_retry_count or 3),
                }
            row.status = STATUS_REVALIDATING
            row.updated_at = _now()

        if row.status not in {
            STATUS_REVALIDATING,
            STATUS_CONFIRMED,
            STATUS_BLOCKED,
        }:
            return {
                "action": "skip",
                "reason": f"STATUS_{row.status}",
                "exit_intent_id": int(row.exit_intent_id),
            }

        rem = self._broker_qty(
            int(user_broker_account_id), str(symbol).upper()
        )
        if rem is None or rem <= ZERO:
            self.mark_completed(row, remaining_quantity=ZERO)
            return {
                "action": "completed",
                "exit_intent_id": int(row.exit_intent_id),
            }
        row.remaining_quantity = rem

        if self._has_open_sell(
            int(user_broker_account_id), str(symbol).upper()
        ):
            row.status = STATUS_ORDER_PENDING
            row.updated_at = _now()
            return {
                "action": "blocked_open_sell",
                "exit_intent_id": int(row.exit_intent_id),
                "reason": "OPEN_SELL_EXISTS",
            }

        ok, snap = self.state_condition_still_true(
            short_ma=short_ma,
            long_ma=long_ma,
            risk_group_policy_json=risk_group_policy_json,
        )
        row.last_condition_checked_at = _now()
        row.last_condition_result = "TRUE" if ok else "FALSE"
        self._append_event(row, EVT_REVALIDATED, snap)
        if not ok:
            self.mark_condition_cleared(row, detail=snap)
            return {
                "action": "cleared",
                "exit_intent_id": int(row.exit_intent_id),
                "condition": snap,
            }

        if int(row.retry_count or 0) >= int(row.max_retry_count or 3):
            self.mark_exhausted(row)
            return {
                "action": "exhausted",
                "exit_intent_id": int(row.exit_intent_id),
            }

        # CONFIRMED without initial order yet — not a retry
        if (
            row.status == STATUS_CONFIRMED
            and row.initial_order_id is None
            and int(row.retry_count or 0) == 0
        ):
            return {
                "action": "skip",
                "reason": "AWAIT_INITIAL_SELL",
                "exit_intent_id": int(row.exit_intent_id),
            }

        return {
            "action": "emit_retry",
            "exit_intent_id": int(row.exit_intent_id),
            "retry_count_before": int(row.retry_count or 0),
            "max_retry_count": int(row.max_retry_count or 3),
            "remaining_quantity": str(rem),
            "condition": snap,
            "attempt_kind": ATTEMPT_RETRY,
        }

    def recover_active_intents(
        self, *, user_broker_account_id: int | None = None
    ) -> dict[str, Any]:
        """Restart recovery — reconcile only, no forced SELL."""

        q = select(UpbitExitIntentEntity).where(
            UpbitExitIntentEntity.status.in_(tuple(ACTIVE_STATUSES))
        )
        if user_broker_account_id is not None:
            q = q.where(
                UpbitExitIntentEntity.user_broker_account_id
                == int(user_broker_account_id)
            )
        rows = list(self._session.scalars(q))
        recovered = 0
        for row in rows:
            rem = self._broker_qty(
                int(row.user_broker_account_id), str(row.symbol)
            )
            if rem is not None and rem <= ZERO:
                self.mark_completed(row, remaining_quantity=ZERO)
                recovered += 1
                continue
            if rem is not None:
                row.remaining_quantity = rem
            if row.status == STATUS_ORDER_PENDING:
                if not self._has_open_sell(
                    int(row.user_broker_account_id), str(row.symbol)
                ):
                    cooldown_s, _ = _settings_retries()
                    # preserve next_retry if set; else cooldown from now
                    if row.next_retry_at is None:
                        row.next_retry_at = _now() + timedelta(
                            seconds=cooldown_s
                        )
                    row.status = STATUS_COOLDOWN
            self._append_event(row, EVT_RECOVERED, {"status": row.status})
            row.updated_at = _now()
            recovered += 1
        return {"ok": True, "recovered": recovered, "count": len(rows)}

    def to_public(self, row: UpbitExitIntentEntity | None) -> dict[str, Any] | None:
        if row is None:
            return None
        retry = int(row.retry_count or 0)
        max_r = int(row.max_retry_count or 3)
        return {
            "exit_intent_id": int(row.exit_intent_id),
            "symbol": row.symbol,
            "exit_reason": row.exit_reason,
            "status": row.status,
            "status_label_ko": self.status_label_ko(row.status),
            "why_still_holding_ko": self.why_still_holding_ko(row),
            "retry_count": retry,
            "max_retry_count": max_r,
            "retry_display": f"{retry}/{max_r}",
            "attempt_semantics_ko": (
                "최초 청산 주문은 재시도가 아닙니다. "
                f"추가 재시도 {retry}/{max_r}회."
            ),
            "initial_order_id": row.initial_order_id,
            "last_order_id": row.last_order_id,
            "next_retry_at": (
                row.next_retry_at.isoformat() if row.next_retry_at else None
            ),
            "remaining_quantity": (
                str(row.remaining_quantity)
                if row.remaining_quantity is not None
                else None
            ),
            "last_condition_result": row.last_condition_result,
            "last_block_reason": row.last_block_reason,
            "binding_id": row.binding_id,
        }

    @staticmethod
    def status_label_ko(status: str) -> str:
        return {
            STATUS_CONFIRMED: "MA 청산 조건 확정",
            STATUS_ORDER_PENDING: "청산 주문 대기",
            STATUS_COOLDOWN: "청산 주문 미체결 · 재시도 대기",
            STATUS_REVALIDATING: "청산 조건 재검증",
            STATUS_COMPLETED: "청산 완료",
            STATUS_CONDITION_CLEARED: "청산 조건 해제 · 다음 교차 대기",
            STATUS_EXHAUSTED: "청산 재시도 한도 도달 · 확인 필요",
            STATUS_BLOCKED: "청산 재시도 차단(안전 게이트)",
            STATUS_CANCELLED: "청산 의도 취소",
        }.get(str(status), str(status))

    @staticmethod
    def why_still_holding_ko(row: UpbitExitIntentEntity) -> str:
        st = str(row.status)
        retry = int(row.retry_count or 0)
        max_r = int(row.max_retry_count or 3)
        if st == STATUS_COOLDOWN:
            return (
                f"청산 주문이 미체결되어 재시도 대기 중입니다 "
                f"(재시도 {retry}/{max_r}). "
                "60초 후 조건을 다시 확인합니다."
            )
        if st == STATUS_ORDER_PENDING:
            return "청산 주문이 제출되어 체결을 기다리는 중입니다."
        if st == STATUS_REVALIDATING:
            return "MA 청산 조건을 다시 확인하는 중입니다."
        if st == STATUS_CONDITION_CLEARED:
            return (
                "MA 청산 조건이 해제되어 다음 교차를 기다립니다."
            )
        if st == STATUS_EXHAUSTED:
            return (
                f"청산 주문 재시도 한도({max_r}회)에 도달했습니다. "
                "확인이 필요합니다."
            )
        if st == STATUS_BLOCKED:
            return (
                "안전 조건(LIVE/ARM 등)으로 청산 재시도가 일시 차단되었습니다."
            )
        if st == STATUS_CONFIRMED:
            return "MA 청산 조건을 감시·확정했습니다. 청산 주문을 준비합니다."
        return "전략 청산 상태를 확인 중입니다."

    def _broker_qty(self, uba_id: int, symbol: str) -> Decimal | None:
        try:
            from stock_platform.broker.account_models import (
                BrokerPositionSnapshotEntity,
            )

            held = self._session.scalar(
                select(BrokerPositionSnapshotEntity.quantity).where(
                    BrokerPositionSnapshotEntity.user_broker_account_id
                    == int(uba_id),
                    BrokerPositionSnapshotEntity.symbol == symbol,
                )
            )
            if held is None:
                return None
            return Decimal(str(held))
        except Exception:  # noqa: BLE001
            return None

    def _has_open_sell(self, uba_id: int, symbol: str) -> bool:
        try:
            from stock_platform.order.entities import TradingOrderEntity
            from stock_platform.risk_engine.exit_risk import (
                PENDING_SELL_STATUSES,
            )

            row = self._session.scalar(
                select(TradingOrderEntity.order_id)
                .where(
                    TradingOrderEntity.user_broker_account_id == int(uba_id),
                    TradingOrderEntity.symbol == symbol,
                    TradingOrderEntity.side_code == "SELL",
                    TradingOrderEntity.status_code.in_(
                        tuple(PENDING_SELL_STATUSES)
                    ),
                )
                .limit(1)
            )
            return row is not None
        except Exception:  # noqa: BLE001
            return True  # fail-closed: assume open sell

    def _append_event(
        self, row: UpbitExitIntentEntity, code: str, detail: dict
    ) -> None:
        log = list(row.event_log_json or [])
        log.append(
            {
                "at": _now().isoformat(),
                "event": code,
                "detail": detail,
            }
        )
        # 과도한 성장 방지
        if len(log) > 80:
            log = log[-80:]
        row.event_log_json = log
        flag_modified(row, "event_log_json")

    def _notify_exhausted(self, row: UpbitExitIntentEntity) -> None:
        try:
            from stock_platform.order.live_safety_audit import (
                emit_live_order_telegram,
            )

            dedupe = (
                f"EXIT_INTENT_EXHAUSTED:{row.user_broker_account_id}:"
                f"{row.symbol}:{row.exit_intent_id}"
            )
            emit_live_order_telegram(
                event_type="EXIT_INTENT_EXHAUSTED",
                title="[업비트] 자동 청산 재시도 한도 도달",
                message=(
                    f"{row.symbol} 청산 주문이 "
                    f"{int(row.max_retry_count or 3)}회 재시도 후에도 "
                    "체결되지 않았습니다."
                ),
                detail={
                    "dedupe_key": dedupe,
                    "exit_intent_id": int(row.exit_intent_id),
                    "symbol": str(row.symbol),
                    "user_broker_account_id": int(
                        row.user_broker_account_id
                    ),
                    "retry_count": int(row.retry_count or 0),
                    "max_retry_count": int(row.max_retry_count or 3),
                },
            )
        except Exception:  # noqa: BLE001
            pass


def resolve_open_binding(
    session: Session,
    *,
    user_broker_account_id: int,
    symbol: str,
) -> tuple[int | None, int | None]:
    """(binding_id, slot_id) for OPEN STRATEGY_OWNED binding.

    Canonical: operation.strategy_position_binding (FIFO oldest).
    Legacy upbit_strategy_position_binding 은 fallback.
    """

    try:
        row = session.execute(
            text(
                """
                SELECT binding_id, NULL::bigint AS slot_id
                FROM operation.strategy_position_binding
                WHERE user_broker_account_id = :uba
                  AND symbol = :sym
                  AND status = 'OPEN'
                  AND ownership_code = 'STRATEGY_OWNED'
                  AND closed_at IS NULL
                  AND owned_quantity > 0
                ORDER BY binding_id ASC
                LIMIT 1
                """
            ),
            {"uba": int(user_broker_account_id), "sym": str(symbol).upper()},
        ).mappings().first()
        if row and row.get("binding_id"):
            return int(row["binding_id"]), None
    except Exception:  # noqa: BLE001
        pass

    try:
        row = session.execute(
            text(
                """
                SELECT binding_id, slot_id
                FROM operation.upbit_strategy_position_binding
                WHERE user_broker_account_id = :uba
                  AND symbol = :sym
                  AND closed_at IS NULL
                ORDER BY binding_id DESC
                LIMIT 1
                """
            ),
            {"uba": int(user_broker_account_id), "sym": str(symbol).upper()},
        ).mappings().first()
        if not row:
            return None, None
        return (
            int(row["binding_id"]) if row.get("binding_id") else None,
            int(row["slot_id"]) if row.get("slot_id") else None,
        )
    except Exception:  # noqa: BLE001
        return None, None
