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
    SELECTION_STATUS_ACTIVE,
    SELECTION_STATUS_CLOSED,
    SELECTION_STATUS_SELECTED,
    SELECTION_STATUS_SUPERSEDED,
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
                "warmup_ready": False,
                "market_data_fresh": False,
                "cooldown_until": None,
                "block_reason": None,
                "active_selection_id": None,
                "ai_live_gate_mode": AI_GATE_ENFORCE,
            }
        return {
            "assignment_id": int(row.assignment_id),
            "mode": row.mode,
            "state": row.state,
            "current_symbol": row.current_symbol,
            "template_symbol": row.template_symbol,
            "full_market_enabled": row.mode == MODE_FULL_MARKET_AUTO,
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
        if row is None or row.mode != MODE_FULL_MARKET_AUTO:
            return (fallback_symbol or None) and str(fallback_symbol).upper()
        if row.current_symbol:
            return str(row.current_symbol).upper()
        return (row.template_symbol or fallback_symbol or None) and str(
            row.current_symbol or row.template_symbol or fallback_symbol
        ).upper()

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

        if assignment.mode != MODE_FULL_MARKET_AUTO:
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
        if row.warmup_ready and row.market_data_fresh and row.mode == MODE_FULL_MARKET_AUTO:
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
    ) -> dict[str, Any]:
        uba_id = int(user_broker_account_id)
        sym = str(symbol).upper()
        assignment = self.get_or_create(uba_id)
        if assignment.mode != MODE_FULL_MARKET_AUTO:
            return {"ok": False, "reason": "MODE_FIXED_SYMBOL"}
        binding = UpbitStrategyPositionBindingEntity(
            user_broker_account_id=uba_id,
            strategy_id=assignment.strategy_id,
            deployment_id=assignment.deployment_id,
            selection_id=selection_id or assignment.active_selection_id,
            symbol=sym,
            status=BINDING_STATUS_OPEN,
            entry_order_id=entry_order_id,
            opened_at=_now(),
            meta_json={},
        )
        self._session.add(binding)
        assignment.state = STATE_POSITION_OPEN
        assignment.current_symbol = sym
        self._session.flush()
        return {"ok": True, "binding_id": int(binding.binding_id)}

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
        for b in list(self._session.scalars(q)):
            b.status = BINDING_STATUS_CLOSED
            b.closed_at = now

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
        if row is None or row.mode != MODE_FULL_MARKET_AUTO:
            return True, "FIXED_SYMBOL_DELEGATE"
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
