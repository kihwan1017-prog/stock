"""FULL_MARKET_PORTFOLIO — slots / Top-K / sequential pending (주문 CREATE 금지)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.operation.upbit_full_market.capital_allocator import (
    AllocationInput,
    allocate_entry_amount,
)
from stock_platform.operation.upbit_full_market.constants import (
    CONFIRM_ALIGN_PORTFOLIO_ENTRY_PIPELINE,
    CONFIRM_DISABLE_PORTFOLIO,
    CONFIRM_ENABLE_PORTFOLIO,
    CONFIRM_RECOVER_STALE_ENTRY_PENDING,
    DEFAULT_CANDIDATE_MAX_AGE_SECONDS,
    DEFAULT_CONSECUTIVE_LOSS_LIMIT,
    DEFAULT_DAILY_LOSS_LIMIT_PCT,
    DEFAULT_ENTRY_COOLDOWN_SECONDS,
    DEFAULT_MAX_POSITIONS,
    DEFAULT_MAX_SYMBOL_EXPOSURE_PCT,
    DEFAULT_MAX_TOTAL_EXPOSURE_PCT,
    DEFAULT_MIN_CASH_RESERVE_PCT,
    DEFAULT_PER_POSITION_TARGET_PCT,
    DEFAULT_PORTFOLIO_CANDIDATE_HOLD_SECONDS,
    DEFAULT_PORTFOLIO_CANDIDATE_SWITCH_MIN_SCORE_DELTA,
    DEFAULT_PORTFOLIO_DAILY_ENTRY_LIMIT,
    DEFAULT_PORTFOLIO_ENTRY_PENDING_TIMEOUT_SECONDS,
    DEFAULT_PORTFOLIO_MAX_PENDING_ENTRIES,
    MODE_FIXED_SYMBOL,
    MODE_FULL_MARKET_PORTFOLIO,
    MODE_FULL_MARKET_SINGLE,
    PORTFOLIO_ENTRY_PAUSED,
    PORTFOLIO_ENTRY_RUNNING,
    SLOT_ACTIVE_SYMBOL_STATUSES,
    SLOT_BLOCKED,
    SLOT_CANDIDATE_HOLD_STATUSES,
    SLOT_COOLDOWN,
    SLOT_EMPTY,
    SLOT_ENTRY_PENDING,
    SLOT_EXIT_PENDING,
    SLOT_OPEN,
    SLOT_RESERVED,
    SLOT_RESERVED_STATUSES,
    SLOT_RUNTIME_SYMBOL_STATUSES,
    SLOT_SELECTED,
    SLOT_WAITING_SIGNAL,
    SLOT_WARMING_UP,
    STATE_IDLE,
    is_full_market_portfolio,
)
from stock_platform.operation.upbit_full_market.entities import (
    UpbitFullMarketAssignmentEntity,
    UpbitLiveCandidateSelectionEntity,
    UpbitPortfolioPolicyEntity,
    UpbitPositionSlotEntity,
    UpbitStrategyPositionBindingEntity,
)
from stock_platform.operation.upbit_full_market.selection_policy import (
    SelectionPolicy,
    select_best_eligible_candidate,
)
from stock_platform.operation.upbit_full_market.service import (
    UpbitFullMarketAssignmentService,
    load_selection_policy_from_settings,
)

logger = structlog.get_logger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


class UpbitPortfolioService:
    """Portfolio policy/slots/Top-K. Broker CREATE 없음."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._assignment = UpbitFullMarketAssignmentService(session)

    def get_or_create_policy(
        self, user_broker_account_id: int
    ) -> UpbitPortfolioPolicyEntity:
        uba_id = int(user_broker_account_id)
        row = self._session.scalar(
            select(UpbitPortfolioPolicyEntity).where(
                UpbitPortfolioPolicyEntity.user_broker_account_id == uba_id
            )
        )
        if row is not None:
            return row
        row = UpbitPortfolioPolicyEntity(
            user_broker_account_id=uba_id,
            enabled=False,
            max_positions=DEFAULT_MAX_POSITIONS,
            per_position_target_pct=DEFAULT_PER_POSITION_TARGET_PCT,
            max_symbol_exposure_pct=DEFAULT_MAX_SYMBOL_EXPOSURE_PCT,
            max_total_exposure_pct=DEFAULT_MAX_TOTAL_EXPOSURE_PCT,
            min_cash_reserve_pct=DEFAULT_MIN_CASH_RESERVE_PCT,
            daily_loss_limit_pct=DEFAULT_DAILY_LOSS_LIMIT_PCT,
            consecutive_loss_limit=DEFAULT_CONSECUTIVE_LOSS_LIMIT,
            allow_averaging_down=False,
            allow_duplicate_symbol=False,
            entry_cooldown_seconds=DEFAULT_ENTRY_COOLDOWN_SECONDS,
            candidate_max_age_seconds=DEFAULT_CANDIDATE_MAX_AGE_SECONDS,
            portfolio_max_pending_entries=DEFAULT_PORTFOLIO_MAX_PENDING_ENTRIES,
            portfolio_daily_entry_limit=DEFAULT_PORTFOLIO_DAILY_ENTRY_LIMIT,
            entry_state=PORTFOLIO_ENTRY_RUNNING,
            consecutive_loss_count=0,
            version=1,
        )
        self._session.add(row)
        self._session.flush()
        return row

    def ensure_slots(
        self,
        user_broker_account_id: int,
        *,
        max_positions: int,
        strategy_id: int | None = None,
        deployment_id: int | None = None,
    ) -> list[UpbitPositionSlotEntity]:
        """max_positions까지 EMPTY slot 확보. OPEN 강제 청산 없이 축소는 ENTRY만 제한."""

        uba_id = int(user_broker_account_id)
        max_n = max(1, min(10, int(max_positions)))
        existing = list(
            self._session.scalars(
                select(UpbitPositionSlotEntity)
                .where(
                    UpbitPositionSlotEntity.user_broker_account_id == uba_id
                )
                .order_by(UpbitPositionSlotEntity.slot_no)
            )
        )
        by_no = {int(s.slot_no): s for s in existing}
        out: list[UpbitPositionSlotEntity] = []
        for no in range(1, max_n + 1):
            if no in by_no:
                out.append(by_no[no])
                continue
            slot = UpbitPositionSlotEntity(
                user_broker_account_id=uba_id,
                strategy_id=strategy_id,
                deployment_id=deployment_id,
                slot_no=no,
                status=SLOT_EMPTY,
                clamp_reasons=[],
                version=1,
            )
            self._session.add(slot)
            out.append(slot)
        self._session.flush()
        return out

    def policy_dict(self, user_broker_account_id: int) -> dict[str, Any]:
        row = self.get_or_create_policy(int(user_broker_account_id))
        return {
            "policy_id": int(row.policy_id),
            "enabled": bool(row.enabled),
            "max_positions": int(row.max_positions),
            "portfolio_capital_limit_krw": row.portfolio_capital_limit_krw,
            "per_position_target_pct": float(row.per_position_target_pct),
            "max_symbol_exposure_pct": float(row.max_symbol_exposure_pct),
            "max_total_exposure_pct": float(row.max_total_exposure_pct),
            "min_cash_reserve_pct": float(row.min_cash_reserve_pct),
            "daily_loss_limit_pct": float(row.daily_loss_limit_pct),
            "consecutive_loss_limit": int(row.consecutive_loss_limit),
            "allow_averaging_down": bool(row.allow_averaging_down),
            "allow_duplicate_symbol": bool(row.allow_duplicate_symbol),
            "entry_cooldown_seconds": int(row.entry_cooldown_seconds),
            "candidate_max_age_seconds": int(row.candidate_max_age_seconds),
            "portfolio_max_pending_entries": int(
                row.portfolio_max_pending_entries
            ),
            "portfolio_daily_entry_limit": int(row.portfolio_daily_entry_limit),
            "entry_state": row.entry_state,
            "consecutive_loss_count": int(row.consecutive_loss_count),
            "version": int(row.version),
        }

    def update_policy(
        self,
        user_broker_account_id: int,
        *,
        patches: dict[str, Any],
        actor: str,
    ) -> dict[str, Any]:
        """설정 갱신. Risk 완화 경고만 반환 — 자동 Enable/주문 없음."""

        row = self.get_or_create_policy(int(user_broker_account_id))
        warnings: list[str] = []
        float_keys = {
            "portfolio_capital_limit_krw",
            "per_position_target_pct",
            "max_symbol_exposure_pct",
            "max_total_exposure_pct",
            "min_cash_reserve_pct",
            "daily_loss_limit_pct",
        }
        int_keys = {
            "max_positions",
            "consecutive_loss_limit",
            "entry_cooldown_seconds",
            "candidate_max_age_seconds",
            "portfolio_max_pending_entries",
            "portfolio_daily_entry_limit",
        }
        bool_keys = {
            "allow_averaging_down",
            "allow_duplicate_symbol",
        }
        for key, value in dict(patches or {}).items():
            if key in float_keys and value is not None:
                old = getattr(row, key)
                new_v = float(value)
                if key in {
                    "max_symbol_exposure_pct",
                    "max_total_exposure_pct",
                    "per_position_target_pct",
                    "daily_loss_limit_pct",
                } and old is not None and new_v > float(old):
                    warnings.append(f"RISK_RELAX_{key.upper()}")
                if key == "min_cash_reserve_pct" and old is not None and new_v < float(old):
                    warnings.append("RISK_RELAX_MIN_CASH_RESERVE")
                setattr(row, key, new_v)
            elif key in int_keys and value is not None:
                old = getattr(row, key)
                new_v = int(value)
                if key == "max_positions":
                    new_v = max(1, min(10, new_v))
                    if old is not None and new_v > int(old):
                        self.ensure_slots(
                            int(user_broker_account_id),
                            max_positions=new_v,
                        )
                    # 축소 시 OPEN 강제 청산 금지 — ENTRY만 제한
                if key in {
                    "portfolio_max_pending_entries",
                    "portfolio_daily_entry_limit",
                    "consecutive_loss_limit",
                } and old is not None and new_v > int(old):
                    warnings.append(f"RISK_RELAX_{key.upper()}")
                setattr(row, key, new_v)
            elif key in bool_keys and value is not None:
                new_b = bool(value)
                if key == "allow_averaging_down" and new_b:
                    warnings.append("AVERAGING_DOWN_ENABLED")
                if key == "allow_duplicate_symbol" and new_b:
                    warnings.append("DUPLICATE_SYMBOL_ENABLED")
                setattr(row, key, new_b)
            elif key == "entry_state" and value is not None:
                setattr(row, key, str(value).upper()[:30])
        row.version = int(row.version or 1) + 1
        self._session.flush()
        logger.info(
            "upbit_portfolio_policy_updated",
            uba_id=int(user_broker_account_id),
            actor=actor,
            warnings=warnings,
        )
        return {
            "ok": True,
            "policy": self.policy_dict(int(user_broker_account_id)),
            "warnings": warnings,
            "orders_created": 0,
        }

    def drawer_summary(self, user_broker_account_id: int) -> dict[str, Any]:
        assignment = self._assignment.status_dict(int(user_broker_account_id))
        policy = self.policy_dict(int(user_broker_account_id))
        slots = self.list_slots(int(user_broker_account_id))
        open_n = sum(
            1 for s in slots if s["status"] in {SLOT_OPEN, SLOT_EXIT_PENDING}
        )
        waiting_n = sum(
            1
            for s in slots
            if s["status"]
            in {
                SLOT_SELECTED,
                SLOT_WARMING_UP,
                SLOT_WAITING_SIGNAL,
            }
        )
        pending_order_n = sum(
            1
            for s in slots
            if s["status"] in {SLOT_RESERVED, SLOT_ENTRY_PENDING}
        )
        reserved = float(self.reserved_amount_total(int(user_broker_account_id)))
        exposure = float(self.strategy_exposure_total(int(user_broker_account_id)))
        capital = float(policy.get("portfolio_capital_limit_krw") or 0) or None
        exposure_pct = (
            (exposure / capital) if capital and capital > 0 else None
        )
        return {
            "mode": assignment.get("mode"),
            "portfolio_enabled": bool(assignment.get("portfolio_enabled")),
            "positions_open": open_n,
            "max_positions": int(policy["max_positions"]),
            "candidates_waiting": waiting_n,
            "pending_orders": pending_order_n,
            "exposure_krw": exposure,
            "exposure_pct": exposure_pct,
            "max_total_exposure_pct": float(policy["max_total_exposure_pct"]),
            "reserved_krw": reserved,
            "min_cash_reserve_pct": float(policy["min_cash_reserve_pct"]),
            "entry_state": policy["entry_state"],
            "slot_badges": [
                {
                    "slot_no": s["slot_no"],
                    "symbol": s["symbol"],
                    "status": s["status"],
                }
                for s in slots
            ],
            "orphans": self.detect_orphans(int(user_broker_account_id)),
        }

    def begin_exit_pending(
        self,
        user_broker_account_id: int,
        *,
        symbol: str,
    ) -> dict[str, Any]:
        """OPEN → EXIT_PENDING atomic. duplicate SELL 방지."""

        from stock_platform.operation.upbit_full_market.constants import (
            SLOT_EXIT_PENDING,
        )

        uba_id = int(user_broker_account_id)
        sym = str(symbol).upper()
        slot = self._session.scalar(
            select(UpbitPositionSlotEntity)
            .where(
                UpbitPositionSlotEntity.user_broker_account_id == uba_id,
                UpbitPositionSlotEntity.symbol == sym,
                UpbitPositionSlotEntity.status == SLOT_OPEN,
            )
            .with_for_update()
        )
        if slot is None:
            return {"ok": False, "reason": "NO_OPEN_SLOT"}
        slot.status = SLOT_EXIT_PENDING
        slot.version = int(slot.version or 1) + 1
        self._session.flush()
        return {"ok": True, "slot_id": int(slot.slot_id), "status": SLOT_EXIT_PENDING}

    def release_reservation(
        self,
        user_broker_account_id: int,
        *,
        slot_id: int | None = None,
        symbol: str | None = None,
    ) -> dict[str, Any]:
        """order fail/cancel 시 reservation 해제."""

        uba_id = int(user_broker_account_id)
        q = select(UpbitPositionSlotEntity).where(
            UpbitPositionSlotEntity.user_broker_account_id == uba_id,
            UpbitPositionSlotEntity.status.in_(
                [SLOT_RESERVED, SLOT_ENTRY_PENDING]
            ),
        )
        if slot_id is not None:
            q = q.where(UpbitPositionSlotEntity.slot_id == int(slot_id))
        if symbol:
            q = q.where(
                UpbitPositionSlotEntity.symbol == str(symbol).upper()
            )
        released = 0
        for slot in list(self._session.scalars(q)):
            slot.status = SLOT_EMPTY
            slot.symbol = None
            slot.candidate_selection_id = None
            slot.scanner_run_id = None
            slot.reserved_amount_krw = None
            slot.allocated_amount_krw = None
            slot.recommended_amount_krw = None
            slot.clamp_reasons = []
            slot.entry_order_id = None
            slot.version = int(slot.version or 1) + 1
            released += 1
        if released:
            self._session.flush()
        return {"ok": True, "released": released}

    def record_completed_trade_pnl(
        self,
        user_broker_account_id: int,
        *,
        pnl_krw: float,
    ) -> dict[str, Any]:
        """strategy-owned 종료 후 consecutive loss 갱신."""

        policy = self.get_or_create_policy(int(user_broker_account_id))
        if float(pnl_krw) < 0:
            policy.consecutive_loss_count = int(
                policy.consecutive_loss_count or 0
            ) + 1
            if policy.consecutive_loss_count >= int(
                policy.consecutive_loss_limit
            ):
                policy.entry_state = PORTFOLIO_ENTRY_PAUSED
        else:
            policy.consecutive_loss_count = 0
        policy.version = int(policy.version or 1) + 1
        self._session.flush()
        return {
            "ok": True,
            "consecutive_loss_count": int(policy.consecutive_loss_count),
            "entry_state": policy.entry_state,
        }

    def list_slots(self, user_broker_account_id: int) -> list[dict[str, Any]]:
        rows = list(
            self._session.scalars(
                select(UpbitPositionSlotEntity)
                .where(
                    UpbitPositionSlotEntity.user_broker_account_id
                    == int(user_broker_account_id)
                )
                .order_by(UpbitPositionSlotEntity.slot_no)
            )
        )
        return [
            {
                "slot_id": int(s.slot_id),
                "slot_no": int(s.slot_no),
                "status": s.status,
                "symbol": s.symbol,
                "recommended_amount_krw": s.recommended_amount_krw,
                "allocated_amount_krw": s.allocated_amount_krw,
                "reserved_amount_krw": s.reserved_amount_krw,
                "clamp_reasons": s.clamp_reasons,
                "candidate_selection_id": s.candidate_selection_id,
                "scanner_run_id": s.scanner_run_id,
                "entry_order_id": s.entry_order_id,
                "position_binding_id": s.position_binding_id,
                "cooldown_until": (
                    s.cooldown_until.isoformat() if s.cooldown_until else None
                ),
                "version": int(s.version),
            }
            for s in rows
        ]

    def active_symbols(self, user_broker_account_id: int) -> list[str]:
        rows = list(
            self._session.scalars(
                select(UpbitPositionSlotEntity).where(
                    UpbitPositionSlotEntity.user_broker_account_id
                    == int(user_broker_account_id),
                    UpbitPositionSlotEntity.status.in_(
                        list(SLOT_ACTIVE_SYMBOL_STATUSES)
                    ),
                )
            )
        )
        out: list[str] = []
        for s in rows:
            sym = str(s.symbol or "").upper()
            if sym and sym not in out:
                out.append(sym)
        return out

    def enable_portfolio(
        self,
        user_broker_account_id: int,
        *,
        confirmation_text: str,
        actor: str,
        strategy_id: int | None = None,
        deployment_id: int | None = None,
        template_symbol: str | None = None,
        portfolio_capital_limit_krw: float | None = None,
        max_positions: int = DEFAULT_MAX_POSITIONS,
    ) -> dict[str, Any]:
        if str(confirmation_text or "").strip() != CONFIRM_ENABLE_PORTFOLIO:
            return {
                "ok": False,
                "error": "CONFIRMATION_MISMATCH",
                "expected": CONFIRM_ENABLE_PORTFOLIO,
            }
        from stock_platform.trading.account_models import UserBrokerAccount

        uba = self._session.get(UserBrokerAccount, int(user_broker_account_id))
        if uba is None:
            return {"ok": False, "error": "UBA_NOT_FOUND"}
        if str(uba.broker_code or "").upper() != "UPBIT":
            return {"ok": False, "error": "BROKER_NOT_UPBIT"}

        assignment = self._assignment.get_or_create(
            int(user_broker_account_id),
            strategy_id=strategy_id,
            deployment_id=deployment_id,
            template_symbol=template_symbol,
        )
        # PORTFOLIO Enable — 자동 주문 없음
        assignment.mode = MODE_FULL_MARKET_PORTFOLIO
        assignment.state = "IDLE"
        if strategy_id is not None:
            assignment.strategy_id = int(strategy_id)
        if deployment_id is not None:
            assignment.deployment_id = int(deployment_id)
        if template_symbol:
            assignment.template_symbol = str(template_symbol).upper()

        policy = self.get_or_create_policy(int(user_broker_account_id))
        policy.enabled = True
        policy.max_positions = max(1, min(10, int(max_positions)))
        if portfolio_capital_limit_krw is not None:
            policy.portfolio_capital_limit_krw = float(
                portfolio_capital_limit_krw
            )
        policy.entry_state = PORTFOLIO_ENTRY_RUNNING
        policy.version = int(policy.version or 1) + 1
        self.ensure_slots(
            int(user_broker_account_id),
            max_positions=int(policy.max_positions),
            strategy_id=assignment.strategy_id,
            deployment_id=assignment.deployment_id,
        )
        self._session.flush()
        logger.info(
            "upbit_portfolio_enabled",
            uba_id=int(user_broker_account_id),
            actor=actor,
        )
        return {
            "ok": True,
            "mode": MODE_FULL_MARKET_PORTFOLIO,
            "policy": self.policy_dict(int(user_broker_account_id)),
            "slots": self.list_slots(int(user_broker_account_id)),
            "orders_created": 0,
        }

    def disable_portfolio(
        self,
        user_broker_account_id: int,
        *,
        confirmation_text: str,
        actor: str,
        fallback_mode: str = MODE_FULL_MARKET_SINGLE,
    ) -> dict[str, Any]:
        if str(confirmation_text or "").strip() != CONFIRM_DISABLE_PORTFOLIO:
            return {
                "ok": False,
                "error": "CONFIRMATION_MISMATCH",
                "expected": CONFIRM_DISABLE_PORTFOLIO,
            }
        assignment = self._assignment.get_or_create(int(user_broker_account_id))
        # OPEN slot 강제 청산 금지 — mode만 SINGLE/FIXED로
        mode = str(fallback_mode or MODE_FULL_MARKET_SINGLE).upper()
        if mode not in {MODE_FIXED_SYMBOL, MODE_FULL_MARKET_SINGLE}:
            mode = MODE_FULL_MARKET_SINGLE
        assignment.mode = mode
        if mode == MODE_FIXED_SYMBOL and assignment.template_symbol:
            assignment.current_symbol = assignment.template_symbol
        policy = self.get_or_create_policy(int(user_broker_account_id))
        policy.enabled = False
        policy.version = int(policy.version or 1) + 1
        self._session.flush()
        logger.info(
            "upbit_portfolio_disabled",
            uba_id=int(user_broker_account_id),
            actor=actor,
            mode=mode,
        )
        return {
            "ok": True,
            "mode": mode,
            "policy": self.policy_dict(int(user_broker_account_id)),
            "slots": self.list_slots(int(user_broker_account_id)),
        }

    def pending_entry_count(self, user_broker_account_id: int) -> int:
        rows = list(
            self._session.scalars(
                select(UpbitPositionSlotEntity).where(
                    UpbitPositionSlotEntity.user_broker_account_id
                    == int(user_broker_account_id),
                    UpbitPositionSlotEntity.status.in_(
                        [SLOT_RESERVED, SLOT_ENTRY_PENDING]
                    ),
                )
            )
        )
        return len(rows)

    def open_slot_count(self, user_broker_account_id: int) -> int:
        rows = list(
            self._session.scalars(
                select(UpbitPositionSlotEntity).where(
                    UpbitPositionSlotEntity.user_broker_account_id
                    == int(user_broker_account_id),
                    UpbitPositionSlotEntity.status.in_(
                        [SLOT_OPEN, SLOT_EXIT_PENDING]
                    ),
                )
            )
        )
        return len(rows)

    def reserved_amount_total(self, user_broker_account_id: int) -> Decimal:
        rows = list(
            self._session.scalars(
                select(UpbitPositionSlotEntity).where(
                    UpbitPositionSlotEntity.user_broker_account_id
                    == int(user_broker_account_id),
                    UpbitPositionSlotEntity.status.in_(
                        [SLOT_RESERVED, SLOT_ENTRY_PENDING]
                    ),
                )
            )
        )
        total = Decimal("0")
        for s in rows:
            total += Decimal(str(s.reserved_amount_krw or 0))
        return total

    def strategy_exposure_total(self, user_broker_account_id: int) -> Decimal:
        """strategy-owned OPEN binding 평가액 근사 — allocated 합."""

        rows = list(
            self._session.scalars(
                select(UpbitPositionSlotEntity).where(
                    UpbitPositionSlotEntity.user_broker_account_id
                    == int(user_broker_account_id),
                    UpbitPositionSlotEntity.status.in_(
                        [SLOT_OPEN, SLOT_EXIT_PENDING]
                    ),
                )
            )
        )
        total = Decimal("0")
        for s in rows:
            total += Decimal(
                str(s.allocated_amount_krw or s.reserved_amount_krw or 0)
            )
        return total

    def tick_cooldown_slots(self, user_broker_account_id: int) -> int:
        now = _now()
        released = 0
        rows = list(
            self._session.scalars(
                select(UpbitPositionSlotEntity).where(
                    UpbitPositionSlotEntity.user_broker_account_id
                    == int(user_broker_account_id),
                    UpbitPositionSlotEntity.status == SLOT_COOLDOWN,
                )
            )
        )
        for s in rows:
            if s.cooldown_until is None or s.cooldown_until <= now:
                s.status = SLOT_EMPTY
                s.symbol = None
                s.candidate_selection_id = None
                s.scanner_run_id = None
                s.reserved_amount_krw = None
                s.allocated_amount_krw = None
                s.recommended_amount_krw = None
                s.entry_order_id = None
                s.position_binding_id = None
                s.clamp_reasons = []
                s.version = int(s.version or 1) + 1
                released += 1
        if released:
            self._session.flush()
        return released

    def consume_top_k(
        self,
        user_broker_account_id: int,
        *,
        candidates: list[dict[str, Any]],
        scanner_run_id: str,
        scanner_completed_at: datetime | None = None,
        available_krw: Decimal | None = None,
        account_max_order_amount: Decimal | None = None,
        activation_max_order_amount: Decimal | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Top-K → 빈 slot 순차 RESERVE (pending_entries=1). 주문 없음."""

        uba_id = int(user_broker_account_id)
        assignment = self._assignment.get_or_create(uba_id)
        out: dict[str, Any] = {
            "ok": False,
            "dry_run": bool(dry_run),
            "uba_id": uba_id,
            "mode": assignment.mode,
            "orders_created": 0,
            "reserved": [],
            "skipped": [],
            "reason": None,
        }
        if not is_full_market_portfolio(assignment.mode):
            out["reason"] = "MODE_NOT_PORTFOLIO"
            return out

        policy = self.get_or_create_policy(uba_id)
        if not policy.enabled:
            out["reason"] = "POLICY_DISABLED"
            return out
        if str(policy.entry_state or "") == PORTFOLIO_ENTRY_PAUSED:
            out["reason"] = "ENTRY_PAUSED"
            return out

        self.tick_cooldown_slots(uba_id)
        self.ensure_slots(
            uba_id,
            max_positions=int(policy.max_positions),
            strategy_id=assignment.strategy_id,
            deployment_id=assignment.deployment_id,
        )
        # ENTRY_PENDING(실제 주문 단계) 고착만 timeout 복구 — WAITING_SIGNAL 제외
        stale_rec = self.recover_stale_entry_pending_without_order(uba_id)
        if int(stale_rec.get("released") or 0) > 0:
            out["stale_entry_recovered"] = stale_rec

        hold = self._candidate_hold_block(uba_id, candidates=candidates)
        if hold.get("blocked"):
            out["reason"] = str(hold.get("reason") or "CANDIDATE_HOLD")
            out["hold"] = hold
            return out

        if self.pending_entry_count(uba_id) >= int(
            policy.portfolio_max_pending_entries
        ):
            out["reason"] = "PENDING_ENTRY_LIMIT"
            return out

        # portfolio_daily_entry_limit — 계좌 daily_order_limit과 분리 (무시 금지)
        day_start = _now().replace(hour=0, minute=0, second=0, microsecond=0)
        today_entries = list(
            self._session.scalars(
                select(UpbitLiveCandidateSelectionEntity).where(
                    UpbitLiveCandidateSelectionEntity.user_broker_account_id
                    == uba_id,
                    UpbitLiveCandidateSelectionEntity.selected_at >= day_start,
                    UpbitLiveCandidateSelectionEntity.selection_reason.like(
                        "PORTFOLIO_SLOT_%"
                    ),
                )
            )
        )
        if len(today_entries) >= int(policy.portfolio_daily_entry_limit):
            out["reason"] = "PORTFOLIO_DAILY_ENTRY_LIMIT"
            return out

        empty = list(
            self._session.scalars(
                select(UpbitPositionSlotEntity)
                .where(
                    UpbitPositionSlotEntity.user_broker_account_id == uba_id,
                    UpbitPositionSlotEntity.status == SLOT_EMPTY,
                )
                .order_by(UpbitPositionSlotEntity.slot_no)
                .with_for_update()
            )
        )
        # max_positions보다 slot_no가 큰 EMPTY는 무시 (축소 정책)
        empty = [s for s in empty if int(s.slot_no) <= int(policy.max_positions)]
        if not empty:
            out["reason"] = "NO_EMPTY_SLOT"
            return out

        active_syms = set(self.active_symbols(uba_id))
        sel_policy = load_selection_policy_from_settings(assignment=assignment)
        sel_policy = SelectionPolicy(
            min_score=sel_policy.min_score,
            min_liquidity_krw=sel_policy.min_liquidity_krw,
            min_confidence=sel_policy.min_confidence,
            max_candidate_age_seconds=float(policy.candidate_max_age_seconds),
            ai_live_gate_mode=sel_policy.ai_live_gate_mode,
            excluded_symbols=sel_policy.excluded_symbols | frozenset(active_syms),
            allow_reduce_as_entry=sel_policy.allow_reduce_as_entry,
        )

        # 순차: pending max=1 → 첫 빈 slot 1개만
        slot = empty[0]
        remaining = list(candidates)
        chosen = None
        skip_all: list[dict[str, Any]] = []
        while remaining:
            decision = select_best_eligible_candidate(
                remaining,
                sel_policy,
                scanner_run_id=scanner_run_id,
                now=_now(),
                scanner_completed_at=scanner_completed_at,
            )
            skip_all.extend(decision.skip_trace)
            if decision.selected is None:
                break
            cand = decision.selected
            if (
                not policy.allow_duplicate_symbol
                and cand.symbol in active_syms
            ):
                skip_all.append(
                    {
                        "symbol": cand.symbol,
                        "ok": False,
                        "reason": "DUPLICATE_SYMBOL",
                    }
                )
                remaining = [
                    c
                    for c in remaining
                    if str(
                        c.get("symbol")
                        if isinstance(c, dict)
                        else getattr(c, "symbol", "")
                    ).upper()
                    != cand.symbol
                ]
                continue
            # preexisting manual holding skip (SINGLE과 동일 정책)
            if self._assignment._has_preexisting_holding(uba_id, cand.symbol):
                skip_all.append(
                    {
                        "symbol": cand.symbol,
                        "ok": False,
                        "reason": "PREEXISTING_HOLDING",
                    }
                )
                remaining = [
                    c
                    for c in remaining
                    if str(
                        c.get("symbol")
                        if isinstance(c, dict)
                        else getattr(c, "symbol", "")
                    ).upper()
                    != cand.symbol
                ]
                continue
            chosen = cand
            break

        out["skipped"] = skip_all
        if chosen is None:
            out["reason"] = "NO_ELIGIBLE_CANDIDATE"
            return out

        capital = Decimal(
            str(
                policy.portfolio_capital_limit_krw
                or (available_krw or 0)
                or 0
            )
        )
        if capital <= 0 and available_krw is not None:
            # 명시 capital 없으면 available의 40%만 운용한도로 보수 적용
            capital = Decimal(str(available_krw)) * Decimal("0.40")

        max_order = account_max_order_amount or Decimal("10000")
        alloc = allocate_entry_amount(
            AllocationInput(
                portfolio_capital_limit_krw=capital,
                available_krw=Decimal(str(available_krw or capital)),
                min_cash_reserve_pct=float(policy.min_cash_reserve_pct),
                per_position_target_pct=float(policy.per_position_target_pct),
                max_symbol_exposure_pct=float(policy.max_symbol_exposure_pct),
                max_total_exposure_pct=float(policy.max_total_exposure_pct),
                current_strategy_exposure_krw=self.strategy_exposure_total(
                    uba_id
                ),
                pending_reserved_krw=self.reserved_amount_total(uba_id),
                current_symbol_exposure_krw=Decimal("0"),
                account_max_order_amount=max_order,
                activation_max_order_amount=activation_max_order_amount,
                scanner_score=chosen.score,
                ai_confidence=chosen.confidence,
                volatility=(chosen.technical_metrics or {}).get("volatility"),
            )
        )
        if alloc.skipped:
            out["reason"] = alloc.skip_reason
            out["allocation"] = {
                "recommended": str(alloc.recommended_amount_krw),
                "approved": str(alloc.approved_amount_krw),
                "clamp_reasons": alloc.clamp_reasons,
            }
            return out

        payload = {
            "slot_no": int(slot.slot_no),
            "symbol": chosen.symbol,
            "rank": chosen.rank,
            "recommendation": chosen.recommendation,
            "recommended_amount_krw": float(alloc.recommended_amount_krw),
            "approved_amount_krw": float(alloc.approved_amount_krw),
            "clamp_reasons": list(alloc.clamp_reasons),
            "reserved_amount_krw": 0.0,
        }
        out["allocation_preview"] = payload
        out["reserved"] = []

        if dry_run:
            out["ok"] = True
            out["reason"] = "DRY_WAITING_SIGNAL"
            return out

        # persist selection — 자금 reservation 없음 (BUY signal 직전까지)
        sel = UpbitLiveCandidateSelectionEntity(
            user_broker_account_id=uba_id,
            strategy_id=assignment.strategy_id,
            deployment_id=assignment.deployment_id,
            scanner_run_id=scanner_run_id,
            symbol=chosen.symbol,
            rank=chosen.rank,
            score=chosen.score,
            market_data_timestamp=chosen.market_data_timestamp or _now(),
            liquidity=chosen.liquidity,
            technical_metrics=dict(chosen.technical_metrics or {}),
            ai_analysis_id=chosen.ai_analysis_id,
            ai_recommendation=chosen.recommendation,
            confidence=chosen.confidence,
            selected_at=_now(),
            selection_reason=f"PORTFOLIO_SLOT_{slot.slot_no}",
            status="SELECTED",
            skip_trace=list(skip_all),
        )
        self._session.add(sel)
        self._session.flush()

        slot.status = SLOT_SELECTED
        slot.symbol = chosen.symbol
        slot.candidate_selection_id = int(sel.selection_id)
        slot.scanner_run_id = scanner_run_id
        slot.ai_analysis_id = chosen.ai_analysis_id
        # BUY 전: recommended만 기록, reserved/allocated=0
        slot.recommended_amount_krw = None
        slot.allocated_amount_krw = None
        slot.reserved_amount_krw = None
        slot.clamp_reasons = []
        slot.entry_order_id = None
        slot.version = int(slot.version or 1) + 1
        assignment.last_scanner_run_id = scanner_run_id
        assignment.current_symbol = chosen.symbol
        self._session.flush()

        runtime_sync: dict[str, Any] | None = None
        if not dry_run:
            try:
                from stock_platform.operation.upbit_full_market.portfolio_runtime_sync import (
                    sync_portfolio_runtime_symbols,
                )

                runtime_sync = sync_portfolio_runtime_symbols(
                    self._session,
                    user_broker_account_id=uba_id,
                    ensure_quote_feed=True,
                )
            except Exception as exc:  # noqa: BLE001
                runtime_sync = {
                    "ok": False,
                    "reason": type(exc).__name__,
                }
            if runtime_sync and not bool(runtime_sync.get("ok")):
                # sync 실패 시 SELECTED/BLOCKED 유지 — ENTRY_PENDING/reserve 금지
                slot.status = SLOT_BLOCKED
                slot.version = int(slot.version or 1) + 1
                self._session.flush()
                out["ok"] = False
                out["reason"] = "RUNTIME_SYNC_FAILED"
                out["runtime_sync"] = runtime_sync
                out["selection_id"] = int(sel.selection_id)
                out["slot_id"] = int(slot.slot_id)
                out["slots"] = self.list_slots(uba_id)
                return out
            # sync OK → WAITING_SIGNAL (warmup은 consumer 내부; 외부 상태는 신호 대기)
            slot.status = SLOT_WAITING_SIGNAL
            slot.version = int(slot.version or 1) + 1
            self._session.flush()
        else:
            slot.status = SLOT_WAITING_SIGNAL

        out["ok"] = True
        out["reason"] = "SLOT_WAITING_SIGNAL"
        out["selection_id"] = int(sel.selection_id)
        out["slot_id"] = int(slot.slot_id)
        out["runtime_sync"] = runtime_sync
        out["reserved"] = []
        out["slots"] = self.list_slots(uba_id)
        return out

    def preview_allocation(
        self,
        user_broker_account_id: int,
        *,
        symbol: str = "KRW-ETH",
        scanner_score: float = 80.0,
        ai_confidence: float = 0.85,
        volatility: str = "MEDIUM",
        available_krw: float | None = None,
        account_max_order_amount: float | None = None,
    ) -> dict[str, Any]:
        policy = self.get_or_create_policy(int(user_broker_account_id))
        avail = Decimal(str(available_krw if available_krw is not None else 500000))
        capital = Decimal(
            str(policy.portfolio_capital_limit_krw or float(avail) * 0.4)
        )
        max_order = Decimal(
            str(account_max_order_amount if account_max_order_amount is not None else 10000)
        )
        alloc = allocate_entry_amount(
            AllocationInput(
                portfolio_capital_limit_krw=capital,
                available_krw=avail,
                min_cash_reserve_pct=float(policy.min_cash_reserve_pct),
                per_position_target_pct=float(policy.per_position_target_pct),
                max_symbol_exposure_pct=float(policy.max_symbol_exposure_pct),
                max_total_exposure_pct=float(policy.max_total_exposure_pct),
                current_strategy_exposure_krw=self.strategy_exposure_total(
                    int(user_broker_account_id)
                ),
                pending_reserved_krw=self.reserved_amount_total(
                    int(user_broker_account_id)
                ),
                current_symbol_exposure_krw=Decimal("0"),
                account_max_order_amount=max_order,
                scanner_score=scanner_score,
                ai_confidence=ai_confidence,
                volatility=volatility,
            )
        )
        return {
            "symbol": symbol,
            "portfolio_capital_limit_krw": float(capital),
            "available_krw": float(avail),
            "recommended_amount_krw": float(alloc.recommended_amount_krw),
            "approved_amount_krw": float(alloc.approved_amount_krw),
            "skipped": alloc.skipped,
            "skip_reason": alloc.skip_reason,
            "clamp_reasons": alloc.clamp_reasons,
            "quality_multiplier": alloc.quality_multiplier,
            "detail": alloc.detail,
            "orders_created": 0,
        }

    def detect_orphans(self, user_broker_account_id: int) -> list[dict[str, Any]]:
        """임의 삭제 금지 — 탐지만."""

        uba_id = int(user_broker_account_id)
        issues: list[dict[str, Any]] = []
        slots = list(
            self._session.scalars(
                select(UpbitPositionSlotEntity).where(
                    UpbitPositionSlotEntity.user_broker_account_id == uba_id
                )
            )
        )
        bindings = list(
            self._session.scalars(
                select(UpbitStrategyPositionBindingEntity).where(
                    UpbitStrategyPositionBindingEntity.user_broker_account_id
                    == uba_id,
                    UpbitStrategyPositionBindingEntity.status == "OPEN",
                )
            )
        )
        binding_by_slot = {
            int(b.slot_id): b for b in bindings if b.slot_id is not None
        }
        for s in slots:
            if s.status == SLOT_OPEN and s.position_binding_id is None:
                if int(s.slot_id) not in binding_by_slot:
                    issues.append(
                        {
                            "code": "SLOT_OPEN_WITHOUT_BINDING",
                            "slot_id": int(s.slot_id),
                            "symbol": s.symbol,
                        }
                    )
            if s.status == SLOT_ENTRY_PENDING and s.entry_order_id is None:
                issues.append(
                    {
                        "code": "ENTRY_PENDING_WITHOUT_ORDER",
                        "slot_id": int(s.slot_id),
                        "symbol": s.symbol,
                        "updated_at": (
                            s.updated_at.isoformat() if s.updated_at else None
                        ),
                    }
                )
            if (
                s.status
                in {
                    SLOT_SELECTED,
                    SLOT_WARMING_UP,
                    SLOT_WAITING_SIGNAL,
                }
                and float(s.reserved_amount_krw or 0) > 0
            ):
                issues.append(
                    {
                        "code": "WAITING_WITH_RESERVATION",
                        "slot_id": int(s.slot_id),
                        "symbol": s.symbol,
                        "reserved_amount_krw": s.reserved_amount_krw,
                    }
                )
        for b in bindings:
            if b.slot_id is None:
                issues.append(
                    {
                        "code": "BINDING_WITHOUT_SLOT",
                        "binding_id": int(b.binding_id),
                        "symbol": b.symbol,
                    }
                )
        return issues

    def _candidate_hold_block(
        self,
        user_broker_account_id: int,
        *,
        candidates: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """WAITING_SIGNAL 등 hold 중이면 매 scanner 주기 교체 금지."""

        from stock_platform.common.settings import get_settings

        uba_id = int(user_broker_account_id)
        settings = get_settings()
        hold_sec = float(
            getattr(
                settings,
                "upbit_portfolio_candidate_hold_seconds",
                DEFAULT_PORTFOLIO_CANDIDATE_HOLD_SECONDS,
            )
            or DEFAULT_PORTFOLIO_CANDIDATE_HOLD_SECONDS
        )
        min_delta = float(
            getattr(
                settings,
                "upbit_portfolio_candidate_switch_min_score_delta",
                DEFAULT_PORTFOLIO_CANDIDATE_SWITCH_MIN_SCORE_DELTA,
            )
            or DEFAULT_PORTFOLIO_CANDIDATE_SWITCH_MIN_SCORE_DELTA
        )
        held = list(
            self._session.scalars(
                select(UpbitPositionSlotEntity).where(
                    UpbitPositionSlotEntity.user_broker_account_id == uba_id,
                    UpbitPositionSlotEntity.status.in_(
                        list(SLOT_CANDIDATE_HOLD_STATUSES)
                    ),
                )
            )
        )
        if not held:
            return {"blocked": False}
        now = _now()
        best_new = 0.0
        for raw in candidates or []:
            if isinstance(raw, dict):
                try:
                    best_new = max(best_new, float(raw.get("score") or 0))
                except (TypeError, ValueError):
                    continue
        for slot in held:
            updated = slot.updated_at or slot.created_at or now
            if updated.tzinfo is None:
                updated = updated.replace(tzinfo=timezone.utc)
            age = max(0.0, (now - updated.astimezone(timezone.utc)).total_seconds())
            cur_score = 0.0
            if slot.candidate_selection_id is not None:
                sel = self._session.get(
                    UpbitLiveCandidateSelectionEntity,
                    int(slot.candidate_selection_id),
                )
                if sel is not None:
                    try:
                        cur_score = float(sel.score or 0)
                    except (TypeError, ValueError):
                        cur_score = 0.0
            if age < hold_sec and (best_new - cur_score) < min_delta:
                return {
                    "blocked": True,
                    "reason": "CANDIDATE_HOLD",
                    "slot_id": int(slot.slot_id),
                    "symbol": slot.symbol,
                    "age_seconds": age,
                    "hold_seconds": hold_sec,
                    "current_score": cur_score,
                    "best_new_score": best_new,
                    "min_score_delta": min_delta,
                }
        return {"blocked": False}

    def begin_entry_from_signal(
        self,
        user_broker_account_id: int,
        *,
        symbol: str,
        available_krw: Decimal | None = None,
        account_max_order_amount: Decimal | None = None,
        activation_max_order_amount: Decimal | None = None,
        scanner_score: float | None = None,
        ai_confidence: float | None = None,
    ) -> dict[str, Any]:
        """WAITING_SIGNAL → capital reserve → ENTRY_PENDING (BUY signal 직후)."""

        uba_id = int(user_broker_account_id)
        sym = str(symbol or "").upper()
        if not sym:
            return {"ok": False, "reason": "SYMBOL_REQUIRED"}
        if self.pending_entry_count(uba_id) >= 1:
            # max_pending_entries=1 — 다른 심볼이 이미 주문 단계면 대기
            existing = self._session.scalar(
                select(UpbitPositionSlotEntity).where(
                    UpbitPositionSlotEntity.user_broker_account_id == uba_id,
                    UpbitPositionSlotEntity.symbol == sym,
                    UpbitPositionSlotEntity.status == SLOT_ENTRY_PENDING,
                )
            )
            if existing is not None:
                return {
                    "ok": True,
                    "already": True,
                    "slot_id": int(existing.slot_id),
                    "status": SLOT_ENTRY_PENDING,
                    "reserved_amount_krw": existing.reserved_amount_krw,
                }
            return {"ok": False, "reason": "PENDING_ENTRY_LIMIT"}

        slot = self._session.scalar(
            select(UpbitPositionSlotEntity)
            .where(
                UpbitPositionSlotEntity.user_broker_account_id == uba_id,
                UpbitPositionSlotEntity.symbol == sym,
                UpbitPositionSlotEntity.status == SLOT_WAITING_SIGNAL,
            )
            .with_for_update()
        )
        if slot is None:
            return {"ok": False, "reason": "NO_WAITING_SIGNAL_SLOT"}

        policy = self.get_or_create_policy(uba_id)
        if not policy.enabled:
            return {"ok": False, "reason": "POLICY_DISABLED"}
        if str(policy.entry_state or "") == PORTFOLIO_ENTRY_PAUSED:
            return {"ok": False, "reason": "ENTRY_PAUSED"}

        score = float(scanner_score or 80.0)
        conf = float(ai_confidence or 0.8)
        if slot.candidate_selection_id is not None:
            sel = self._session.get(
                UpbitLiveCandidateSelectionEntity,
                int(slot.candidate_selection_id),
            )
            if sel is not None:
                score = float(sel.score or score)
                conf = float(sel.confidence or conf)

        capital = Decimal(
            str(policy.portfolio_capital_limit_krw or available_krw or 0)
        )
        if capital <= 0 and available_krw is not None:
            capital = Decimal(str(available_krw)) * Decimal("0.40")
        max_order = account_max_order_amount or Decimal("10000")
        alloc = allocate_entry_amount(
            AllocationInput(
                portfolio_capital_limit_krw=capital,
                available_krw=Decimal(str(available_krw or capital)),
                min_cash_reserve_pct=float(policy.min_cash_reserve_pct),
                per_position_target_pct=float(policy.per_position_target_pct),
                max_symbol_exposure_pct=float(policy.max_symbol_exposure_pct),
                max_total_exposure_pct=float(policy.max_total_exposure_pct),
                current_strategy_exposure_krw=self.strategy_exposure_total(
                    uba_id
                ),
                pending_reserved_krw=self.reserved_amount_total(uba_id),
                current_symbol_exposure_krw=Decimal("0"),
                account_max_order_amount=max_order,
                activation_max_order_amount=activation_max_order_amount,
                scanner_score=score,
                ai_confidence=conf,
                volatility="MEDIUM",
            )
        )
        if alloc.skipped or float(alloc.approved_amount_krw) <= 0:
            return {
                "ok": False,
                "reason": alloc.skip_reason or "ALLOCATION_SKIPPED",
                "allocation": {
                    "recommended": str(alloc.recommended_amount_krw),
                    "approved": str(alloc.approved_amount_krw),
                    "clamp_reasons": alloc.clamp_reasons,
                },
            }

        slot.status = SLOT_ENTRY_PENDING
        slot.recommended_amount_krw = float(alloc.recommended_amount_krw)
        slot.allocated_amount_krw = float(alloc.approved_amount_krw)
        slot.reserved_amount_krw = float(alloc.approved_amount_krw)
        slot.clamp_reasons = list(alloc.clamp_reasons)
        slot.version = int(slot.version or 1) + 1
        self._session.flush()
        return {
            "ok": True,
            "slot_id": int(slot.slot_id),
            "status": SLOT_ENTRY_PENDING,
            "reserved_amount_krw": float(alloc.approved_amount_krw),
            "approved_amount_krw": float(alloc.approved_amount_krw),
            "clamp_reasons": list(alloc.clamp_reasons),
            "orders_created": 0,
        }

    def align_legacy_reserved_entry_pending(
        self,
        user_broker_account_id: int,
        *,
        confirmation_text: str,
        actor: str = "system",
    ) -> dict[str, Any]:
        """구 semantics(ENTRY_PENDING+reserve, 주문없음) → WAITING_SIGNAL+reserve0."""

        if str(confirmation_text or "").strip() != CONFIRM_ALIGN_PORTFOLIO_ENTRY_PIPELINE:
            return {
                "ok": False,
                "reason": "CONFIRMATION_MISMATCH",
                "expected": CONFIRM_ALIGN_PORTFOLIO_ENTRY_PIPELINE,
            }
        uba_id = int(user_broker_account_id)
        slots = list(
            self._session.scalars(
                select(UpbitPositionSlotEntity)
                .where(
                    UpbitPositionSlotEntity.user_broker_account_id == uba_id,
                    UpbitPositionSlotEntity.status == SLOT_ENTRY_PENDING,
                    UpbitPositionSlotEntity.entry_order_id.is_(None),
                )
                .with_for_update()
            )
        )
        aligned: list[dict[str, Any]] = []
        for slot in slots:
            if self._has_local_open_order(
                uba_id, symbol=str(slot.symbol or "")
            ) or self._has_pending_outbox_for_symbol(
                uba_id, symbol=str(slot.symbol or "")
            ):
                aligned.append(
                    {
                        "slot_id": int(slot.slot_id),
                        "skipped": True,
                        "reason": "ORDER_EVIDENCE",
                    }
                )
                continue
            prior = {
                "status": slot.status,
                "reserved_amount_krw": slot.reserved_amount_krw,
                "allocated_amount_krw": slot.allocated_amount_krw,
            }
            slot.status = SLOT_WAITING_SIGNAL
            slot.reserved_amount_krw = None
            slot.allocated_amount_krw = None
            slot.clamp_reasons = []
            slot.version = int(slot.version or 1) + 1
            aligned.append(
                {
                    "slot_id": int(slot.slot_id),
                    "symbol": slot.symbol,
                    "from": prior,
                    "to": SLOT_WAITING_SIGNAL,
                }
            )
        if aligned:
            self._session.flush()
        sync = None
        try:
            from stock_platform.operation.upbit_full_market.portfolio_runtime_sync import (
                sync_portfolio_runtime_symbols,
            )

            sync = sync_portfolio_runtime_symbols(
                self._session,
                user_broker_account_id=uba_id,
                ensure_quote_feed=True,
            )
        except Exception as exc:  # noqa: BLE001
            sync = {"ok": False, "reason": type(exc).__name__}
        logger.info(
            "portfolio_legacy_entry_pending_aligned",
            uba_id=uba_id,
            actor=str(actor)[:80],
            aligned=len(aligned),
        )
        return {
            "ok": True,
            "aligned": aligned,
            "runtime_sync": sync,
            "orders_created": 0,
        }

    def recover_stale_entry_pending_without_order(
        self,
        user_broker_account_id: int,
        *,
        timeout_seconds: float | None = None,
        confirmation_text: str | None = None,
        broker_open_symbols: set[str] | frozenset[str] | None = None,
        actor: str = "system",
    ) -> dict[str, Any]:
        """ENTRY_PENDING + entry_order_id null 이고 주문 흔적 없으면 slot release.

        - DB `updated_at` 기준 timeout (process-memory timer 금지)
        - local open order / pending outbox / broker open 존재 시 release 금지
        - history/selection row 삭제 금지 (slot만 EMPTY로 되돌림)
        """

        from stock_platform.common.settings import get_settings

        uba_id = int(user_broker_account_id)
        settings = get_settings()
        timeout = float(
            timeout_seconds
            if timeout_seconds is not None
            else getattr(
                settings,
                "upbit_portfolio_entry_pending_timeout_seconds",
                120.0,
            )
            or 120.0
        )
        if confirmation_text is not None:
            if (
                str(confirmation_text).strip()
                != CONFIRM_RECOVER_STALE_ENTRY_PENDING
            ):
                return {
                    "ok": False,
                    "reason": "CONFIRMATION_MISMATCH",
                    "expected": CONFIRM_RECOVER_STALE_ENTRY_PENDING,
                    "released": 0,
                }

        now = _now()
        slots = list(
            self._session.scalars(
                select(UpbitPositionSlotEntity)
                .where(
                    UpbitPositionSlotEntity.user_broker_account_id == uba_id,
                    UpbitPositionSlotEntity.status == SLOT_ENTRY_PENDING,
                    UpbitPositionSlotEntity.entry_order_id.is_(None),
                )
                .with_for_update()
            )
        )
        inspected: list[dict[str, Any]] = []
        released_ids: list[int] = []
        blocked: list[dict[str, Any]] = []

        for slot in slots:
            sym = str(slot.symbol or "").upper() or None
            updated = slot.updated_at or slot.created_at or now
            if updated.tzinfo is None:
                updated = updated.replace(tzinfo=timezone.utc)
            else:
                updated = updated.astimezone(timezone.utc)
            age_sec = max(0.0, (now - updated).total_seconds())
            row_info: dict[str, Any] = {
                "slot_id": int(slot.slot_id),
                "symbol": sym,
                "age_seconds": age_sec,
                "timeout_seconds": timeout,
            }
            inspected.append(row_info)

            if age_sec < timeout:
                blocked.append({**row_info, "reason": "NOT_YET_TIMEOUT"})
                continue
            if not sym:
                blocked.append({**row_info, "reason": "SYMBOL_MISSING"})
                continue
            if self._has_local_open_order(uba_id, symbol=sym):
                blocked.append({**row_info, "reason": "LOCAL_OPEN_ORDER"})
                continue
            if self._has_pending_outbox_for_symbol(uba_id, symbol=sym):
                blocked.append({**row_info, "reason": "OUTBOX_PENDING"})
                continue
            if broker_open_symbols is not None and sym in {
                str(x).upper() for x in broker_open_symbols
            }:
                blocked.append({**row_info, "reason": "BROKER_OPEN_ORDER"})
                continue

            # selection history 보존 — ENTRY_PENDING timeout 시 WAITING_SIGNAL로 복귀
            # (무한 고착 방지 + 재선정 루프 완화)
            slot.status = SLOT_WAITING_SIGNAL
            slot.reserved_amount_krw = None
            slot.allocated_amount_krw = None
            slot.clamp_reasons = []
            slot.entry_order_id = None
            slot.version = int(slot.version or 1) + 1
            released_ids.append(int(slot.slot_id))
            row_info["released"] = True
            row_info["rolled_back_to"] = SLOT_WAITING_SIGNAL

        if released_ids:
            assignment = self._assignment.get_or_create(uba_id)
            assignment.signals_paused = False
            if is_full_market_portfolio(assignment.mode):
                assignment.state = STATE_IDLE
            self._session.flush()
            logger.info(
                "portfolio_stale_entry_pending_recovered",
                uba_id=uba_id,
                released_slot_ids=released_ids,
                actor=str(actor or "system")[:80],
                timeout_seconds=timeout,
            )

        return {
            "ok": True,
            "released": len(released_ids),
            "released_slot_ids": released_ids,
            "blocked": blocked,
            "inspected": inspected,
            "timeout_seconds": timeout,
            "orders_created": 0,
        }

    def _has_local_open_order(
        self, user_broker_account_id: int, *, symbol: str
    ) -> bool:
        from sqlalchemy import func

        from stock_platform.order.entities import TradingOrderEntity

        open_statuses = (
            "CREATED",
            "PENDING",
            "SENT",
            "ACCEPTED",
            "PARTIALLY_FILLED",
            "CANCEL_REQUESTED",
            "REPLACE_REQUESTED",
        )
        count = self._session.scalar(
            select(func.count())
            .select_from(TradingOrderEntity)
            .where(
                TradingOrderEntity.user_broker_account_id
                == int(user_broker_account_id),
                TradingOrderEntity.symbol == str(symbol).upper(),
                TradingOrderEntity.status_code.in_(open_statuses),
            )
        )
        return int(count or 0) > 0

    def _has_pending_outbox_for_symbol(
        self, user_broker_account_id: int, *, symbol: str
    ) -> bool:
        from sqlalchemy import func

        from stock_platform.order.entities import TradingOrderEntity
        from stock_platform.order.outbox_entities import OrderOutbox
        from stock_platform.order.outbox_models import OutboxStatus

        pending = (
            OutboxStatus.PENDING.value,
            OutboxStatus.PROCESSING.value,
            OutboxStatus.RETRY.value,
            OutboxStatus.AMBIGUOUS.value,
            OutboxStatus.MANUAL_REVIEW.value,
        )
        count = self._session.scalar(
            select(func.count())
            .select_from(OrderOutbox)
            .join(
                TradingOrderEntity,
                TradingOrderEntity.order_id == OrderOutbox.order_id,
            )
            .where(
                TradingOrderEntity.user_broker_account_id
                == int(user_broker_account_id),
                TradingOrderEntity.symbol == str(symbol).upper(),
                OrderOutbox.status_code.in_(pending),
            )
        )
        return int(count or 0) > 0
