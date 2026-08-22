"""FULL_MARKET_PORTFOLIO entry signal policy — CROSS_EVENT | BULLISH_STATE.

FIXED / FULL_MARKET_SINGLE 은 기본 CROSS_EVENT(MA_GOLDEN_CROSS) 유지.
Portfolio 모드에서만 DB policy(risk_group_policy_json) 또는 settings로
BULLISH_STATE 를 켠다.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from threading import Lock
from typing import Any

from stock_platform.operation.upbit_full_market.constants import (
    ALLOW_RECOMMENDATIONS,
)

POLICY_CROSS_EVENT = "CROSS_EVENT"
POLICY_BULLISH_STATE = "BULLISH_STATE"
# settings 하위호환 alias
POLICY_TREND_STATE = "TREND_STATE"

REASON_CROSS = "MA_GOLDEN_CROSS"
REASON_BULLISH = "PORTFOLIO_BULLISH_STATE_ENTRY"

_VALID = frozenset(
    {POLICY_CROSS_EVENT, POLICY_BULLISH_STATE, POLICY_TREND_STATE}
)


def normalize_entry_policy(raw: str | None) -> str:
    value = str(raw or POLICY_CROSS_EVENT).strip().upper()
    if value == POLICY_TREND_STATE:
        return POLICY_BULLISH_STATE
    if value not in _VALID:
        return POLICY_CROSS_EVENT
    return value


@dataclass(frozen=True, slots=True)
class PortfolioEntryThresholds:
    """BULLISH_STATE 필터 임계값 — scanner policy 재사용 우선."""

    rsi_max: float = 70.0
    min_volume_surge: float = 0.8
    min_ma_separation_pct: float = 0.05
    max_feed_age_seconds: float = 30.0
    max_candidate_age_seconds: float = 1800.0
    require_ai_allow: bool = True


@dataclass
class SymbolEntrySnapshot:
    """슬롯 후보 provenance (selection 시점) — tick마다 DB hit 금지용 캐시."""

    symbol: str
    selection_id: int | None = None
    selected_at: datetime | None = None
    ai_recommendation: str | None = None
    ai_confidence: float | None = None
    scanner_score: float | None = None
    rsi14: float | None = None
    volume_surge: float | None = None
    technical_metrics: dict[str, Any] = field(default_factory=dict)
    # WAITING_SIGNAL/ENTRY_PENDING 슬롯에 이미 배정된 후보 — scanner 신선도 만료로 BUY 영구 차단 금지
    bound_to_waiting_slot: bool = False


@dataclass
class PortfolioEntryContext:
    """Consumer에 부착하는 portfolio entry 컨텍스트."""

    user_broker_account_id: int
    policy: str = POLICY_CROSS_EVENT
    thresholds: PortfolioEntryThresholds = field(
        default_factory=PortfolioEntryThresholds
    )
    by_symbol: dict[str, SymbolEntrySnapshot] = field(default_factory=dict)
    refreshed_at: datetime | None = None


@dataclass
class EntryEvalRecord:
    last_evaluated_at: datetime | None = None
    evaluation_count: int = 0
    last_decision: str = "NONE"
    last_block_reason: str | None = None
    last_reason_code: str | None = None
    indicator_snapshot: dict[str, Any] = field(default_factory=dict)


def _latest_eval_store_path(uba_id: int) -> Path:
    """재시작 후에도 latest decision/reason 확인용 bounded JSON SoT."""

    root = Path(__file__).resolve().parents[4] / ".run"
    root.mkdir(parents=True, exist_ok=True)
    return root / f"uba_{int(uba_id)}_entry_eval_latest.json"


class PortfolioEntryTelemetry:
    """슬롯별 평가 요약 — 메모리 + decision 변경 시만 JSON persist."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._by_uba: dict[int, dict[str, EntryEvalRecord]] = {}

    def record(
        self,
        uba_id: int,
        symbol: str,
        *,
        decision: str,
        block_reason: str | None,
        reason_code: str | None,
        snapshot: dict[str, Any],
    ) -> None:
        now = datetime.now(timezone.utc)
        with self._lock:
            bucket = self._by_uba.setdefault(int(uba_id), {})
            row = bucket.setdefault(symbol.upper(), EntryEvalRecord())
            prev_decision = row.last_decision
            prev_reason = row.last_block_reason
            row.last_evaluated_at = now
            row.evaluation_count += 1
            row.last_decision = decision
            row.last_block_reason = block_reason
            row.last_reason_code = reason_code
            row.indicator_snapshot = dict(snapshot)
            # tick마다 쓰지 않고 decision/reason 변경 시에만 저장
            if (
                prev_decision != decision
                or prev_reason != block_reason
                or row.evaluation_count == 1
            ):
                self._persist_unlocked(int(uba_id))

    def _row_dict(self, row: EntryEvalRecord) -> dict[str, Any]:
        return {
            "last_evaluated_at": (
                row.last_evaluated_at.isoformat()
                if row.last_evaluated_at
                else None
            ),
            "evaluation_count": row.evaluation_count,
            "last_decision": row.last_decision,
            "last_block_reason": row.last_block_reason,
            "last_reason_code": row.last_reason_code,
            "indicator_snapshot": dict(row.indicator_snapshot),
        }

    def _persist_unlocked(self, uba_id: int) -> None:
        # 단위테스트가 운영 SoT 파일을 오염시키지 않도록 차단
        import os

        if os.environ.get("PYTEST_CURRENT_TEST"):
            return
        payload = {
            sym: self._row_dict(r)
            for sym, r in self._by_uba.get(int(uba_id), {}).items()
        }
        try:
            _latest_eval_store_path(uba_id).write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError:
            pass

    def _load_persisted(self, uba_id: int) -> dict[str, Any]:
        path = _latest_eval_store_path(uba_id)
        if not path.is_file():
            return {}
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            return raw if isinstance(raw, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def snapshot(self, uba_id: int | None = None) -> dict[str, Any]:
        with self._lock:
            if uba_id is None:
                return {
                    str(k): {
                        sym: self._row_dict(r) for sym, r in v.items()
                    }
                    for k, v in self._by_uba.items()
                }
            mem = {
                sym: self._row_dict(r)
                for sym, r in self._by_uba.get(int(uba_id), {}).items()
            }
            if mem:
                return mem
            return self._load_persisted(int(uba_id))


portfolio_entry_telemetry = PortfolioEntryTelemetry()


def build_portfolio_entry_context(
    session: Any,
    user_broker_account_id: int,
) -> PortfolioEntryContext:
    """DB에서 WAITING_SIGNAL 슬롯 selection provenance를 읽어 컨텍스트 구성."""

    from sqlalchemy import select

    from stock_platform.common.settings import get_settings
    from stock_platform.operation.upbit_full_market.constants import (
        SLOT_WAITING_SIGNAL,
        SLOT_ENTRY_PENDING,
    )
    from stock_platform.operation.upbit_full_market.entities import (
        UpbitLiveCandidateSelectionEntity,
        UpbitPortfolioPolicyEntity,
        UpbitPositionSlotEntity,
    )

    settings = get_settings()
    uba_id = int(user_broker_account_id)
    policy_row = session.scalar(
        select(UpbitPortfolioPolicyEntity).where(
            UpbitPortfolioPolicyEntity.user_broker_account_id == uba_id
        )
    )
    policy = resolve_policy_from_row(
        risk_group_policy_json=dict(
            (policy_row.risk_group_policy_json if policy_row else None) or {}
        ),
        settings_default=str(
            getattr(settings, "upbit_portfolio_entry_signal_policy", POLICY_CROSS_EVENT)
        ),
    )
    # candidate_max_age는 policy 행 우선 — UBA JSON이 entry 임계값 SoT
    cand_age = (
        int(policy_row.candidate_max_age_seconds)
        if policy_row is not None and policy_row.candidate_max_age_seconds
        else None
    )
    thresholds = load_thresholds_from_policy(
        settings=settings,
        risk_group_policy_json=dict(
            (policy_row.risk_group_policy_json if policy_row else None) or {}
        ),
        candidate_max_age_seconds=cand_age,
    )

    slots = list(
        session.scalars(
            select(UpbitPositionSlotEntity).where(
                UpbitPositionSlotEntity.user_broker_account_id == uba_id,
                UpbitPositionSlotEntity.status.in_(
                    [SLOT_WAITING_SIGNAL, SLOT_ENTRY_PENDING]
                ),
            )
        )
    )
    by_symbol: dict[str, SymbolEntrySnapshot] = {}
    for slot in slots:
        sym = str(slot.symbol or "").upper()
        if not sym:
            continue
        sel = None
        if slot.candidate_selection_id is not None:
            sel = session.get(
                UpbitLiveCandidateSelectionEntity,
                int(slot.candidate_selection_id),
            )
        tech = dict((sel.technical_metrics if sel else None) or {})
        rsi = tech.get("rsi14")
        surge = tech.get("volume_surge")
        try:
            rsi_f = float(rsi) if rsi is not None else None
        except (TypeError, ValueError):
            rsi_f = None
        try:
            surge_f = float(surge) if surge is not None else None
        except (TypeError, ValueError):
            surge_f = None
        rec = None
        conf = None
        score = None
        selected_at = None
        if sel is not None:
            rec = str(
                getattr(sel, "ai_recommendation", None)
                or getattr(sel, "recommendation", None)
                or ""
            ).upper() or None
            try:
                conf = (
                    float(sel.confidence)
                    if getattr(sel, "confidence", None) is not None
                    else None
                )
            except (TypeError, ValueError):
                conf = None
            try:
                score = float(sel.score) if sel.score is not None else None
            except (TypeError, ValueError):
                score = None
            selected_at = (
                getattr(sel, "selected_at", None)
                or getattr(sel, "created_at", None)
                or slot.updated_at
            )
        by_symbol[sym] = SymbolEntrySnapshot(
            symbol=sym,
            selection_id=(
                int(slot.candidate_selection_id)
                if slot.candidate_selection_id is not None
                else None
            ),
            selected_at=selected_at,
            ai_recommendation=rec,
            ai_confidence=conf,
            scanner_score=score,
            rsi14=rsi_f,
            volume_surge=surge_f,
            technical_metrics=tech,
            bound_to_waiting_slot=True,
        )

    return PortfolioEntryContext(
        user_broker_account_id=uba_id,
        policy=policy,
        thresholds=thresholds,
        by_symbol=by_symbol,
        refreshed_at=datetime.now(timezone.utc),
    )


def attach_portfolio_entry_context_to_hub(
    session: Any,
    user_broker_account_id: int,
) -> dict[str, Any]:
    """Hub consumer evaluator에 portfolio entry context 부착 + BULLISH config 보강."""

    from dataclasses import replace

    from stock_platform.realtime.market_data_hub import (
        get_realtime_market_data_hub,
    )

    ctx = build_portfolio_entry_context(session, user_broker_account_id)
    hub = get_realtime_market_data_hub()
    attached = 0
    config_patched = 0
    with hub.registry._lock:  # noqa: SLF001
        for consumer in hub.registry._by_scope.values():  # noqa: SLF001
            scope = consumer.scope
            if int(getattr(scope, "account_id", 0) or 0) != int(
                user_broker_account_id
            ):
                continue
            if str(getattr(scope, "broker_code", "") or "").upper() != "UPBIT":
                continue
            consumer.evaluator.portfolio_entry_ctx = ctx
            attached += 1
            # bridge 기본 CROSS_EVENT 방어: ctx 정책으로 portfolio_mode 강제
            old_cfg = consumer.evaluator.config
            new_policy = normalize_entry_policy(ctx.policy)
            if (
                not bool(old_cfg.portfolio_mode)
                or normalize_entry_policy(old_cfg.entry_signal_policy)
                != new_policy
            ):
                consumer.evaluator.config = replace(
                    old_cfg,
                    portfolio_mode=True,
                    entry_signal_policy=new_policy,
                )
                config_patched += 1
    return {
        "ok": True,
        "attached": attached,
        "config_patched": config_patched,
        "policy": ctx.policy,
        "symbols": sorted(ctx.by_symbol.keys()),
        "refreshed_at": (
            ctx.refreshed_at.isoformat() if ctx.refreshed_at else None
        ),
    }


def ensure_portfolio_entry_evaluator_for_uba(
    user_broker_account_id: int,
) -> dict[str, Any]:
    """Runtime sync/restore 후 portfolio entry ctx를 항상 재부착 (세션 단명)."""

    from stock_platform.database.session import get_session_factory
    from stock_platform.operation.upbit_full_market.constants import (
        is_full_market_portfolio,
    )
    from stock_platform.operation.upbit_full_market.entities import (
        UpbitFullMarketAssignmentEntity,
        UpbitPortfolioPolicyEntity,
    )
    from sqlalchemy import select

    uba_id = int(user_broker_account_id)
    sf = get_session_factory()
    with sf() as session:
        assignment = session.scalar(
            select(UpbitFullMarketAssignmentEntity).where(
                UpbitFullMarketAssignmentEntity.user_broker_account_id == uba_id
            )
        )
        if assignment is None or not is_full_market_portfolio(
            getattr(assignment, "mode", None)
        ):
            return {
                "ok": True,
                "skipped": True,
                "reason": "NOT_FULL_MARKET_PORTFOLIO",
            }
        policy = session.scalar(
            select(UpbitPortfolioPolicyEntity).where(
                UpbitPortfolioPolicyEntity.user_broker_account_id == uba_id
            )
        )
        if policy is not None and not bool(policy.enabled):
            return {
                "ok": True,
                "skipped": True,
                "reason": "PORTFOLIO_DISABLED",
            }
        result = attach_portfolio_entry_context_to_hub(session, uba_id)
        result["skipped"] = False
        return result


def load_thresholds_from_settings(settings: Any) -> PortfolioEntryThresholds:
    """settings + scanner RSI ideal_high 재사용."""

    try:
        from stock_platform.operation.upbit_opportunity_scanner.policy import (
            load_scanner_policy,
        )

        scanner = load_scanner_policy(settings)
        rsi_max = float(
            getattr(settings, "upbit_portfolio_entry_rsi_max", None)
            or getattr(scanner, "rsi_ideal_high", 70.0)
            or 70.0
        )
    except Exception:  # noqa: BLE001
        rsi_max = float(
            getattr(settings, "upbit_portfolio_entry_rsi_max", 70.0) or 70.0
        )

    return PortfolioEntryThresholds(
        rsi_max=rsi_max,
        min_volume_surge=float(
            getattr(settings, "upbit_portfolio_entry_min_volume_surge", 0.8)
            or 0.8
        ),
        min_ma_separation_pct=float(
            getattr(
                settings, "upbit_portfolio_entry_min_ma_separation_pct", 0.05
            )
            or 0.05
        ),
        max_feed_age_seconds=float(
            getattr(
                settings,
                "autotrading_market_feed_stale_seconds",
                30.0,
            )
            or 30.0
        ),
        max_candidate_age_seconds=float(
            getattr(
                settings,
                "upbit_portfolio_candidate_hold_seconds",
                1800.0,
            )
            or 1800.0
        ),
        require_ai_allow=bool(
            getattr(settings, "upbit_portfolio_entry_require_ai_allow", True)
        ),
    )


def load_thresholds_from_policy(
    *,
    settings: Any,
    risk_group_policy_json: dict[str, Any] | None,
    candidate_max_age_seconds: int | None = None,
) -> PortfolioEntryThresholds:
    """settings 기본 + operation.upbit_portfolio_policy.risk_group_policy_json 우선."""

    base = load_thresholds_from_settings(settings)
    blob = dict(risk_group_policy_json or {})

    def _float(key: str, default: float) -> float:
        raw = blob.get(key)
        if raw is None:
            return default
        try:
            return float(raw)
        except (TypeError, ValueError):
            return default

    cand_age = candidate_max_age_seconds
    if cand_age is None and blob.get("candidate_max_age_seconds") is not None:
        try:
            cand_age = int(blob["candidate_max_age_seconds"])
        except (TypeError, ValueError):
            cand_age = None

    require_ai = blob.get("require_ai_allow")
    if require_ai is None:
        require_ai = base.require_ai_allow
    else:
        require_ai = bool(require_ai)

    return PortfolioEntryThresholds(
        rsi_max=_float("rsi_max", base.rsi_max),
        min_volume_surge=_float("min_volume_surge", base.min_volume_surge),
        min_ma_separation_pct=_float(
            "min_ma_separation_pct", base.min_ma_separation_pct
        ),
        max_feed_age_seconds=base.max_feed_age_seconds,
        max_candidate_age_seconds=float(
            cand_age if cand_age is not None else base.max_candidate_age_seconds
        ),
        require_ai_allow=require_ai,
    )


def resolve_ma_windows_from_policy(
    *,
    risk_group_policy_json: dict[str, Any] | None,
    strategy_parameter_payload: dict[str, Any] | None = None,
) -> dict[str, int]:
    """UBA policy JSON > strategy parameter_payload > default 5/20."""

    blob = dict(risk_group_policy_json or {})
    payload = dict(strategy_parameter_payload or {})
    try:
        short = int(blob.get("short_ma_window") or payload.get("short_window") or 5)
    except (TypeError, ValueError):
        short = 5
    try:
        long = int(blob.get("long_ma_window") or payload.get("long_window") or 20)
    except (TypeError, ValueError):
        long = 20
    short = max(1, short)
    long = max(short + 1, long)
    return {"short_ma_window": short, "long_ma_window": long}


def resolve_policy_from_row(
    *,
    risk_group_policy_json: dict[str, Any] | None,
    settings_default: str,
) -> str:
    """DB policy JSON 우선, 없으면 settings 기본."""

    blob = dict(risk_group_policy_json or {})
    raw = blob.get("entry_signal_policy") or blob.get("entry_policy")
    if raw:
        return normalize_entry_policy(str(raw))
    return normalize_entry_policy(settings_default)


def evaluate_bullish_state_entry(
    *,
    short_ma: Decimal,
    long_ma: Decimal,
    event_time: datetime | None,
    now: datetime | None = None,
    snap: SymbolEntrySnapshot | None,
    thresholds: PortfolioEntryThresholds,
) -> tuple[bool, str | None, dict[str, Any]]:
    """BULLISH_STATE BUY 가능 여부. (ok, block_reason, snapshot)."""

    now = now or datetime.now(timezone.utc)
    gap_pct = float(
        ((short_ma - long_ma) / long_ma) * Decimal("100")
        if long_ma != 0
        else Decimal("0")
    )
    detail: dict[str, Any] = {
        "short_ma": str(short_ma),
        "long_ma": str(long_ma),
        "ma_gap_pct": gap_pct,
        "rsi14": snap.rsi14 if snap else None,
        "volume_surge": snap.volume_surge if snap else None,
        "ai_recommendation": snap.ai_recommendation if snap else None,
        "selected_at": (
            snap.selected_at.isoformat()
            if snap and snap.selected_at
            else None
        ),
    }

    if short_ma <= long_ma:
        return False, "SHORT_MA_NOT_ABOVE_LONG_MA", detail

    if gap_pct < float(thresholds.min_ma_separation_pct):
        return False, "MA_SEPARATION_TOO_SMALL", detail

    if event_time is not None:
        et = event_time
        if et.tzinfo is None:
            et = et.replace(tzinfo=timezone.utc)
        age = (now - et).total_seconds()
        detail["feed_age_seconds"] = age
        if age > float(thresholds.max_feed_age_seconds):
            return False, "FEED_STALE", detail

    if snap is None:
        return False, "NO_CANDIDATE_SNAPSHOT", detail

    # 슬롯에 이미 배정된 후보는 scanner age로 영구 BLOCK하지 않음
    # (BULLISH_STATE는 배정 후 MA/RSI 조건을 기다리는 모델)
    if snap.selected_at is not None and not bool(snap.bound_to_waiting_slot):
        sel = snap.selected_at
        if sel.tzinfo is None:
            sel = sel.replace(tzinfo=timezone.utc)
        cand_age = (now - sel).total_seconds()
        detail["candidate_age_seconds"] = cand_age
        if cand_age > float(thresholds.max_candidate_age_seconds):
            return False, "CANDIDATE_STALE", detail
    elif snap.selected_at is not None:
        sel = snap.selected_at
        if sel.tzinfo is None:
            sel = sel.replace(tzinfo=timezone.utc)
        detail["candidate_age_seconds"] = (now - sel).total_seconds()
        detail["candidate_age_gate"] = "SKIPPED_SLOT_BOUND"

    if thresholds.require_ai_allow:
        rec = str(snap.ai_recommendation or "").upper()
        if rec not in ALLOW_RECOMMENDATIONS:
            return False, "AI_SELECTION_NOT_ALLOW", detail

    if snap.rsi14 is not None and float(snap.rsi14) > float(thresholds.rsi_max):
        detail["rsi_max"] = thresholds.rsi_max
        return False, "RSI_TOO_HIGH", detail

    if (
        snap.volume_surge is not None
        and float(snap.volume_surge) < float(thresholds.min_volume_surge)
    ):
        detail["min_volume_surge"] = thresholds.min_volume_surge
        return False, "VOLUME_SURGE_TOO_LOW", detail

    return True, None, detail
