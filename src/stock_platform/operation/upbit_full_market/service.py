"""FULL_MARKET assignment + selection consume 서비스 (주문 생성 금지)."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.operation.upbit_full_market.constants import (
    AI_GATE_ENFORCE,
    BINDING_STATUS_CLOSED,
    BINDING_STATUS_OPEN,
    CONFIRM_DISABLE_FULL_MARKET,
    CONFIRM_ENABLE_FULL_MARKET,
    MODE_FIXED_SYMBOL,
    MODE_FULL_MARKET_AUTO,
    PORTFOLIO_ENTRY_PAUSED,
    SELECTION_STATUS_ACTIVE,
    SELECTION_STATUS_CLOSED,
    SELECTION_STATUS_SELECTED,
    SELECTION_STATUS_SUPERSEDED,
    SLOT_ENTRY_PENDING,
    SLOT_OPEN,
    SOURCE_UPBIT_OPPORTUNITY_SCANNER,
    STATE_BLOCKED,
    STATE_CANDIDATE_SELECTED,
    STATE_COOLDOWN,
    STATE_IDLE,
    STATE_POSITION_CLOSED,
    STATE_POSITION_OPEN,
    STATE_SWITCH_PRECHECK,
    STATE_SWITCHED,
    STATE_WARMUP,
    is_any_full_market,
    is_full_market_portfolio,
    is_full_market_single,
)
from stock_platform.operation.upbit_full_market.entities import (
    UpbitFullMarketAssignmentEntity,
    UpbitLiveCandidateSelectionEntity,
    UpbitStrategyPositionBindingEntity,
)
from stock_platform.operation.upbit_full_market.selection_policy import (
    SelectionPolicy,
    select_best_eligible_candidate,
)

logger = structlog.get_logger(__name__)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def load_selection_policy_from_settings(
    settings: Any | None = None,
    *,
    assignment: UpbitFullMarketAssignmentEntity | None = None,
) -> SelectionPolicy:
    from stock_platform.common.settings import get_settings

    cfg = settings or get_settings()
    excluded: set[str] = set()
    raw_ex = getattr(cfg, "upbit_full_market_excluded_symbols", "") or ""
    for part in str(raw_ex).split(","):
        s = part.strip().upper()
        if s:
            excluded.add(s)
    policy_json = dict(getattr(assignment, "policy_json", None) or {})
    ai_mode = str(
        getattr(assignment, "ai_live_gate_mode", None)
        or getattr(cfg, "upbit_full_market_ai_live_gate_mode", AI_GATE_ENFORCE)
        or AI_GATE_ENFORCE
    ).upper()
    return SelectionPolicy(
        min_score=float(
            policy_json.get(
                "min_score",
                getattr(cfg, "upbit_full_market_min_score", 0.0),
            )
        ),
        min_liquidity_krw=float(
            policy_json.get(
                "min_liquidity_krw",
                getattr(cfg, "upbit_full_market_min_liquidity_krw", 0.0),
            )
        ),
        min_confidence=float(
            policy_json.get(
                "min_confidence",
                getattr(cfg, "upbit_full_market_min_confidence", 0.0),
            )
        ),
        max_candidate_age_seconds=float(
            policy_json.get(
                "max_candidate_age_seconds",
                getattr(cfg, "upbit_full_market_max_candidate_age_seconds", 1800.0),
            )
        ),
        ai_live_gate_mode=ai_mode,
        excluded_symbols=frozenset(excluded),
        allow_reduce_as_entry=bool(
            policy_json.get(
                "allow_reduce_as_entry",
                getattr(cfg, "upbit_full_market_allow_reduce_as_entry", True),
            )
        ),
    )


class UpbitFullMarketAssignmentService:
    """모드 전환·심볼 assignment·consume. Broker CREATE 금지."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get_or_create(
        self,
        user_broker_account_id: int,
        *,
        strategy_id: int | None = None,
        deployment_id: int | None = None,
        template_symbol: str | None = None,
    ) -> UpbitFullMarketAssignmentEntity:
        uba_id = int(user_broker_account_id)
        row = self._session.scalar(
            select(UpbitFullMarketAssignmentEntity).where(
                UpbitFullMarketAssignmentEntity.user_broker_account_id == uba_id
            )
        )
        if row is not None:
            if strategy_id is not None and row.strategy_id is None:
                row.strategy_id = int(strategy_id)
            if deployment_id is not None and row.deployment_id is None:
                row.deployment_id = int(deployment_id)
            if template_symbol and not row.template_symbol:
                row.template_symbol = str(template_symbol).upper()
            return row
        row = UpbitFullMarketAssignmentEntity(
            user_broker_account_id=uba_id,
            broker_code="UPBIT",
            strategy_id=int(strategy_id) if strategy_id else None,
            deployment_id=int(deployment_id) if deployment_id else None,
            mode=MODE_FIXED_SYMBOL,
            state=STATE_IDLE,
            template_symbol=(
                str(template_symbol).upper() if template_symbol else None
            ),
            current_symbol=(
                str(template_symbol).upper() if template_symbol else None
            ),
            ai_live_gate_mode=AI_GATE_ENFORCE,
            policy_json={},
        )
        self._session.add(row)
        self._session.flush()
        return row

    def status_dict(self, user_broker_account_id: int) -> dict[str, Any]:
        row = self._session.scalar(
            select(UpbitFullMarketAssignmentEntity).where(
                UpbitFullMarketAssignmentEntity.user_broker_account_id
                == int(user_broker_account_id)
            )
        )
        if row is None:
            return {
                "mode": MODE_FIXED_SYMBOL,
                "state": STATE_IDLE,
                "current_symbol": None,
                "template_symbol": None,
                "full_market_enabled": False,
                "portfolio_enabled": False,
                "warmup_ready": False,
                "market_data_fresh": False,
                "cooldown_until": None,
                "block_reason": None,
                "active_selection_id": None,
                "ai_live_gate_mode": AI_GATE_ENFORCE,
                "active_symbols": [],
            }
        active_symbols: list[str] = []
        if is_full_market_portfolio(row.mode):
            try:
                from stock_platform.operation.upbit_full_market.portfolio_service import (
                    UpbitPortfolioService,
                )

                active_symbols = UpbitPortfolioService(
                    self._session
                ).active_symbols(int(row.user_broker_account_id))
            except Exception:  # noqa: BLE001
                active_symbols = []
            if row.current_symbol and row.current_symbol not in active_symbols:
                active_symbols = [str(row.current_symbol).upper(), *active_symbols]
        elif row.current_symbol:
            active_symbols = [str(row.current_symbol).upper()]
        return {
            "assignment_id": int(row.assignment_id),
            "mode": row.mode,
            "state": row.state,
            "current_symbol": row.current_symbol,
            "template_symbol": row.template_symbol,
            "full_market_enabled": is_full_market_single(row.mode),
            "portfolio_enabled": is_full_market_portfolio(row.mode),
            "warmup_ready": bool(row.warmup_ready),
            "market_data_fresh": bool(row.market_data_fresh),
            "signals_paused": bool(row.signals_paused),
            "cooldown_until": (
                row.cooldown_until.isoformat() if row.cooldown_until else None
            ),
            "block_reason": row.block_reason,
            "active_selection_id": row.active_selection_id,
            "last_scanner_run_id": row.last_scanner_run_id,
            "ai_live_gate_mode": row.ai_live_gate_mode,
            "strategy_id": row.strategy_id,
            "deployment_id": row.deployment_id,
            "active_symbols": active_symbols,
        }

    def resolve_runtime_symbol(
        self,
        user_broker_account_id: int,
        *,
        fallback_symbol: str | None,
    ) -> str | None:
        """FULL_MARKET + 활성 target이면 current_symbol, 아니면 template/fallback."""

        row = self._session.scalar(
            select(UpbitFullMarketAssignmentEntity).where(
                UpbitFullMarketAssignmentEntity.user_broker_account_id
                == int(user_broker_account_id)
            )
        )
        if row is None or not is_any_full_market(row.mode):
            return (fallback_symbol or None) and str(fallback_symbol).upper()
        if row.current_symbol:
            return str(row.current_symbol).upper()
        return (row.template_symbol or fallback_symbol or None) and str(
            row.current_symbol or row.template_symbol or fallback_symbol
        ).upper()

    def resolve_runtime_symbols(
        self,
        user_broker_account_id: int,
        *,
        fallback_symbol: str | None,
    ) -> list[str]:
        """PORTFOLIO는 active slot 집합, SINGLE은 current 1개."""

        row = self._session.scalar(
            select(UpbitFullMarketAssignmentEntity).where(
                UpbitFullMarketAssignmentEntity.user_broker_account_id
                == int(user_broker_account_id)
            )
        )
        if row is None:
            fb = (fallback_symbol or None) and str(fallback_symbol).upper()
            return [fb] if fb else []
        if is_full_market_portfolio(row.mode):
            from stock_platform.operation.upbit_full_market.portfolio_service import (
                UpbitPortfolioService,
            )

            syms = UpbitPortfolioService(self._session).active_symbols(
                int(user_broker_account_id)
            )
            if not syms and row.current_symbol:
                syms = [str(row.current_symbol).upper()]
            if not syms and fallback_symbol:
                syms = [str(fallback_symbol).upper()]
            return syms
        one = self.resolve_runtime_symbol(
            int(user_broker_account_id),
            fallback_symbol=fallback_symbol,
        )
        return [one] if one else []

    def enable_full_market(
        self,
        user_broker_account_id: int,
        *,
        confirmation_text: str,
        actor: str,
        strategy_id: int | None = None,
        deployment_id: int | None = None,
        template_symbol: str | None = None,
        ai_live_gate_mode: str = AI_GATE_ENFORCE,
    ) -> dict[str, Any]:
        if str(confirmation_text or "").strip() != CONFIRM_ENABLE_FULL_MARKET:
            return {
                "ok": False,
                "error": "CONFIRMATION_MISMATCH",
                "expected": CONFIRM_ENABLE_FULL_MARKET,
            }
        # KIWOOM UBA 차단
        from stock_platform.trading.account_models import UserBrokerAccount

        uba = self._session.get(UserBrokerAccount, int(user_broker_account_id))
        if uba is None:
            return {"ok": False, "error": "UBA_NOT_FOUND"}
        if str(uba.broker_code or "").upper() != "UPBIT":
            return {"ok": False, "error": "BROKER_NOT_UPBIT"}

        row = self.get_or_create(
            int(user_broker_account_id),
            strategy_id=strategy_id,
            deployment_id=deployment_id,
            template_symbol=template_symbol,
        )
        row.mode = MODE_FULL_MARKET_AUTO
        row.state = STATE_IDLE
        row.ai_live_gate_mode = str(ai_live_gate_mode or AI_GATE_ENFORCE).upper()
        row.enabled_at = _now()
        row.enabled_by = str(actor or "admin")[:100]
        row.disabled_at = None
        row.disabled_by = None
        row.block_reason = None
        row.warmup_ready = False
        row.market_data_fresh = False
        if strategy_id is not None:
            row.strategy_id = int(strategy_id)
        if deployment_id is not None:
            row.deployment_id = int(deployment_id)
        if template_symbol:
            row.template_symbol = str(template_symbol).upper()
            if not row.current_symbol:
                row.current_symbol = row.template_symbol
        self._session.flush()
        logger.info(
            "upbit_full_market_enabled",
            uba_id=int(user_broker_account_id),
            actor=actor,
        )
        return {"ok": True, **self.status_dict(int(user_broker_account_id))}

    def disable_full_market(
        self,
        user_broker_account_id: int,
        *,
        confirmation_text: str,
        actor: str,
    ) -> dict[str, Any]:
        if str(confirmation_text or "").strip() != CONFIRM_DISABLE_FULL_MARKET:
            return {
                "ok": False,
                "error": "CONFIRMATION_MISMATCH",
                "expected": CONFIRM_DISABLE_FULL_MARKET,
            }
        row = self.get_or_create(int(user_broker_account_id))
        # 열린 strategy binding 있으면 심볼은 유지, 모드만 FIXED로 (신규 교체 금지)
        row.mode = MODE_FIXED_SYMBOL
        if row.template_symbol:
            row.current_symbol = row.template_symbol
        row.state = STATE_IDLE
        row.signals_paused = False
        row.warmup_ready = True
        row.market_data_fresh = True
        row.disabled_at = _now()
        row.disabled_by = str(actor or "admin")[:100]
        row.block_reason = None
        self._session.flush()
        logger.info(
            "upbit_full_market_disabled",
            uba_id=int(user_broker_account_id),
            actor=actor,
        )
        return {"ok": True, **self.status_dict(int(user_broker_account_id))}

    def has_open_strategy_position(self, user_broker_account_id: int) -> bool:
        row = self._session.scalar(
            select(UpbitStrategyPositionBindingEntity.binding_id).where(
                UpbitStrategyPositionBindingEntity.user_broker_account_id
                == int(user_broker_account_id),
                UpbitStrategyPositionBindingEntity.status == BINDING_STATUS_OPEN,
            )
        )
        return row is not None

    def is_strategy_owned_symbol(
        self, user_broker_account_id: int, symbol: str
    ) -> bool:
        sym = str(symbol or "").strip().upper()
        if not sym:
            return False
        row = self._session.scalar(
            select(UpbitStrategyPositionBindingEntity.binding_id).where(
                UpbitStrategyPositionBindingEntity.user_broker_account_id
                == int(user_broker_account_id),
                UpbitStrategyPositionBindingEntity.symbol == sym,
                UpbitStrategyPositionBindingEntity.status == BINDING_STATUS_OPEN,
            )
        )
        return row is not None

    def acquire_selection_lease(
        self,
        assignment: UpbitFullMarketAssignmentEntity,
        *,
        ttl_seconds: float = 30.0,
    ) -> str | None:
        """동시 selection 방지 — DB lease."""

        now = _now()
        until = assignment.selection_lease_until
        if (
            until is not None
            and until > now
            and assignment.selection_lease_token
        ):
            return None
        token = uuid.uuid4().hex
        assignment.selection_lease_token = token
        assignment.selection_lease_until = now + timedelta(seconds=ttl_seconds)
        self._session.flush()
        return token

    def release_selection_lease(
        self,
        assignment: UpbitFullMarketAssignmentEntity,
        token: str,
    ) -> None:
        if assignment.selection_lease_token == token:
            assignment.selection_lease_token = None
            assignment.selection_lease_until = None
            self._session.flush()

    def consume_scanner_candidates(
        self,
        user_broker_account_id: int,
        *,
        candidates: list[dict[str, Any]],
        scanner_run_id: str,
        scanner_completed_at: datetime | None = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Scanner 결과 → eligible 선택 → assignment 갱신. 주문 없음."""

        uba_id = int(user_broker_account_id)
        assignment = self.get_or_create(uba_id)
        out: dict[str, Any] = {
            "ok": False,
            "dry_run": bool(dry_run),
            "uba_id": uba_id,
            "mode": assignment.mode,
            "selected": None,
            "reason": None,
            "skip_trace": [],
            "orders_created": 0,
        }

        if is_full_market_portfolio(assignment.mode):
            out["reason"] = "USE_PORTFOLIO_CONSUME"
            return out
        if not is_full_market_single(assignment.mode):
            out["reason"] = "MODE_FIXED_SYMBOL"
            return out

        now = _now()
        if assignment.cooldown_until and assignment.cooldown_until > now:
            out["reason"] = "COOLDOWN_ACTIVE"
            out["cooldown_until"] = assignment.cooldown_until.isoformat()
            return out

        if self.has_open_strategy_position(uba_id):
            out["reason"] = "STRATEGY_POSITION_OPEN"
            return out

        if assignment.state == STATE_POSITION_OPEN:
            out["reason"] = "STATE_POSITION_OPEN"
            return out

        # 동일 scanner_run 중복 consume 방지
        if (
            assignment.last_scanner_run_id
            and assignment.last_scanner_run_id == scanner_run_id
            and assignment.active_selection_id is not None
            and assignment.state
            in {
                STATE_CANDIDATE_SELECTED,
                STATE_SWITCH_PRECHECK,
                STATE_SWITCHED,
                STATE_WARMUP,
                STATE_POSITION_OPEN,
            }
        ):
            out["reason"] = "SCANNER_RUN_ALREADY_CONSUMED"
            return out

        lease = self.acquire_selection_lease(assignment)
        if lease is None:
            out["reason"] = "SELECTION_LEASE_HELD"
            return out

        try:
            policy = load_selection_policy_from_settings(assignment=assignment)
            decision = select_best_eligible_candidate(
                candidates,
                policy,
                scanner_run_id=scanner_run_id,
                now=now,
                scanner_completed_at=scanner_completed_at,
            )
            out["skip_trace"] = decision.skip_trace
            out["reason"] = decision.reason
            if decision.selected is None:
                return out

            cand = decision.selected

            # 기존 수동 보유 심볼이면 skip (strategy-owned 아니면)
            if self._has_preexisting_holding(uba_id, cand.symbol):
                out["reason"] = "PREEXISTING_HOLDING"
                out["skip_trace"].append(
                    {
                        "symbol": cand.symbol,
                        "ok": False,
                        "reason": "PREEXISTING_HOLDING",
                    }
                )
                # 다음 rank 재시도
                remaining = [
                    c
                    for c in candidates
                    if str(
                        c.get("symbol") if isinstance(c, dict) else getattr(c, "symbol", "")
                    ).upper()
                    != cand.symbol
                ]
                decision2 = select_best_eligible_candidate(
                    remaining,
                    policy,
                    scanner_run_id=scanner_run_id,
                    now=now,
                    scanner_completed_at=scanner_completed_at,
                )
                out["skip_trace"].extend(decision2.skip_trace)
                out["reason"] = decision2.reason
                if decision2.selected is None:
                    return out
                cand = decision2.selected
                if self._has_preexisting_holding(uba_id, cand.symbol):
                    out["reason"] = "PREEXISTING_HOLDING_ALL"
                    return out

            # 공통 ownership gate
            try:
                from stock_platform.trading.symbol_ownership import (
                    SymbolOwnershipService,
                )

                allowed, skip_reason, ownership = SymbolOwnershipService(
                    self._session
                ).entry_gate(
                    broker_code="UPBIT",
                    user_broker_account_id=uba_id,
                    symbol=str(cand.symbol),
                )
                if not allowed:
                    out["reason"] = skip_reason or "SYMBOL_OWNERSHIP_BLOCKED"
                    out["skip_trace"].append(
                        {
                            "symbol": cand.symbol,
                            "ok": False,
                            "reason": out["reason"],
                            "owner": ownership.owner,
                        }
                    )
                    return out
            except Exception:  # noqa: BLE001
                out["reason"] = "SYMBOL_OWNERSHIP_UNKNOWN"
                return out

            selected_payload = {
                "symbol": cand.symbol,
                "rank": cand.rank,
                "score": cand.score,
                "recommendation": cand.recommendation,
                "confidence": cand.confidence,
                "liquidity": cand.liquidity,
                "ai_analysis_id": cand.ai_analysis_id,
            }
            out["selected"] = selected_payload

            if dry_run:
                out["ok"] = True
                out["reason"] = decision.reason
                return out

            # persist selection (idempotent unique)
            existing = self._session.scalar(
                select(UpbitLiveCandidateSelectionEntity).where(
                    UpbitLiveCandidateSelectionEntity.user_broker_account_id
                    == uba_id,
                    UpbitLiveCandidateSelectionEntity.scanner_run_id
                    == scanner_run_id,
                    UpbitLiveCandidateSelectionEntity.symbol == cand.symbol,
                )
            )
            if existing is not None:
                out["reason"] = "DUPLICATE_SELECTION_ROW"
                out["selection_id"] = int(existing.selection_id)
                return out

            # supersede prior ACTIVE
            priors = list(
                self._session.scalars(
                    select(UpbitLiveCandidateSelectionEntity).where(
                        UpbitLiveCandidateSelectionEntity.user_broker_account_id
                        == uba_id,
                        UpbitLiveCandidateSelectionEntity.status.in_(
                            [
                                SELECTION_STATUS_SELECTED,
                                SELECTION_STATUS_ACTIVE,
                            ]
                        ),
                    )
                )
            )
            for p in priors:
                p.status = SELECTION_STATUS_SUPERSEDED

            sel = UpbitLiveCandidateSelectionEntity(
                user_broker_account_id=uba_id,
                strategy_id=assignment.strategy_id,
                deployment_id=assignment.deployment_id,
                scanner_run_id=scanner_run_id,
                symbol=cand.symbol,
                rank=cand.rank,
                score=cand.score,
                market_data_timestamp=cand.market_data_timestamp or now,
                liquidity=cand.liquidity,
                technical_metrics=dict(cand.technical_metrics or {}),
                ai_analysis_id=cand.ai_analysis_id,
                ai_recommendation=cand.recommendation,
                confidence=cand.confidence,
                selected_at=now,
                selection_reason=decision.reason,
                source=SOURCE_UPBIT_OPPORTUNITY_SCANNER,
                status=SELECTION_STATUS_SELECTED,
                skip_trace=list(decision.skip_trace),
            )
            self._session.add(sel)
            self._session.flush()

            assignment.state = STATE_CANDIDATE_SELECTED
            assignment.active_selection_id = int(sel.selection_id)
            assignment.last_scanner_run_id = scanner_run_id
            assignment.signals_paused = True
            assignment.warmup_ready = False
            assignment.market_data_fresh = False
            assignment.block_reason = None
            self._session.flush()

            # switch precheck → assign symbol
            assignment.state = STATE_SWITCH_PRECHECK
            assignment.current_symbol = cand.symbol
            assignment.state = STATE_SWITCHED
            assignment.state = STATE_WARMUP
            sel.status = SELECTION_STATUS_ACTIVE
            self._session.flush()

            out["ok"] = True
            out["selection_id"] = int(sel.selection_id)
            out["assignment"] = self.status_dict(uba_id)
            out["reason"] = decision.reason
            return out
        finally:
            self.release_selection_lease(assignment, lease)

    def mark_warmup(
        self,
        user_broker_account_id: int,
        *,
        warmup_ready: bool,
        market_data_fresh: bool,
    ) -> dict[str, Any]:
        row = self.get_or_create(int(user_broker_account_id))
        row.warmup_ready = bool(warmup_ready)
        row.market_data_fresh = bool(market_data_fresh)
        if row.warmup_ready and row.market_data_fresh and is_full_market_single(
            row.mode
        ):
            if row.state == STATE_WARMUP:
                row.state = STATE_SWITCHED
            row.signals_paused = False
        self._session.flush()
        return self.status_dict(int(user_broker_account_id))

    def mark_position_open(
        self,
        user_broker_account_id: int,
        *,
        symbol: str,
        entry_order_id: int | None = None,
        selection_id: int | None = None,
        slot_id: int | None = None,
    ) -> dict[str, Any]:
        uba_id = int(user_broker_account_id)
        sym = str(symbol).upper()
        assignment = self.get_or_create(uba_id)
        if not is_any_full_market(assignment.mode):
            return {"ok": False, "reason": "MODE_FIXED_SYMBOL"}

        # 동일 심볼 OPEN binding 재사용 — overlapping OPEN INSERT 금지
        existing_open = self._session.scalar(
            select(UpbitStrategyPositionBindingEntity).where(
                UpbitStrategyPositionBindingEntity.user_broker_account_id
                == uba_id,
                UpbitStrategyPositionBindingEntity.symbol == sym,
                UpbitStrategyPositionBindingEntity.status
                == BINDING_STATUS_OPEN,
            )
        )
        if existing_open is not None:
            # 같은 entry_order면 idempotent reuse
            if (
                entry_order_id is not None
                and existing_open.entry_order_id is not None
                and int(existing_open.entry_order_id) != int(entry_order_id)
            ):
                return {
                    "ok": False,
                    "reason": "ENTRY_SKIPPED_EXISTING_SYMBOL_EXPOSURE",
                    "binding_id": int(existing_open.binding_id),
                    "existing_entry_order_id": int(existing_open.entry_order_id),
                }
            binding = existing_open
            reused = True
        else:
            binding = UpbitStrategyPositionBindingEntity(
                user_broker_account_id=uba_id,
                strategy_id=assignment.strategy_id,
                deployment_id=assignment.deployment_id,
                selection_id=selection_id or assignment.active_selection_id,
                slot_id=slot_id,
                symbol=sym,
                status=BINDING_STATUS_OPEN,
                entry_order_id=entry_order_id,
                opened_at=_now(),
                meta_json={},
            )
            self._session.add(binding)
            self._session.flush()
            reused = False

        if reused:
            self._session.flush()

        if is_full_market_portfolio(assignment.mode):
            from stock_platform.operation.upbit_full_market.entities import (
                UpbitPositionSlotEntity,
            )

            slot = None
            if slot_id is not None:
                slot = self._session.get(UpbitPositionSlotEntity, int(slot_id))
            if slot is None:
                slot = self._session.scalar(
                    select(UpbitPositionSlotEntity).where(
                        UpbitPositionSlotEntity.user_broker_account_id == uba_id,
                        UpbitPositionSlotEntity.symbol == sym,
                        UpbitPositionSlotEntity.status == SLOT_ENTRY_PENDING,
                    )
                )
            if slot is not None:
                slot.status = SLOT_OPEN
                slot.entry_order_id = entry_order_id
                slot.position_binding_id = int(binding.binding_id)
                slot.opened_at = _now()
                slot.reserved_amount_krw = None
                slot.version = int(slot.version or 1) + 1
                binding.slot_id = int(slot.slot_id)
            assignment.current_symbol = sym
        else:
            assignment.state = STATE_POSITION_OPEN
            assignment.current_symbol = sym
        self._session.flush()
        # Forward shadow cohort 등록 (연구용 — REAL 정책 무관)
        # binding reuse 시 중복 enroll 금지
        if not reused:
            try:
                from decimal import Decimal as _Dec

                from stock_platform.operation.upbit_opportunity_shadow.ma_exit_forward_shadow.hooks import (
                    enroll_binding_on_open,
                )

                entry_px = _Dec("0")
                entry_qty = None
                entry_fee = None
                if entry_order_id is not None:
                    from stock_platform.order.entities import TradingOrderEntity

                    order = self._session.get(
                        TradingOrderEntity, int(entry_order_id)
                    )
                    if order is not None:
                        avg = getattr(order, "average_fill_price", None) or getattr(
                            order, "limit_price", None
                        )
                        if avg is not None:
                            entry_px = _Dec(str(avg))
                        q = getattr(order, "filled_quantity", None) or getattr(
                            order, "quantity", None
                        )
                        if q is not None:
                            entry_qty = _Dec(str(q))
                if entry_px <= _Dec("0"):
                    entry_px = _Dec("1")

                enroll_binding_on_open(
                    self._session,
                    user_broker_account_id=uba_id,
                    binding_id=int(binding.binding_id),
                    symbol=sym,
                    strategy_id=assignment.strategy_id,
                    entry_order_id=entry_order_id,
                    entry_at=binding.opened_at,
                    entry_price=entry_px,
                    entry_quantity=entry_qty,
                    entry_fee=entry_fee,
                )
                from stock_platform.operation.upbit_opportunity_shadow.trailing_forward_shadow.hooks import (
                    enroll_binding_on_open as enroll_trailing_shadow,
                )

                enroll_trailing_shadow(
                    self._session,
                    user_broker_account_id=uba_id,
                    binding_id=int(binding.binding_id),
                    symbol=sym,
                    strategy_id=assignment.strategy_id,
                    entry_order_id=entry_order_id,
                    entry_at=binding.opened_at,
                    entry_price=entry_px,
                    entry_quantity=entry_qty,
                    entry_fee=entry_fee,
                )
                try:
                    from stock_platform.operation.upbit_opportunity_shadow.exit_optimization_shadow_v3.hooks import (
                        enroll_binding_on_open as enroll_eosv3_shadow,
                    )

                    enroll_eosv3_shadow(
                        self._session,
                        user_broker_account_id=uba_id,
                        binding_id=int(binding.binding_id),
                        symbol=sym,
                        strategy_id=assignment.strategy_id,
                        entry_order_id=entry_order_id,
                        entry_at=binding.opened_at,
                        entry_price=entry_px,
                        entry_quantity=entry_qty,
                        entry_fee=entry_fee,
                    )
                except Exception:  # noqa: BLE001
                    pass
                try:
                    from stock_platform.operation.upbit_opportunity_shadow.profitability_improvement_shadow.hooks import (
                        enroll_binding_on_open as enroll_pislab_shadow,
                    )

                    enroll_pislab_shadow(
                        self._session,
                        user_broker_account_id=uba_id,
                        binding_id=int(binding.binding_id),
                        symbol=sym,
                        strategy_id=assignment.strategy_id,
                        entry_order_id=entry_order_id,
                        entry_at=binding.opened_at,
                        entry_price=entry_px,
                        entry_quantity=entry_qty,
                        entry_fee=entry_fee,
                    )
                except Exception:  # noqa: BLE001
                    pass
                try:
                    from stock_platform.operation.upbit_opportunity_shadow.reentry_cooldown_shadow.hooks import (
                        enroll_reentry_on_open,
                    )

                    enroll_reentry_on_open(
                        self._session,
                        user_broker_account_id=uba_id,
                        symbol=sym,
                        entry_order_id=entry_order_id,
                        entry_at=binding.opened_at,
                    )
                except Exception:  # noqa: BLE001
                    pass
                from stock_platform.operation.upbit_opportunity_shadow.exit_strategy_shadow.hooks import (
                    enroll_binding_on_open as enroll_exit_strategy_shadow,
                )

                order_meta = None
                if entry_order_id is not None:
                    from stock_platform.order.entities import TradingOrderEntity

                    _ord = self._session.get(
                        TradingOrderEntity, int(entry_order_id)
                    )
                    if _ord is not None and isinstance(
                        getattr(_ord, "metadata_payload", None), dict
                    ):
                        order_meta = dict(_ord.metadata_payload)
                enroll_exit_strategy_shadow(
                    self._session,
                    user_broker_account_id=uba_id,
                    binding_id=int(binding.binding_id),
                    symbol=sym,
                    strategy_id=assignment.strategy_id,
                    entry_order_id=entry_order_id,
                    entry_at=binding.opened_at,
                    entry_price=entry_px,
                    entry_quantity=entry_qty,
                    entry_fee=entry_fee,
                    metadata=order_meta,
                )
            except Exception:  # noqa: BLE001
                pass
        # OPEN binding → protective quote feed (slot 없어도 GEOD 등 구독)
        feed: dict[str, Any] = {}
        try:
            from stock_platform.operation.upbit_full_market.portfolio_runtime_sync import (
                ensure_protective_quote_feed,
                sync_portfolio_runtime_symbols,
            )

            if is_full_market_portfolio(assignment.mode):
                feed = sync_portfolio_runtime_symbols(
                    self._session,
                    user_broker_account_id=uba_id,
                    ensure_quote_feed=True,
                )
            else:
                feed = ensure_protective_quote_feed(
                    self._session, user_broker_account_id=uba_id
                )
        except Exception as exc:  # noqa: BLE001
            feed = {"ok": False, "error": type(exc).__name__}
        return {
            "ok": True,
            "binding_id": int(binding.binding_id),
            "slot_id": binding.slot_id,
            "reused": reused,
            "protective_quote_feed": feed,
        }

    def mark_position_closed(
        self,
        user_broker_account_id: int,
        *,
        symbol: str | None = None,
        cooldown_seconds: float | None = None,
    ) -> dict[str, Any]:
        from stock_platform.common.settings import get_settings

        uba_id = int(user_broker_account_id)
        assignment = self.get_or_create(uba_id)
        now = _now()
        q = select(UpbitStrategyPositionBindingEntity).where(
            UpbitStrategyPositionBindingEntity.user_broker_account_id == uba_id,
            UpbitStrategyPositionBindingEntity.status == BINDING_STATUS_OPEN,
        )
        if symbol:
            q = q.where(
                UpbitStrategyPositionBindingEntity.symbol == str(symbol).upper()
            )
        closed_bindings = list(self._session.scalars(q))
        for b in closed_bindings:
            b.status = BINDING_STATUS_CLOSED
            b.closed_at = now
            try:
                from decimal import Decimal as _Dec

                from stock_platform.operation.upbit_opportunity_shadow.ma_exit_forward_shadow.hooks import (
                    finalize_binding_on_close,
                )

                meta = dict(b.meta_json or {})
                exit_reason = str(meta.get("exit_reason") or "UNKNOWN")
                exit_px = None
                exit_oid = meta.get("exit_order_id")
                if exit_oid is not None:
                    from stock_platform.order.entities import TradingOrderEntity

                    sell = self._session.get(TradingOrderEntity, int(exit_oid))
                    if sell is not None:
                        avg = getattr(sell, "average_fill_price", None)
                        if avg is not None:
                            exit_px = _Dec(str(avg))
                        if not exit_reason or exit_reason == "UNKNOWN":
                            mp = getattr(sell, "metadata_payload", None) or {}
                            if isinstance(mp, dict):
                                exit_reason = str(
                                    mp.get("signal_reason")
                                    or mp.get("exit_reason")
                                    or exit_reason
                                )
                # Shadow finalize용 PnL — Upbit binding에 realized_pnl/fees/quantity 없음.
                # entry/exit order fill 기반 (AttributeError로 Lab B/V3 swallow 방지).
                gross = 0.0
                fees = 0.0
                net = 0.0
                try:
                    from stock_platform.order.entities import TradingOrderEntity as _TO

                    entry_oid = getattr(b, "entry_order_id", None)
                    entry_px = None
                    qty = 0.0
                    buy_notional = 0.0
                    sell_notional = 0.0
                    if entry_oid is not None:
                        buy = self._session.get(_TO, int(entry_oid))
                        if buy is not None:
                            if getattr(buy, "average_fill_price", None) is not None:
                                entry_px = float(buy.average_fill_price)
                            qty = float(getattr(buy, "filled_quantity", None) or 0)
                            buy_notional = float(
                                getattr(buy, "filled_amount", None) or 0
                            )
                            if buy_notional <= 0 and entry_px and qty:
                                buy_notional = entry_px * qty
                    if exit_oid is not None:
                        sell = self._session.get(_TO, int(exit_oid))
                        if sell is not None:
                            sell_qty = float(
                                getattr(sell, "filled_quantity", None) or 0
                            )
                            if qty <= 0:
                                qty = sell_qty
                            sell_notional = float(
                                getattr(sell, "filled_amount", None) or 0
                            )
                            if (
                                sell_notional <= 0
                                and exit_px is not None
                                and qty > 0
                            ):
                                sell_notional = float(exit_px) * qty
                    # Upbit taker ~0.05% each side — fee 칼럼 없을 때 추정
                    fee_rate = 0.0005
                    fees = (buy_notional + sell_notional) * fee_rate
                    if (
                        exit_px is not None
                        and entry_px is not None
                        and qty > 0
                    ):
                        gross = (float(exit_px) - entry_px) * qty
                        net = gross - fees
                    elif sell_notional > 0 and buy_notional > 0:
                        gross = sell_notional - buy_notional
                        net = gross - fees
                    else:
                        net = -fees
                except Exception:  # noqa: BLE001
                    gross, fees, net = 0.0, 0.0, 0.0

                if exit_px is not None:
                    finalize_binding_on_close(
                        self._session,
                        binding_id=int(b.binding_id),
                        exit_reason=exit_reason,
                        exit_at=now,
                        exit_price=exit_px,
                    )
                    from stock_platform.operation.upbit_opportunity_shadow.trailing_forward_shadow.hooks import (
                        finalize_binding_on_close as finalize_trailing_shadow,
                    )

                    finalize_trailing_shadow(
                        self._session,
                        binding_id=int(b.binding_id),
                        exit_reason=exit_reason,
                        exit_at=now,
                        exit_price=exit_px,
                        entry_order_id=getattr(b, "entry_order_id", None),
                    )
                    try:
                        from stock_platform.operation.upbit_opportunity_shadow.exit_optimization_shadow_v3.hooks import (
                            finalize_binding_on_close as finalize_eosv3_shadow,
                        )

                        finalize_eosv3_shadow(
                            self._session,
                            binding_id=int(b.binding_id),
                            exit_reason=exit_reason,
                            exit_at=now,
                            exit_price=exit_px,
                            gross_pnl=gross,
                            fee=fees,
                            net_pnl=net,
                        )
                    except Exception:  # noqa: BLE001
                        pass
                    from stock_platform.operation.upbit_opportunity_shadow.exit_strategy_shadow.hooks import (
                        finalize_binding_on_close as finalize_exit_strategy_shadow,
                    )

                    finalize_exit_strategy_shadow(
                        self._session,
                        binding_id=int(b.binding_id),
                        entry_order_id=getattr(b, "entry_order_id", None),
                        exit_reason=exit_reason,
                        exit_at=now,
                        exit_price=exit_px,
                        exit_order_id=(
                            int(exit_oid) if exit_oid is not None else None
                        ),
                    )
                # Exit V4 / Profitability Lab: exit_px 없어도 baseline finalize
                # (CLOSED binding + canonical IDs만으로 deterministic)
                try:
                    from decimal import Decimal as _D

                    from stock_platform.operation.upbit_opportunity_shadow.profitability_improvement_shadow.hooks import (
                        finalize_binding_on_close as finalize_pislab_shadow,
                    )

                    hold_s = None
                    if b.opened_at is not None:
                        hold_s = (now - b.opened_at).total_seconds()
                    finalize_pislab_shadow(
                        self._session,
                        binding_id=int(b.binding_id),
                        exit_at=now,
                        exit_price=exit_px,
                        exit_reason=exit_reason,
                        gross_pnl=_D(str(round(gross, 4))),
                        fees=_D(str(round(fees, 4))),
                        net_pnl=_D(str(round(net, 4))),
                        hold_seconds=hold_s,
                    )
                except Exception:  # noqa: BLE001
                    pass
                try:
                    from stock_platform.operation.upbit_opportunity_shadow.reentry_cooldown_shadow.hooks import (
                        finalize_reentry_on_close,
                    )

                    finalize_reentry_on_close(
                        self._session,
                        entry_order_id=getattr(b, "entry_order_id", None),
                        user_broker_account_id=int(
                            b.user_broker_account_id
                        ),
                    )
                except Exception:  # noqa: BLE001
                    pass
                if exit_px is None:
                    # exit_px 없어도 trailing baseline ledger reconcile 시도
                    try:
                        from stock_platform.operation.upbit_opportunity_shadow.trailing_forward_shadow.hooks import (
                            finalize_binding_on_close as finalize_trailing_shadow,
                        )

                        finalize_trailing_shadow(
                            self._session,
                            binding_id=int(b.binding_id),
                            exit_reason=exit_reason,
                            exit_at=now,
                            exit_price=None,
                            entry_order_id=getattr(b, "entry_order_id", None),
                        )
                    except Exception:  # noqa: BLE001
                        pass
            except Exception:  # noqa: BLE001
                pass

        if is_full_market_portfolio(assignment.mode):
            from stock_platform.operation.upbit_full_market.constants import (
                SLOT_COOLDOWN,
                SLOT_EXIT_PENDING,
            )
            from stock_platform.operation.upbit_full_market.entities import (
                UpbitPositionSlotEntity,
                UpbitPortfolioPolicyEntity,
            )

            cool = cooldown_seconds
            if cool is None:
                policy = self._session.scalar(
                    select(UpbitPortfolioPolicyEntity).where(
                        UpbitPortfolioPolicyEntity.user_broker_account_id
                        == uba_id
                    )
                )
                cool = float(
                    getattr(policy, "entry_cooldown_seconds", None)
                    or getattr(
                        get_settings(),
                        "upbit_full_market_entry_cooldown_seconds",
                        300.0,
                    )
                )
            slot_q = select(UpbitPositionSlotEntity).where(
                UpbitPositionSlotEntity.user_broker_account_id == uba_id,
                UpbitPositionSlotEntity.status.in_(
                    [SLOT_OPEN, SLOT_EXIT_PENDING]
                ),
            )
            if symbol:
                slot_q = slot_q.where(
                    UpbitPositionSlotEntity.symbol == str(symbol).upper()
                )
            for slot in list(self._session.scalars(slot_q)):
                slot.status = SLOT_COOLDOWN
                slot.closed_at = now
                slot.cooldown_until = now + timedelta(seconds=float(cool))
                slot.reserved_amount_krw = None
                slot.version = int(slot.version or 1) + 1
            self._session.flush()
            return {
                "ok": True,
                "mode": assignment.mode,
                "closed_bindings": len(closed_bindings),
                "cooldown_seconds": float(cool),
            }

        if assignment.active_selection_id:
            sel = self._session.get(
                UpbitLiveCandidateSelectionEntity,
                int(assignment.active_selection_id),
            )
            if sel is not None:
                sel.status = SELECTION_STATUS_CLOSED

        cool = cooldown_seconds
        if cool is None:
            cool = float(
                getattr(
                    get_settings(),
                    "upbit_full_market_entry_cooldown_seconds",
                    300.0,
                )
            )
        assignment.state = STATE_POSITION_CLOSED
        assignment.cooldown_until = now + timedelta(seconds=float(cool))
        assignment.state = STATE_COOLDOWN
        assignment.active_selection_id = None
        assignment.warmup_ready = False
        assignment.market_data_fresh = False
        assignment.signals_paused = True
        self._session.flush()
        # cooldown 후 IDLE은 다음 consume/tick에서 처리
        return {
            "ok": True,
            "state": assignment.state,
            "cooldown_until": assignment.cooldown_until.isoformat(),
        }

    def tick_cooldown_to_idle(self, user_broker_account_id: int) -> dict[str, Any]:
        row = self.get_or_create(int(user_broker_account_id))
        now = _now()
        if row.state == STATE_COOLDOWN and (
            row.cooldown_until is None or row.cooldown_until <= now
        ):
            row.state = STATE_IDLE
            row.signals_paused = False
            row.block_reason = None
            self._session.flush()
        if is_full_market_portfolio(row.mode):
            from stock_platform.operation.upbit_full_market.portfolio_service import (
                UpbitPortfolioService,
            )

            UpbitPortfolioService(self._session).tick_cooldown_slots(
                int(user_broker_account_id)
            )
        return self.status_dict(int(user_broker_account_id))

    def entry_allowed(
        self, user_broker_account_id: int, *, symbol: str | None = None
    ) -> tuple[bool, str]:
        """신규 ENTRY fail-closed 게이트 (FULL_MARKET). FIXED는 항상 True(다른 게이트에 위임)."""

        row = self._session.scalar(
            select(UpbitFullMarketAssignmentEntity).where(
                UpbitFullMarketAssignmentEntity.user_broker_account_id
                == int(user_broker_account_id)
            )
        )
        if row is None or not is_any_full_market(row.mode):
            return True, "FIXED_SYMBOL_DELEGATE"

        if is_full_market_portfolio(row.mode):
            from stock_platform.operation.upbit_full_market.entities import (
                UpbitPortfolioPolicyEntity,
                UpbitPositionSlotEntity,
            )

            policy = self._session.scalar(
                select(UpbitPortfolioPolicyEntity).where(
                    UpbitPortfolioPolicyEntity.user_broker_account_id
                    == int(user_broker_account_id)
                )
            )
            if policy is None or not policy.enabled:
                return False, "PORTFOLIO_POLICY_DISABLED"
            if str(policy.entry_state or "") == PORTFOLIO_ENTRY_PAUSED:
                return False, "PORTFOLIO_ENTRY_PAUSED"
            if str(policy.entry_state or "") == "BLOCKED":
                return False, "PORTFOLIO_ENTRY_BLOCKED"
            if not symbol:
                return False, "SYMBOL_REQUIRED"
            slot = self._session.scalar(
                select(UpbitPositionSlotEntity).where(
                    UpbitPositionSlotEntity.user_broker_account_id
                    == int(user_broker_account_id),
                    UpbitPositionSlotEntity.symbol == str(symbol).upper(),
                    UpbitPositionSlotEntity.status.in_(
                        [
                            "WAITING_SIGNAL",
                            "ENTRY_PENDING",
                        ]
                    ),
                )
            )
            if slot is None:
                return False, "NO_WAITING_SIGNAL_SLOT"
            return True, "PORTFOLIO_PASS"

        if row.signals_paused:
            return False, "SIGNALS_PAUSED"
        if not row.warmup_ready:
            return False, "WARMUP_INCOMPLETE"
        if not row.market_data_fresh:
            return False, "MARKET_DATA_STALE"
        if row.state in {STATE_BLOCKED, STATE_COOLDOWN, STATE_WARMUP, STATE_SWITCH_PRECHECK}:
            return False, f"STATE_{row.state}"
        if row.cooldown_until and row.cooldown_until > _now():
            return False, "COOLDOWN_ACTIVE"
        if self.has_open_strategy_position(int(user_broker_account_id)):
            return False, "STRATEGY_POSITION_OPEN"
        if symbol and row.current_symbol and str(symbol).upper() != row.current_symbol:
            return False, "SYMBOL_NOT_ACTIVE_TARGET"
        return True, "PASS"

    def _has_preexisting_holding(self, uba_id: int, symbol: str) -> bool:
        """전략 바인딩 없이 스냅샷에 수량이 있으면 수동/기존 보유로 간주."""

        if self.is_strategy_owned_symbol(uba_id, symbol):
            return False
        try:
            from decimal import Decimal

            from stock_platform.broker.account_models import (
                BrokerPositionSnapshotEntity,
            )
            from stock_platform.broker.snapshot_constants import (
                BrokerSnapshotStatus,
            )

            qty = self._session.scalar(
                select(BrokerPositionSnapshotEntity.quantity).where(
                    BrokerPositionSnapshotEntity.user_broker_account_id
                    == uba_id,
                    BrokerPositionSnapshotEntity.broker_code == "UPBIT",
                    BrokerPositionSnapshotEntity.symbol == str(symbol).upper(),
                    BrokerPositionSnapshotEntity.snapshot_status
                    == BrokerSnapshotStatus.ACTIVE.value,
                )
            )
            if qty is None:
                return False
            return Decimal(str(qty)) > 0
        except Exception:  # noqa: BLE001
            return False
