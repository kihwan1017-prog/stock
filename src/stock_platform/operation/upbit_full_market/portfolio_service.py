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
    AllocationResult,
)
from stock_platform.operation.upbit_full_market.portfolio_entry_sizing import (
    PortfolioEntryRiskLimits,
    allocate_portfolio_entry_amount,
    build_sizing_telemetry,
    effective_max_order_cap,
    resolve_portfolio_entry_risk_limits,
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


def _resolve_uba_user_id(session: Session, uba_id: int) -> int | None:
    from stock_platform.trading.account_models import UserBrokerAccount

    uba = session.get(UserBrokerAccount, int(uba_id))
    if uba is None or getattr(uba, "user_id", None) is None:
        return None
    return int(uba.user_id)


class UpbitPortfolioService:
    """Portfolio policy/slots/Top-K. Broker CREATE 없음."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._assignment = UpbitFullMarketAssignmentService(session)

    def _allocate_entry_with_risk_limits(
        self,
        uba_id: int,
        *,
        capital: Decimal,
        available_krw: Decimal,
        policy: UpbitPortfolioPolicyEntity,
        score: float,
        conf: float,
        volatility: str | None = None,
        activation_max_order_amount: Decimal | None = None,
        legacy_explicit_cap: Decimal | None = None,
    ) -> tuple[AllocationResult, PortfolioEntryRiskLimits, Decimal, dict[str, Any]]:
        """Portfolio desired → Risk-compatible executable amount (SoT: ResolvedRiskPolicy)."""

        user_id = _resolve_uba_user_id(self._session, uba_id)
        risk_limits = resolve_portfolio_entry_risk_limits(
            self._session,
            user_broker_account_id=int(uba_id),
            user_id=user_id,
        )
        effective_cap = effective_max_order_cap(
            risk_limits,
            activation_max_order_amount=activation_max_order_amount,
            legacy_explicit_cap=legacy_explicit_cap,
        )
        alloc = allocate_portfolio_entry_amount(
            AllocationInput(
                portfolio_capital_limit_krw=capital,
                available_krw=available_krw,
                min_cash_reserve_pct=float(policy.min_cash_reserve_pct),
                per_position_target_pct=float(policy.per_position_target_pct),
                max_symbol_exposure_pct=float(policy.max_symbol_exposure_pct),
                max_total_exposure_pct=float(policy.max_total_exposure_pct),
                current_strategy_exposure_krw=self.strategy_exposure_total(
                    uba_id
                ),
                pending_reserved_krw=self.reserved_amount_total(uba_id),
                current_symbol_exposure_krw=Decimal("0"),
                account_max_order_amount=effective_cap,
                scanner_score=score,
                ai_confidence=conf,
                volatility=volatility,
            ),
            risk_limits=risk_limits,
            activation_max_order_amount=activation_max_order_amount,
            legacy_explicit_cap=legacy_explicit_cap,
        )
        sizing = build_sizing_telemetry(
            alloc,
            risk_limits=risk_limits,
            effective_cap=effective_cap,
        )
        return alloc, risk_limits, effective_cap, sizing

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
        from stock_platform.common.settings import get_settings
        from stock_platform.operation.upbit_full_market.portfolio_entry_signal import (
            load_thresholds_from_policy,
            resolve_ma_windows_from_policy,
            resolve_policy_from_row,
        )

        row = self.get_or_create_policy(int(user_broker_account_id))
        settings = get_settings()
        blob = dict(row.risk_group_policy_json or {})
        entry_policy = resolve_policy_from_row(
            risk_group_policy_json=blob,
            settings_default=str(
                getattr(
                    settings,
                    "upbit_portfolio_entry_signal_policy",
                    "CROSS_EVENT",
                )
            ),
        )
        thresholds = load_thresholds_from_policy(
            settings=settings,
            risk_group_policy_json=blob,
            candidate_max_age_seconds=int(row.candidate_max_age_seconds),
        )
        ma_windows = resolve_ma_windows_from_policy(
            risk_group_policy_json=blob,
            strategy_parameter_payload=self._strategy_parameter_payload(
                int(user_broker_account_id)
            ),
        )
        slots = self.list_slots(int(user_broker_account_id))
        capacity = int(row.max_positions)
        in_cap = [
            s for s in slots if int(s.get("slot_no") or 0) <= capacity
        ]
        occupied = sum(
            1
            for s in in_cap
            if str(s.get("status") or "").upper() != SLOT_EMPTY
        )
        empty_n = sum(
            1
            for s in in_cap
            if str(s.get("status") or "").upper() == SLOT_EMPTY
        )
        waiting = sum(
            1
            for s in in_cap
            if str(s.get("status") or "").upper()
            in {
                SLOT_SELECTED,
                SLOT_WARMING_UP,
                SLOT_WAITING_SIGNAL,
            }
        )
        return {
            "policy_id": int(row.policy_id),
            "enabled": bool(row.enabled),
            "max_positions": capacity,
            "slot_capacity": capacity,
            "slots_occupied": occupied,
            "slots_waiting": waiting,
            "slots_empty": empty_n,
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
            "entry_signal_policy": entry_policy,
            "risk_group_policy_json": blob,
            "version": int(row.version),
            "rsi_max": float(thresholds.rsi_max),
            "min_ma_separation_pct": float(thresholds.min_ma_separation_pct),
            "min_volume_surge": float(thresholds.min_volume_surge),
            "require_ai_allow": bool(thresholds.require_ai_allow),
            "short_ma_window": int(ma_windows["short_ma_window"]),
            "long_ma_window": int(ma_windows["long_ma_window"]),
            "ownership_requirement": "FREE",
            "ai_requirement_label": (
                "ALLOW" if thresholds.require_ai_allow else "ANY"
            ),
            **self._ma_exit_policy_public(
                risk_group_policy_json=blob,
                entry_cooldown_seconds=int(row.entry_cooldown_seconds),
            ),
            **self._replacement_policy_public(
                risk_group_policy_json=blob,
                candidate_max_age_seconds=int(row.candidate_max_age_seconds),
            ),
        }

    def _strategy_parameter_payload(
        self, user_broker_account_id: int
    ) -> dict[str, Any] | None:
        """Active link strategy parameter_payload — MA window 표시용."""

        try:
            from sqlalchemy import select

            from stock_platform.strategy_deployment.definition_entities import (
                AccountStrategyLinkEntity,
                StrategyDefinitionEntity,
            )

            link = self._session.scalar(
                select(AccountStrategyLinkEntity)
                .where(
                    AccountStrategyLinkEntity.user_broker_account_id
                    == int(user_broker_account_id),
                    AccountStrategyLinkEntity.is_active.is_(True),
                )
                .limit(1)
            )
            if link is None or link.strategy_id is None:
                return None
            defn = self._session.get(
                StrategyDefinitionEntity, int(link.strategy_id)
            )
            if defn is None:
                return None
            payload = getattr(defn, "parameter_payload", None)
            return dict(payload) if isinstance(payload, dict) else None
        except Exception:  # noqa: BLE001
            return None

    def _ma_exit_policy_public(
        self,
        *,
        risk_group_policy_json: dict[str, Any],
        entry_cooldown_seconds: int,
    ) -> dict[str, Any]:
        """전략 MA 청산 anti-churn — 보호 청산과 분리 표시."""

        from stock_platform.common.settings import get_settings
        from stock_platform.realtime.ma_exit_policy import (
            load_ma_exit_thresholds,
        )

        th = load_ma_exit_thresholds(
            settings=get_settings(),
            risk_group_policy_json=risk_group_policy_json,
        )
        return {
            "exit_min_ma_separation_pct": float(th.exit_min_ma_separation_pct),
            "ma_exit_min_holding_seconds": int(th.ma_exit_min_holding_seconds),
            # 동일종목 재진입 — 기존 entry_cooldown / slot cooldown 재사용
            "strategy_exit_reentry_cooldown_seconds": int(
                entry_cooldown_seconds
            ),
            "ma_exit_applies_to_protective": False,
            "ma_exit_profit_only_gate": False,
        }

    def _replacement_policy_public(
        self,
        *,
        risk_group_policy_json: dict[str, Any],
        candidate_max_age_seconds: int,
    ) -> dict[str, Any]:
        from stock_platform.common.settings import get_settings
        from stock_platform.operation.upbit_full_market.slot_replacement import (
            load_replacement_policy,
        )

        pol = load_replacement_policy(
            settings=get_settings(),
            risk_group_policy_json=risk_group_policy_json,
            candidate_max_age_seconds=candidate_max_age_seconds,
        )
        return {
            "candidate_hold_seconds": int(pol.hold_seconds),
            "candidate_max_wait_seconds": int(pol.max_wait_seconds),
            "candidate_switch_min_score_delta": float(
                pol.switch_min_score_delta
            ),
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
            elif key == "entry_signal_policy" and value is not None:
                from stock_platform.operation.upbit_full_market.portfolio_entry_signal import (
                    normalize_entry_policy,
                )

                blob = dict(row.risk_group_policy_json or {})
                blob["entry_signal_policy"] = normalize_entry_policy(str(value))
                row.risk_group_policy_json = blob
            elif key in {
                "candidate_hold_seconds",
                "candidate_max_wait_seconds",
                "candidate_switch_min_score_delta",
            }:
                blob = dict(row.risk_group_policy_json or {})
                if value is None:
                    continue
                try:
                    num = float(value)
                except (TypeError, ValueError):
                    continue
                if key == "candidate_hold_seconds":
                    blob[key] = max(0, int(num))
                elif key == "candidate_max_wait_seconds":
                    blob[key] = max(60, int(num))
                else:
                    blob[key] = max(0.0, float(num))
                row.risk_group_policy_json = blob
            elif key in {
                "rsi_max",
                "min_ma_separation_pct",
                "min_volume_surge",
                "require_ai_allow",
                "short_ma_window",
                "long_ma_window",
                "exit_min_ma_separation_pct",
                "ma_exit_min_holding_seconds",
            }:
                blob = dict(row.risk_group_policy_json or {})
                if value is None:
                    continue
                if key == "require_ai_allow":
                    blob[key] = bool(value)
                elif key == "rsi_max":
                    v = float(value)
                    if not (0 < v <= 100):
                        raise ValueError("RSI_MAX_OUT_OF_RANGE")
                    blob[key] = v
                elif key == "min_ma_separation_pct":
                    v = float(value)
                    if v < 0:
                        raise ValueError("MA_SEPARATION_NEGATIVE")
                    blob[key] = v
                elif key == "exit_min_ma_separation_pct":
                    v = float(value)
                    if v < 0:
                        raise ValueError("EXIT_MA_SEPARATION_NEGATIVE")
                    blob[key] = v
                elif key == "ma_exit_min_holding_seconds":
                    blob[key] = max(0, int(value))
                elif key == "min_volume_surge":
                    v = float(value)
                    if v <= 0:
                        raise ValueError("VOLUME_SURGE_INVALID")
                    blob[key] = v
                elif key == "short_ma_window":
                    v = max(1, int(value))
                    long_v = blob.get("long_ma_window")
                    if long_v is not None:
                        try:
                            if v >= int(long_v):
                                raise ValueError("MA_WINDOW_ORDER_INVALID")
                        except (TypeError, ValueError):
                            pass
                    blob[key] = v
                elif key == "long_ma_window":
                    v = max(2, int(value))
                    short_v = blob.get("short_ma_window")
                    if short_v is not None:
                        try:
                            if int(short_v) >= v:
                                raise ValueError("MA_WINDOW_ORDER_INVALID")
                        except (TypeError, ValueError):
                            pass
                    blob[key] = v
                row.risk_group_policy_json = blob
            elif key == "risk_group_policy_json" and isinstance(value, dict):
                blob = dict(row.risk_group_policy_json or {})
                blob.update(value)
                if "entry_signal_policy" in blob:
                    from stock_platform.operation.upbit_full_market.portfolio_entry_signal import (
                        normalize_entry_policy,
                    )

                    blob["entry_signal_policy"] = normalize_entry_policy(
                        str(blob["entry_signal_policy"])
                    )
                row.risk_group_policy_json = blob
        # MA window 최종 교차 검증
        blob = dict(row.risk_group_policy_json or {})
        short_v = blob.get("short_ma_window")
        long_v = blob.get("long_ma_window")
        if short_v is not None and long_v is not None:
            try:
                if int(short_v) >= int(long_v):
                    raise ValueError("MA_WINDOW_ORDER_INVALID")
            except (TypeError, ValueError) as exc:
                if str(exc) == "MA_WINDOW_ORDER_INVALID":
                    raise
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
        from stock_platform.operation.upbit_full_market.portfolio_daily_entry_count import (
            summarize_portfolio_daily_entries,
        )

        daily_entry = summarize_portfolio_daily_entries(
            self._session,
            int(user_broker_account_id),
            daily_limit=int(policy.get("portfolio_daily_entry_limit") or 10),
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
            "daily_entry": daily_entry,
            "daily_entry_label_ko": (
                f"오늘 실제 진입 {daily_entry['entry_count']} / "
                f"{daily_entry['entry_limit']} "
                f"(남은 {daily_entry['remaining']})"
            ),
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

    def link_entry_order_to_pending_slot(
        self,
        user_broker_account_id: int,
        *,
        order_id: int,
        symbol: str,
        actor: str = "system",
    ) -> dict[str, Any]:
        """BUY 주문 생성 직후 ENTRY_PENDING slot.entry_order_id 연결."""

        from stock_platform.operation.upbit_full_market.portfolio_lifecycle_sync import (
            link_entry_order_to_pending_slot,
        )

        return link_entry_order_to_pending_slot(
            self._session,
            user_broker_account_id=int(user_broker_account_id),
            order_id=int(order_id),
            symbol=str(symbol),
            actor=actor,
        )

    def reconcile_portfolio_slot_lifecycle(
        self,
        user_broker_account_id: int,
        *,
        symbol: str | None = None,
        actor: str = "system",
    ) -> dict[str, Any]:
        """Local AUTO order 기준 slot/binding lifecycle 복원 (멱등)."""

        from stock_platform.operation.upbit_full_market.portfolio_lifecycle_sync import (
            reconcile_portfolio_slot_lifecycle,
        )

        return reconcile_portfolio_slot_lifecycle(
            self._session,
            user_broker_account_id=int(user_broker_account_id),
            symbol=symbol,
            actor=actor,
        )

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
        from stock_platform.operation.upbit_full_market.portfolio_entry_signal import (
            portfolio_entry_telemetry,
        )

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
        sel_ids = [
            int(s.candidate_selection_id)
            for s in rows
            if s.candidate_selection_id is not None
        ]
        sel_by_id: dict[int, Any] = {}
        if sel_ids:
            for sel in self._session.scalars(
                select(UpbitLiveCandidateSelectionEntity).where(
                    UpbitLiveCandidateSelectionEntity.selection_id.in_(sel_ids)
                )
            ):
                sel_by_id[int(sel.selection_id)] = sel
        evals = portfolio_entry_telemetry.snapshot(int(user_broker_account_id))
        policy_row = self.get_or_create_policy(int(user_broker_account_id))
        repl = self._replacement_policy_public(
            risk_group_policy_json=dict(policy_row.risk_group_policy_json or {}),
            candidate_max_age_seconds=int(policy_row.candidate_max_age_seconds),
        )
        max_wait_s = float(repl.get("candidate_max_wait_seconds") or 10800)
        hold_s = float(repl.get("candidate_hold_seconds") or 1800)
        switch_delta = float(repl.get("candidate_switch_min_score_delta") or 8)
        out: list[dict[str, Any]] = []
        for s in rows:
            sel = (
                sel_by_id.get(int(s.candidate_selection_id))
                if s.candidate_selection_id is not None
                else None
            )
            sym = str(s.symbol or "").upper()
            ev = evals.get(sym) if isinstance(evals, dict) else None
            if not isinstance(ev, dict):
                ev = {}
            waiting_age_seconds = None
            if sel is not None and getattr(sel, "selected_at", None) is not None:
                try:
                    selected = sel.selected_at
                    if selected.tzinfo is None:
                        selected = selected.replace(tzinfo=timezone.utc)
                    waiting_age_seconds = max(
                        0.0,
                        (datetime.now(timezone.utc) - selected).total_seconds(),
                    )
                except Exception:  # noqa: BLE001
                    waiting_age_seconds = None
            slot_score = (
                float(sel.score) if sel is not None and sel.score is not None else None
            )
            max_wait_exceeded = (
                waiting_age_seconds is not None
                and float(waiting_age_seconds) >= max_wait_s
            )
            within_hold = (
                waiting_age_seconds is not None
                and float(waiting_age_seconds) < hold_s
            )
            out.append(
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
                        s.cooldown_until.isoformat()
                        if s.cooldown_until
                        else None
                    ),
                    "version": int(s.version),
                    "scanner_score": slot_score,
                    "score": slot_score,
                    "ai_recommendation": (
                        sel.ai_recommendation if sel is not None else None
                    ),
                    "ai_confidence": (
                        float(sel.confidence)
                        if sel is not None and sel.confidence is not None
                        else None
                    ),
                    "waiting_age_seconds": waiting_age_seconds,
                    "last_entry_decision": ev.get("last_decision"),
                    "last_entry_block_reason": ev.get("last_block_reason"),
                    "last_entry_evaluated_at": ev.get("last_evaluated_at"),
                    "entry_evaluation_count": ev.get("evaluation_count"),
                    "replacement_max_wait_seconds": int(max_wait_s),
                    "replacement_max_wait_exceeded": max_wait_exceeded,
                    "replacement_within_hold": within_hold,
                    "replacement_min_score_to_beat": slot_score,
                    "replacement_switch_min_score_delta": switch_delta,
                }
            )
        return out

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
        # 주문/체결과 slot 불일치 복구 (멱등) — stale recovery 전에 실행
        try:
            from stock_platform.operation.upbit_full_market.portfolio_lifecycle_sync import (
                reconcile_portfolio_slot_lifecycle,
            )

            lifecycle_rec = reconcile_portfolio_slot_lifecycle(
                self._session, user_broker_account_id=uba_id, actor="consume_top_k"
            )
            if lifecycle_rec.get("changed"):
                out["lifecycle_reconciled"] = lifecycle_rec
        except Exception as exc:  # noqa: BLE001
            out["lifecycle_reconcile_error"] = type(exc).__name__

        # ENTRY_PENDING(실제 주문 단계) 고착만 timeout 복구 — WAITING_SIGNAL 제외
        stale_rec = self.recover_stale_entry_pending_without_order(uba_id)
        if int(stale_rec.get("released") or 0) > 0:
            out["stale_entry_recovered"] = stale_rec

        # NOTE: hold/score-delta는 EMPTY fill을 막지 않는다.
        # WAITING_SIGNAL 교체 경로에서만 사용 (_try_replace_waiting_signal).

        if self.pending_entry_count(uba_id) >= int(
            policy.portfolio_max_pending_entries
        ):
            out["reason"] = "PENDING_ENTRY_LIMIT"
            return out

        # portfolio_daily_entry_limit — REAL AUTO BUY(KST day) SoT.
        # SUPERSEDED/SELECTED/slot rotation 은 쿼터를 소비하지 않는다.
        from stock_platform.operation.upbit_full_market.portfolio_daily_entry_count import (
            summarize_portfolio_daily_entries,
        )

        daily_limit = int(policy.portfolio_daily_entry_limit)
        daily_usage = summarize_portfolio_daily_entries(
            self._session,
            uba_id,
            daily_limit=daily_limit,
            now=_now(),
        )
        out["daily_entry_usage"] = daily_usage
        if int(daily_usage["entry_count"]) >= daily_limit:
            out["reason"] = "PORTFOLIO_DAILY_ENTRY_LIMIT"
            try:
                from stock_platform.notification.telegram_policy import (
                    maybe_emit_upbit_daily_limit_edge,
                )

                maybe_emit_upbit_daily_limit_edge(
                    usage=daily_usage, uba_id=uba_id
                )
            except Exception:  # noqa: BLE001
                pass
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
            # EMPTY 없음 → WAITING_SIGNAL 안전 교체 시도 (OPEN/ENTRY_PENDING 보호)
            replaced = self._try_replace_waiting_signal(
                uba_id,
                candidates=candidates,
                scanner_run_id=scanner_run_id,
                scanner_completed_at=scanner_completed_at,
                dry_run=dry_run,
                out=out,
            )
            return replaced

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
            # 공통 Symbol Ownership gate (MANUAL/AUTO/UNKNOWN 제외)
            gate = self._ownership_entry_gate(uba_id, cand.symbol)
            if not gate["allowed"]:
                skip_all.append(
                    {
                        "symbol": cand.symbol,
                        "ok": False,
                        "reason": gate.get("reason")
                        or "SYMBOL_OWNERSHIP_BLOCKED",
                        "owner": gate.get("owner"),
                        "ownership_reasons": gate.get("ownership_reasons"),
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
                    != str(cand.symbol).upper()
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
        alloc, _risk_limits, _cap, sizing = self._allocate_entry_with_risk_limits(
            uba_id,
            capital=capital,
            available_krw=Decimal(str(available_krw or capital)),
            policy=policy,
            score=float(chosen.score or 80.0),
            conf=float(chosen.confidence or 0.8),
            volatility=(chosen.technical_metrics or {}).get("volatility"),
            activation_max_order_amount=activation_max_order_amount,
            legacy_explicit_cap=max_order if account_max_order_amount else None,
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
        return self._assign_candidate_to_empty_slot(
            uba_id,
            assignment=assignment,
            slot=slot,
            chosen=chosen,
            scanner_run_id=scanner_run_id,
            skip_all=skip_all,
            out=out,
            dry_run=False,
        )

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
        legacy_cap = (
            Decimal(str(account_max_order_amount))
            if account_max_order_amount is not None
            else None
        )
        alloc, _risk_limits, _cap, sizing = self._allocate_entry_with_risk_limits(
            int(user_broker_account_id),
            capital=capital,
            available_krw=avail,
            policy=policy,
            score=float(scanner_score),
            conf=float(ai_confidence),
            volatility=volatility,
            legacy_explicit_cap=legacy_cap,
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
            "sizing": sizing,
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

    def _ownership_entry_gate(
        self, uba_id: int, symbol: str
    ) -> dict[str, Any]:
        try:
            from stock_platform.trading.symbol_ownership import (
                SymbolOwnershipService,
            )

            allowed, skip_reason, ownership = SymbolOwnershipService(
                self._session
            ).entry_gate(
                broker_code="UPBIT",
                user_broker_account_id=int(uba_id),
                symbol=str(symbol),
            )
            return {
                "allowed": bool(allowed),
                "reason": skip_reason,
                "owner": ownership.owner,
                "ownership_reasons": ownership.reasons,
            }
        except Exception:  # noqa: BLE001
            return {
                "allowed": False,
                "reason": "SYMBOL_OWNERSHIP_UNKNOWN",
                "owner": None,
                "ownership_reasons": [],
            }

    def _slot_has_open_order(self, uba_id: int, symbol: str) -> bool:
        """로컬 미체결 주문 존재 여부 (교체 보호)."""

        sym = str(symbol or "").upper()
        if not sym:
            return False
        try:
            from stock_platform.order.entities import TradingOrderEntity

            row = self._session.scalar(
                select(TradingOrderEntity.order_id)
                .where(
                    TradingOrderEntity.user_broker_account_id == int(uba_id),
                    TradingOrderEntity.symbol == sym,
                    TradingOrderEntity.status_code.in_(
                        (
                            "NEW",
                            "ACCEPTED",
                            "PARTIAL",
                            "PARTIAL_FILLED",
                            "SUBMITTED",
                            "OPEN",
                            "WORKING",
                        )
                    ),
                )
                .limit(1)
            )
            return row is not None
        except Exception:  # noqa: BLE001
            # 조회 실패 시 fail-closed (교체 금지)
            return True

    def _assign_candidate_to_empty_slot(
        self,
        uba_id: int,
        *,
        assignment: UpbitFullMarketAssignmentEntity,
        slot: UpbitPositionSlotEntity,
        chosen: Any,
        scanner_run_id: str,
        skip_all: list[dict[str, Any]],
        out: dict[str, Any],
        dry_run: bool,
    ) -> dict[str, Any]:
        """EMPTY slot에 신규 selection 배정 + runtime sync. 주문 없음."""

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
        slot.recommended_amount_krw = None
        slot.allocated_amount_krw = None
        slot.reserved_amount_krw = None
        slot.clamp_reasons = []
        slot.entry_order_id = None
        slot.updated_at = _now()
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
        out["orders_created"] = 0
        out["slots"] = self.list_slots(uba_id)
        if not dry_run:
            try:
                from stock_platform.operation.upbit_full_market.replacement_notify import (
                    publish_slot_assigned_alert,
                )

                out["notify"] = publish_slot_assigned_alert(
                    user_broker_account_id=uba_id,
                    symbol=str(chosen.symbol),
                    slot_no=int(slot.slot_no),
                    scanner_score=float(chosen.score)
                    if chosen.score is not None
                    else None,
                    recommendation=str(chosen.recommendation or "") or None,
                    confidence=float(chosen.confidence)
                    if chosen.confidence is not None
                    else None,
                    selection_id=int(sel.selection_id),
                    scanner_run_id=scanner_run_id,
                )
            except Exception as exc:  # noqa: BLE001
                out["notify"] = {
                    "ok": False,
                    "reason": type(exc).__name__,
                }
        return out

    def _try_replace_waiting_signal(
        self,
        uba_id: int,
        *,
        candidates: list[dict[str, Any]],
        scanner_run_id: str,
        scanner_completed_at: datetime | None,
        dry_run: bool,
        out: dict[str, Any],
    ) -> dict[str, Any]:
        """WAITING_SIGNAL 만석 시 안전 교체 (cycle당 최대 1건, 주문 없음)."""

        from stock_platform.common.settings import get_settings
        from stock_platform.operation.upbit_full_market.constants import (
            SELECTION_STATUS_SUPERSEDED,
        )
        from stock_platform.operation.upbit_full_market.slot_replacement import (
            CandidateScoreView,
            SlotScoreView,
            load_replacement_policy,
            pick_best_replacement,
            reason_ko,
        )

        assignment = self._assignment.get_or_create(uba_id)
        policy = self.get_or_create_policy(uba_id)
        repl_pol = load_replacement_policy(
            settings=get_settings(),
            risk_group_policy_json=dict(policy.risk_group_policy_json or {}),
            candidate_max_age_seconds=int(policy.candidate_max_age_seconds),
        )
        out["replacement_policy"] = {
            "hold_seconds": repl_pol.hold_seconds,
            "max_wait_seconds": repl_pol.max_wait_seconds,
            "switch_min_score_delta": repl_pol.switch_min_score_delta,
            "candidate_max_age_seconds": repl_pol.candidate_max_age_seconds,
        }

        waiting = list(
            self._session.scalars(
                select(UpbitPositionSlotEntity)
                .where(
                    UpbitPositionSlotEntity.user_broker_account_id == uba_id,
                    UpbitPositionSlotEntity.status == SLOT_WAITING_SIGNAL,
                )
                .order_by(UpbitPositionSlotEntity.slot_no)
                .with_for_update()
            )
        )
        if not waiting:
            out["reason"] = "NO_EMPTY_SLOT"
            out["orders_created"] = 0
            return out

        # telemetry (읽기 전용 — tick DB write 금지)
        telem_map: dict[str, Any] = {}
        try:
            from stock_platform.operation.upbit_full_market.portfolio_entry_signal import (
                portfolio_entry_telemetry,
            )

            snap = portfolio_entry_telemetry.snapshot(uba_id) or {}
            telem_map = dict(snap) if isinstance(snap, dict) else {}
        except Exception:  # noqa: BLE001
            telem_map = {}

        slot_views: list[SlotScoreView] = []
        protected_symbols: set[str] = set()
        for slot in waiting:
            score = 0.0
            selected_at = None
            if slot.candidate_selection_id is not None:
                sel = self._session.get(
                    UpbitLiveCandidateSelectionEntity,
                    int(slot.candidate_selection_id),
                )
                if sel is not None:
                    try:
                        score = float(sel.score or 0)
                    except (TypeError, ValueError):
                        score = 0.0
                    selected_at = sel.selected_at
            sym = str(slot.symbol or "").upper()
            telem = telem_map.get(sym) or {}
            if not isinstance(telem, dict):
                telem = {}
            slot_views.append(
                SlotScoreView(
                    slot_id=int(slot.slot_id),
                    slot_no=int(slot.slot_no),
                    status=str(slot.status),
                    symbol=sym,
                    score=score,
                    updated_at=slot.updated_at,
                    selected_at=selected_at,
                    reserved_amount_krw=(
                        float(slot.reserved_amount_krw)
                        if slot.reserved_amount_krw is not None
                        else None
                    ),
                    entry_order_id=(
                        int(slot.entry_order_id)
                        if slot.entry_order_id is not None
                        else None
                    ),
                    position_binding_id=(
                        int(slot.position_binding_id)
                        if slot.position_binding_id is not None
                        else None
                    ),
                    has_open_order=self._slot_has_open_order(uba_id, sym),
                    last_block_reason=telem.get("last_block_reason")
                    or telem.get("last_reason_code"),
                    evaluation_count=int(telem.get("evaluation_count") or 0),
                    last_decision=telem.get("last_decision"),
                )
            )

        # OPEN/ENTRY_PENDING 등 활성 심볼은 신규 후보와 중복 금지
        # (WAITING 심볼 중복은 pick_best_replacement가 slot별로 처리)
        for s in self.list_slots(uba_id):
            st = str(s.get("status") or "")
            sy = str(s.get("symbol") or "").upper()
            if sy and st in {
                SLOT_OPEN,
                SLOT_ENTRY_PENDING,
                SLOT_EXIT_PENDING,
                SLOT_RESERVED,
                SLOT_SELECTED,
                SLOT_WARMING_UP,
            }:
                protected_symbols.add(sy)

        # 후보 eligibility (scanner + ownership FREE/ALLOW)
        sel_policy = load_selection_policy_from_settings(assignment=assignment)
        sel_policy = SelectionPolicy(
            min_score=sel_policy.min_score,
            min_liquidity_krw=sel_policy.min_liquidity_krw,
            min_confidence=sel_policy.min_confidence,
            max_candidate_age_seconds=float(policy.candidate_max_age_seconds),
            ai_live_gate_mode=sel_policy.ai_live_gate_mode,
            excluded_symbols=sel_policy.excluded_symbols,
            allow_reduce_as_entry=sel_policy.allow_reduce_as_entry,
        )
        eligible_views: list[CandidateScoreView] = []
        skip_all: list[dict[str, Any]] = []
        remaining = list(candidates)
        seen: set[str] = set()
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
            sym = str(cand.symbol).upper()
            remaining = [
                c
                for c in remaining
                if str(
                    c.get("symbol")
                    if isinstance(c, dict)
                    else getattr(c, "symbol", "")
                ).upper()
                != sym
            ]
            if sym in seen:
                continue
            seen.add(sym)
            if self._assignment._has_preexisting_holding(uba_id, sym):
                skip_all.append(
                    {"symbol": sym, "ok": False, "reason": "PREEXISTING_HOLDING"}
                )
                continue
            gate = self._ownership_entry_gate(uba_id, sym)
            if not gate["allowed"]:
                skip_all.append(
                    {
                        "symbol": sym,
                        "ok": False,
                        "reason": gate.get("reason")
                        or "SYMBOL_OWNERSHIP_BLOCKED",
                        "owner": gate.get("owner"),
                    }
                )
                continue
            eligible_views.append(
                CandidateScoreView(
                    symbol=sym,
                    score=float(cand.score or 0),
                    recommendation=str(cand.recommendation or ""),
                    rank=int(cand.rank) if cand.rank is not None else None,
                    confidence=(
                        float(cand.confidence)
                        if cand.confidence is not None
                        else None
                    ),
                    raw={
                        "market_data_timestamp": cand.market_data_timestamp,
                        "liquidity": cand.liquidity,
                        "technical_metrics": dict(cand.technical_metrics or {}),
                        "ai_analysis_id": cand.ai_analysis_id,
                        "recommendation": cand.recommendation,
                        "confidence": cand.confidence,
                        "score": cand.score,
                        "rank": cand.rank,
                        "symbol": sym,
                    },
                )
            )

        out["skipped"] = skip_all

        # 교체 대상 slot 심볼은 protected에서 제외 (자기 자신 교체 허용)
        decision = pick_best_replacement(
            slots=slot_views,
            candidates=eligible_views,
            policy=repl_pol,
            now=_now(),
            protected_symbols=protected_symbols,
        )
        out["replacement_decision"] = {
            "replace": decision.replace,
            "reason": decision.reason,
            "old_symbol": decision.old_symbol,
            "new_symbol": decision.new_symbol,
            "old_score": decision.old_score,
            "new_score": decision.new_score,
            "age_seconds": decision.age_seconds,
            "detail": decision.detail,
        }
        if not decision.replace:
            out["reason"] = str(decision.reason or "NO_EMPTY_SLOT")
            # 하위 호환: 교체 불가 시 기존 reason 유지
            if out["reason"] in {
                "NO_REPLACEABLE_OR_CANDIDATE",
                "NO_MATCH",
                "DELTA_OR_WAIT_INSUFFICIENT",
                "WITHIN_HOLD",
            }:
                out["reason"] = "NO_EMPTY_SLOT"
            out["orders_created"] = 0
            return out

        # 매칭된 slot / candidate
        slot = next(
            (s for s in waiting if int(s.slot_id) == int(decision.slot_id or 0)),
            None,
        )
        cand_view = next(
            (
                c
                for c in eligible_views
                if c.symbol == str(decision.new_symbol or "").upper()
            ),
            None,
        )
        if slot is None or cand_view is None:
            out["reason"] = "NO_EMPTY_SLOT"
            out["orders_created"] = 0
            return out

        if dry_run:
            out["ok"] = True
            out["reason"] = "DRY_SLOT_REPLACED"
            out["orders_created"] = 0
            out["replacement"] = out["replacement_decision"]
            return out

        # --- atomic supersede ---
        old_symbol = str(slot.symbol or "").upper()
        old_sel_id = slot.candidate_selection_id
        old_score = decision.old_score
        if old_sel_id is not None:
            old_sel = self._session.get(
                UpbitLiveCandidateSelectionEntity, int(old_sel_id)
            )
            if old_sel is not None:
                old_sel.status = SELECTION_STATUS_SUPERSEDED
                old_sel.selection_reason = (
                    f"{old_sel.selection_reason or 'PORTFOLIO'}"
                    f"|SUPERSEDED_BY_{cand_view.symbol}"
                )[:200]

        raw = dict(cand_view.raw or {})
        new_sel = UpbitLiveCandidateSelectionEntity(
            user_broker_account_id=uba_id,
            strategy_id=assignment.strategy_id,
            deployment_id=assignment.deployment_id,
            scanner_run_id=scanner_run_id,
            symbol=cand_view.symbol,
            rank=cand_view.rank,
            score=cand_view.score,
            market_data_timestamp=raw.get("market_data_timestamp") or _now(),
            liquidity=raw.get("liquidity"),
            technical_metrics=dict(raw.get("technical_metrics") or {}),
            ai_analysis_id=raw.get("ai_analysis_id"),
            ai_recommendation=cand_view.recommendation,
            confidence=cand_view.confidence,
            selected_at=_now(),
            selection_reason=(
                f"PORTFOLIO_SLOT_{slot.slot_no}|REPLACE_{decision.reason}"
            ),
            status="SELECTED",
            skip_trace=list(skip_all),
        )
        self._session.add(new_sel)
        self._session.flush()

        slot.status = SLOT_SELECTED
        slot.symbol = cand_view.symbol
        slot.candidate_selection_id = int(new_sel.selection_id)
        slot.scanner_run_id = scanner_run_id
        slot.ai_analysis_id = raw.get("ai_analysis_id")
        slot.recommended_amount_krw = None
        slot.allocated_amount_krw = None
        slot.reserved_amount_krw = None
        slot.clamp_reasons = []
        slot.entry_order_id = None
        slot.position_binding_id = None
        slot.updated_at = _now()  # hold timer 재시작 (churn 방지)
        slot.version = int(slot.version or 1) + 1
        assignment.last_scanner_run_id = scanner_run_id
        assignment.current_symbol = cand_view.symbol
        self._session.flush()

        runtime_sync: dict[str, Any] | None = None
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
            runtime_sync = {"ok": False, "reason": type(exc).__name__}
        if runtime_sync and not bool(runtime_sync.get("ok")):
            slot.status = SLOT_BLOCKED
            slot.version = int(slot.version or 1) + 1
            self._session.flush()
            out["ok"] = False
            out["reason"] = "RUNTIME_SYNC_FAILED"
            out["runtime_sync"] = runtime_sync
            out["selection_id"] = int(new_sel.selection_id)
            out["slot_id"] = int(slot.slot_id)
            out["orders_created"] = 0
            out["slots"] = self.list_slots(uba_id)
            return out

        slot.status = SLOT_WAITING_SIGNAL
        slot.version = int(slot.version or 1) + 1
        self._session.flush()

        notify: dict[str, Any] | None = None
        try:
            from stock_platform.operation.upbit_full_market.replacement_notify import (
                publish_slot_replacement_alert,
            )

            notify = publish_slot_replacement_alert(
                user_broker_account_id=uba_id,
                old_symbol=old_symbol,
                new_symbol=cand_view.symbol,
                old_score=old_score,
                new_score=cand_view.score,
                reason=decision.reason,
                reason_display=reason_ko(decision.reason),
                slot_no=int(slot.slot_no),
                scanner_run_id=scanner_run_id,
            )
        except Exception as exc:  # noqa: BLE001
            notify = {"ok": False, "reason": type(exc).__name__}

        out["ok"] = True
        out["reason"] = "SLOT_REPLACED"
        out["orders_created"] = 0
        out["selection_id"] = int(new_sel.selection_id)
        out["slot_id"] = int(slot.slot_id)
        out["runtime_sync"] = runtime_sync
        out["notify"] = notify
        out["replacement"] = {
            **out["replacement_decision"],
            "old_selection_id": int(old_sel_id) if old_sel_id else None,
            "new_selection_id": int(new_sel.selection_id),
        }
        out["reserved"] = []
        out["slots"] = self.list_slots(uba_id)
        logger.info(
            "upbit_portfolio_slot_replaced",
            uba_id=uba_id,
            slot_id=int(slot.slot_id),
            old_symbol=old_symbol,
            new_symbol=cand_view.symbol,
            reason=decision.reason,
            orders_created=0,
        )
        return out

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

        # WAITING_SIGNAL + 수동 보유(바인딩 없음) → ENTRY 금지 + slot 안전 해제
        if self._assignment._has_preexisting_holding(uba_id, sym):
            reserve = float(slot.reserved_amount_krw or 0)
            released = False
            if slot.entry_order_id is None and reserve <= 0:
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
                self._session.flush()
                released = True
            return {
                "ok": False,
                "reason": "MANUAL_SYMBOL_EXCLUDED",
                "slot_released": released,
                "detail": "WAITING_SIGNAL_PREEXISTING_HOLDING",
            }

        # Symbol Ownership — exclusion/hold/unknown (AUTO_ALREADY_MANAGED는 이 slot 자체)
        try:
            from stock_platform.trading.symbol_ownership import (
                SymbolOwnershipService,
            )
            from stock_platform.trading.symbol_ownership.constants import (
                OWNER_FREE,
                SKIP_MANUAL_SYMBOL_EXCLUDED,
                SKIP_OWNERSHIP_UNKNOWN,
                SKIP_AUTO_EXCLUDED,
                SKIP_SYMBOL_HOLD,
            )

            allowed, skip_reason, ownership = SymbolOwnershipService(
                self._session
            ).entry_gate(
                broker_code="UPBIT",
                user_broker_account_id=uba_id,
                symbol=sym,
            )
            if not allowed and skip_reason != "AUTO_SYMBOL_ALREADY_MANAGED":
                reserve = float(slot.reserved_amount_krw or 0)
                can_release = (
                    slot.entry_order_id is None
                    and reserve <= 0
                    and skip_reason
                    in {
                        SKIP_MANUAL_SYMBOL_EXCLUDED,
                        SKIP_OWNERSHIP_UNKNOWN,
                        SKIP_AUTO_EXCLUDED,
                        SKIP_SYMBOL_HOLD,
                    }
                )
                released = False
                if can_release:
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
                    self._session.flush()
                    released = True
                return {
                    "ok": False,
                    "reason": skip_reason or "SYMBOL_OWNERSHIP_BLOCKED",
                    "owner": ownership.owner,
                    "ownership_reasons": ownership.reasons,
                    "slot_released": released,
                    "expected_owner_for_entry": OWNER_FREE,
                }
        except Exception as exc:  # noqa: BLE001
            return {
                "ok": False,
                "reason": "SYMBOL_OWNERSHIP_UNKNOWN",
                "error": type(exc).__name__,
            }

        policy = self.get_or_create_policy(uba_id)
        if not policy.enabled:
            return {"ok": False, "reason": "POLICY_DISABLED"}
        if str(policy.entry_state or "") == PORTFOLIO_ENTRY_PAUSED:
            return {"ok": False, "reason": "ENTRY_PAUSED"}

        # BUY 직전 final admission의 fail-fast — WAITING은 quota 미소비.
        # hard cap은 OrderExecutionService persist fence가 보장.
        try:
            from stock_platform.operation.upbit_full_market.constants import (
                DEFAULT_PORTFOLIO_DAILY_ENTRY_LIMIT,
            )
            from stock_platform.operation.upbit_full_market.portfolio_daily_entry_count import (
                summarize_portfolio_daily_entries,
            )

            daily_limit = int(
                getattr(
                    policy,
                    "portfolio_daily_entry_limit",
                    DEFAULT_PORTFOLIO_DAILY_ENTRY_LIMIT,
                )
                or DEFAULT_PORTFOLIO_DAILY_ENTRY_LIMIT
            )
            daily_usage = summarize_portfolio_daily_entries(
                self._session,
                uba_id,
                daily_limit=daily_limit,
            )
            if int(daily_usage["entry_count"]) >= daily_limit:
                return {
                    "ok": False,
                    "reason": "PORTFOLIO_DAILY_ENTRY_LIMIT",
                    "daily_entry_usage": daily_usage,
                }
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "portfolio_daily_entry_failfast_skipped",
                error=type(exc).__name__,
                uba_id=uba_id,
            )

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
        alloc, _risk_limits, _cap, sizing = self._allocate_entry_with_risk_limits(
            uba_id,
            capital=capital,
            available_krw=Decimal(str(available_krw or capital)),
            policy=policy,
            score=score,
            conf=conf,
            volatility="MEDIUM",
            activation_max_order_amount=activation_max_order_amount,
            legacy_explicit_cap=(
                account_max_order_amount
                if account_max_order_amount is not None
                else None
            ),
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
                "sizing": sizing,
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
            "requested_amount_krw": sizing.get("requested_amount_krw"),
            "final_order_amount_krw": sizing.get("final_order_amount_krw"),
            "effective_max_order_amount_krw": sizing.get(
                "effective_max_order_amount_krw"
            ),
            "clamped_by": sizing.get("clamped_by"),
            "clamp_reasons": list(alloc.clamp_reasons),
            "sizing": sizing,
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
            # FILLED BUY / open SELL 등 실제 lifecycle이 있으면 복구 시도
            try:
                from stock_platform.operation.upbit_full_market.portfolio_lifecycle_sync import (
                    reconcile_portfolio_slot_lifecycle,
                )

                rec = reconcile_portfolio_slot_lifecycle(
                    self._session,
                    user_broker_account_id=uba_id,
                    symbol=sym,
                    actor=str(actor or "stale_recovery"),
                )
                if rec.get("changed"):
                    blocked.append(
                        {
                            **row_info,
                            "reason": "LIFECYCLE_RECONCILED",
                            "reconcile": rec,
                        }
                    )
                    continue
            except Exception as exc:  # noqa: BLE001
                row_info["reconcile_error"] = type(exc).__name__
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
