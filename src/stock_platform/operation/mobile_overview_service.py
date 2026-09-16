# -*- coding: utf-8 -*-
"""Mobile PWA V1 — READ-ONLY overview aggregate.

기존 SoT 재사용: UBA ops summary, ops dashboard, autotrading performance, dual LLM.
POST/PUT/PATCH/DELETE 없음. secret/credential 미포함.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from stock_platform.common.settings import get_settings
from stock_platform.common.ttl_cache import process_ttl_cache
from stock_platform.operation.autotrading_performance_service import (
    AutotradingPerformanceService,
)
from stock_platform.operation.db_pool_monitor import measure_db_latency_ms
from stock_platform.operation.ops_monitoring.service import (
    OpsMonitoringDashboardService,
)
from stock_platform.operation.upbit_market_context.dual_llm_runtime import (
    analysis_config,
    teacher_config,
    trading_config,
)
from stock_platform.order.entities import TradingOrderEntity
from stock_platform.risk_engine.kill_switch_service import KillSwitchService
from stock_platform.trading.uba_operational_summary import (
    build_uba_operational_summary,
)

_KST = ZoneInfo("Asia/Seoul")
_CACHE_KEY = "mobile:overview:v3"
_CACHE_TTL = 8.0

# FE dashboard 와 동일 기본 UBA
_DEFAULT_UPBIT_UBA = 1380
_DEFAULT_KIWOOM_UBA = 1381
_CLEAN_TARGET = 500


def _dec(v: Any) -> float | None:
    if v is None or v == "":
        return None
    try:
        return float(Decimal(str(v)))
    except Exception:  # noqa: BLE001
        return None


def _today_start_kst() -> datetime:
    now = datetime.now(_KST)
    start = datetime(now.year, now.month, now.day, tzinfo=_KST)
    return start.astimezone(timezone.utc)


def _side_counts(
    session: Session, *, uba_id: int, since: datetime
) -> dict[str, int]:
    buy = sell = fill = 0
    rows = session.scalars(
        select(TradingOrderEntity).where(
            and_(
                TradingOrderEntity.user_broker_account_id == int(uba_id),
                TradingOrderEntity.created_at >= since,
            )
        )
    )
    for o in rows:
        side = str(getattr(o, "side_code", "") or "").upper()
        if side in {"BUY", "BID"}:
            buy += 1
        elif side in {"SELL", "ASK"}:
            sell += 1
        st = str(getattr(o, "status_code", "") or "").upper()
        if st in {"FILLED", "DONE", "COMPLETED", "PARTIALLY_FILLED"}:
            fill += 1
    return {"auto_buy_count": buy, "auto_sell_count": sell, "fill_count": fill}


def _broker_card(ops: dict[str, Any], *, side: dict[str, int]) -> dict[str, Any]:
    feed = ops.get("market_feed") if isinstance(ops.get("market_feed"), dict) else {}
    scanner = ops.get("scanner") if isinstance(ops.get("scanner"), dict) else {}
    live = str(ops.get("live") or "OFF").upper() == "ON"
    arm = str(ops.get("arm") or "OFF").upper() == "ON"
    runtime = str(ops.get("runtime") or "STOPPED").upper()
    auto_state = str(ops.get("auto_trading_state") or "STOPPED").upper()
    can_auto = (
        live
        and arm
        and auto_state == "RUNNING"
        and "KILL_SWITCH_ACTIVE" not in (ops.get("blockers") or [])
    )
    market_status = None
    broker = str(ops.get("broker_code") or "").upper()
    if broker == "UPBIT":
        market_status = "OPEN_24H"
    elif broker == "KIWOOM":
        # 장 세션 상세는 별도 calendar — 없으면 ops 기반 추정만
        market_status = "UNKNOWN"

    rel = ops.get("reliability") if isinstance(ops.get("reliability"), dict) else {}
    sem = ops.get("operational_semantics") if isinstance(
        ops.get("operational_semantics"), dict
    ) else rel.get("operational_semantics") if isinstance(
        rel.get("operational_semantics"), dict
    ) else {}
    op_tier = str(sem.get("operational_tier") or "").upper()
    health_state = str(rel.get("health_state") or "").upper()
    no_trade = str(rel.get("no_trade_classification") or "")
    display_status = "정상"
    if op_tier == "ENTRY_RESTRICTED":
        display_status = "청산체결대기"
    elif op_tier == "SYSTEM_BLOCKED" or health_state == "BROKEN" or rel.get(
        "partial_restore"
    ):
        display_status = "장애"
    elif no_trade == "WAITING_SLOT_STARVATION":
        display_status = "슬롯대기정체"
    elif no_trade == "PIPELINE_STALL" and rel.get("waiting_starvation", {}).get(
        "waiting_slot_starvation"
    ):
        display_status = "슬롯대기정체"
    elif no_trade == "NORMAL_NO_SIGNAL":
        display_status = "신호대기"
    elif no_trade == "NORMAL_POLICY_BLOCK":
        display_status = "정책대기"
    elif health_state == "DEGRADED":
        display_status = "확인필요"
    elif broker == "KIWOOM" and market_status == "UNKNOWN":
        display_status = "장마감"

    return {
        "uba_id": ops.get("user_broker_account_id"),
        "broker_code": broker or None,
        "market_status": market_status,
        "health_display": display_status,
        "health_state": health_state or None,
        "partial_restore": bool(rel.get("partial_restore")),
        "no_trade_classification": no_trade or None,
        "first_zero_stage": rel.get("first_zero_stage"),
        "auto_trading_ready": rel.get("auto_trading_ready"),
        "live": live,
        "arm": arm,
        "runtime": runtime,
        "runner": str(ops.get("runner") or "STOPPED").upper(),
        "worker": str(ops.get("outbox_worker") or "STOPPED").upper(),
        "exit_monitor": str(ops.get("exit_monitor") or "STOPPED").upper(),
        "scanner": (
            "RUNNING"
            if scanner.get("running") is True
            else ("STOPPED" if scanner else "UNKNOWN")
        ),
        "feed": str(feed.get("status") or "UNKNOWN").upper(),
        "auto_trading_state": auto_state,
        "can_auto_trade": can_auto,
        "operational_tier": sem.get("operational_tier"),
        "operational_label_ko": sem.get("operational_label_ko"),
        "entry_restricted": bool(sem.get("entry_restricted")),
        "system_blocked": bool(sem.get("system_blocked")),
        "blockers": list(ops.get("blockers") or [])[:8],
        "warnings": list(ops.get("warnings") or [])[:8],
        "today_buy_count": int(side.get("auto_buy_count") or 0),
        "today_sell_count": int(side.get("auto_sell_count") or 0),
        "today_fill_count": int(side.get("fill_count") or 0),
    }


def _overall_tone(
    *,
    kill_active: bool,
    upbit: dict[str, Any],
    kiwoom: dict[str, Any],
) -> str:
    if kill_active:
        return "STOPPED"
    u_state = str(upbit.get("auto_trading_state") or "")
    if u_state == "RUNNING" and upbit.get("can_auto_trade"):
        return "HEALTHY"
    if u_state in {"DEGRADED", "WAITING_SIGNAL"} or upbit.get("warnings"):
        return "ATTENTION"
    if u_state in {"STOPPED", "BLOCKED"} and not upbit.get("live"):
        # UPBIT 중지 + KIWOOM도 중지면 STOPPED
        if str(kiwoom.get("auto_trading_state") or "") in {"STOPPED", "BLOCKED", ""}:
            return "STOPPED"
        return "ATTENTION"
    return "ATTENTION"


def _slim_position(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "symbol": item.get("symbol") or item.get("market"),
        "market": item.get("broker_code"),
        "uba_id": item.get("user_broker_account_id"),
        "quantity": item.get("quantity"),
        "entry": item.get("average_price"),
        "current": item.get("current_price"),
        "pnl": item.get("unrealized_pnl"),
        "stale": bool(item.get("stale")),
    }


def _slim_order(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "created_at": item.get("created_at"),
        "broker_code": item.get("broker_code"),
        "symbol": item.get("market"),
        "side": item.get("side"),
        "status": item.get("internal_status"),
        "price": item.get("requested_price"),
        "quantity": item.get("requested_quantity"),
        "order_id": item.get("order_id"),
    }


def _slim_alert(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "severity": item.get("severity") or item.get("level"),
        "code": item.get("code") or item.get("reason_code"),
        "title": item.get("title") or item.get("message"),
        "message": item.get("detail") or item.get("message"),
        "created_at": item.get("created_at") or item.get("checked_at"),
    }


def build_mobile_overview(session: Session) -> dict[str, Any]:
    """집계 본문 — 캐시 없이 계산."""

    settings = get_settings()
    upbit_uba = int(
        getattr(settings, "mobile_default_upbit_uba_id", None) or _DEFAULT_UPBIT_UBA
    )
    kiwoom_uba = int(
        getattr(settings, "mobile_default_kiwoom_uba_id", None) or _DEFAULT_KIWOOM_UBA
    )
    since = _today_start_kst()
    checked_at = datetime.now(timezone.utc)

    db_status, latency_ms, db_err = measure_db_latency_ms()
    try:
        kill = KillSwitchService(session).get_state()
        from stock_platform.risk_engine.kill_switch_models import KillSwitchStatus

        kill_active = kill.status == KillSwitchStatus.ACTIVE
    except Exception:  # noqa: BLE001
        try:
            kill_active = bool(KillSwitchService(session).is_active())
        except Exception:  # noqa: BLE001
            kill_active = False

    upbit_ops = build_uba_operational_summary(
        session, user_broker_account_id=upbit_uba
    )
    kiwoom_ops = build_uba_operational_summary(
        session, user_broker_account_id=kiwoom_uba
    )
    upbit_sides = _side_counts(session, uba_id=upbit_uba, since=since)
    kiwoom_sides = _side_counts(session, uba_id=kiwoom_uba, since=since)
    upbit_card = _broker_card(upbit_ops, side=upbit_sides)
    kiwoom_card = _broker_card(kiwoom_ops, side=kiwoom_sides)

    ops_svc = OpsMonitoringDashboardService(session)
    # overview는 무거울 수 있어 system 최소 필드만 직접 구성
    sched_ok = True
    try:
        ov = ops_svc.overview()
        sched = ov.get("scheduler") if isinstance(ov, dict) else {}
        worker = ov.get("worker") if isinstance(ov, dict) else {}
        overall = ov.get("overall_status") if isinstance(ov, dict) else None
    except Exception:  # noqa: BLE001
        ov = {}
        sched = {}
        worker = {}
        overall = None
        sched_ok = False

    pos_raw = ops_svc.positions()
    positions = [
        _slim_position(p)
        for p in (pos_raw.get("positions") or [])
        if isinstance(p, dict)
    ][:5]

    ord_raw = ops_svc.orders(limit=8, offset=0, sort="created_at")
    recent_orders = [
        _slim_order(o)
        for o in (ord_raw.get("items") or ord_raw.get("orders") or [])
        if isinstance(o, dict)
    ][:8]

    alert_raw = ops_svc.alerts(limit=5)
    recent_events = [
        _slim_alert(a)
        for a in (alert_raw.get("items") or alert_raw.get("alerts") or [])
        if isinstance(a, dict)
    ][:5]

    # Today PnL — AUTO strategy-owned SoT
    perf_all = AutotradingPerformanceService(session).build(
        broker="ALL", period="TODAY", include_ops=False
    )
    summary = (
        perf_all.get("summary") if isinstance(perf_all.get("summary"), dict) else {}
    )
    by_broker: dict[str, Any] = {}
    try:
        for code in ("UPBIT", "KIWOOM"):
            p = AutotradingPerformanceService(session).build(
                broker=code, period="TODAY", include_ops=False
            )
            s = p.get("summary") if isinstance(p.get("summary"), dict) else {}
            by_broker[code] = {
                "realized_pnl": _dec(s.get("today_realized_pnl") or s.get("period_realized_pnl")),
                "unrealized_pnl": _dec(s.get("current_unrealized_pnl")),
            }
    except Exception:  # noqa: BLE001
        by_broker = {}

    realized = _dec(summary.get("today_realized_pnl") or summary.get("period_realized_pnl"))
    unrealized = _dec(summary.get("current_unrealized_pnl"))
    total = None
    if realized is not None or unrealized is not None:
        total = float(realized or 0) + float(unrealized or 0)

    activity = (
        perf_all.get("today_order_activity")
        if isinstance(perf_all.get("today_order_activity"), dict)
        else {}
    )
    # 평균 보유시간 초 → 표시용 분/초는 FE에서 포맷
    avg_hold_sec = summary.get("today_avg_hold_sec")
    try:
        avg_hold_sec_i = int(avg_hold_sec) if avg_hold_sec is not None else None
    except (TypeError, ValueError):
        avg_hold_sec_i = None

    a_cfg = analysis_config()
    t_cfg = trading_config()
    te_cfg = teacher_config()
    clean_count = None
    sample_stage = None
    try:
        from stock_platform.operation.upbit_opportunity_shadow.entities import (
            UpbitOpportunityShadowEntity,
        )
        from stock_platform.operation.upbit_opportunity_shadow.constants import (
            SHADOW_STATUS_COMPLETED,
        )
        from stock_platform.operation.upbit_opportunity_shadow.clean_forward_research import (
            assign_clean_forward_obs,
        )
        from stock_platform.operation.upbit_market_context.learning_dataset import (
            sample_stage as calc_stage,
        )

        completed = list(
            session.scalars(
                select(UpbitOpportunityShadowEntity).where(
                    UpbitOpportunityShadowEntity.deleted_at.is_(None),
                    UpbitOpportunityShadowEntity.status == SHADOW_STATUS_COMPLETED,
                )
            )
        )
        clean_n = len(assign_clean_forward_obs(completed))
        clean_count = clean_n
        st = calc_stage(clean_n)
        sample_stage = st.get("stage") if isinstance(st, dict) else st
    except Exception:  # noqa: BLE001
        clean_count = None
        sample_stage = None

    system_status = str(overall or ("HEALTHY" if db_status == "UP" else "DEGRADED"))
    tone = _overall_tone(
        kill_active=kill_active, upbit=upbit_card, kiwoom=kiwoom_card
    )

    # 사용자용 Why No Trade (raw JSON 비노출 — 요약 필드만)
    why_no_trade: dict[str, Any] = {
        "trade_ready": bool(upbit_card.get("auto_trading_ready")),
        "trade_running": str(upbit_card.get("auto_trading_state") or "").upper()
        == "RUNNING",
        "no_trade_reason_code": None,
        "no_trade_reason_text": None,
        "last_entry_signal_at": None,
        "last_order_at": None,
        "uba_id": upbit_uba,
        "broker_code": "UPBIT",
    }
    try:
        from stock_platform.trading.pipeline_liveness_service import (
            build_pipeline_liveness_snapshot,
        )

        live_snap = build_pipeline_liveness_snapshot(
            session, user_broker_account_id=upbit_uba
        )
        why_no_trade["trade_ready"] = bool(
            live_snap.get("auto_trading_ready", why_no_trade["trade_ready"])
        )
        why_no_trade["no_trade_reason_code"] = (
            live_snap.get("classification")
            or live_snap.get("first_zero_stage")
            or upbit_card.get("no_trade_classification")
        )
        why_no_trade["no_trade_reason_text"] = (
            live_snap.get("user_friendly_reason")
            or live_snap.get("user_status")
            or upbit_card.get("operational_label_ko")
        )
        last_trade = live_snap.get("last_trade") if isinstance(live_snap.get("last_trade"), dict) else {}
        why_no_trade["last_order_at"] = live_snap.get("last_trade_at") or last_trade.get(
            "at"
        )
        # ENTRY 신호 시각 — heartbeat/funnel 없으면 None 유지
        for hb in live_snap.get("stage_heartbeats") or []:
            if not isinstance(hb, dict):
                continue
            if str(hb.get("stage") or "") in {"entry_pass", "entry_evaluation", "selection"}:
                if hb.get("last_at"):
                    why_no_trade["last_entry_signal_at"] = hb.get("last_at")
                    break
    except Exception:  # noqa: BLE001
        why_no_trade["no_trade_reason_code"] = upbit_card.get("no_trade_classification")
        why_no_trade["no_trade_reason_text"] = upbit_card.get("operational_label_ko")

    return {
        "schema": "mobile_overview_v2",
        "updated_at": checked_at.isoformat(),
        "overall": {
            "status": tone,
            "label_hint": {
                "HEALTHY": "정상 운영",
                "ATTENTION": "확인 필요",
                "STOPPED": "자동매매 중지",
            }.get(tone, "확인 필요"),
        },
        "why_no_trade": why_no_trade,
        "system": {
            "status": system_status,
            "backend": "UP",
            "database": "HEALTHY" if db_status == "UP" else "ERROR",
            "database_latency_ms": latency_ms,
            "database_detail": db_err,
            "worker": (
                str((worker or {}).get("status") or "UNKNOWN")
                if isinstance(worker, dict)
                else "UNKNOWN"
            ),
            "scheduler": (
                str((sched or {}).get("status") or ("OK" if sched_ok else "UNKNOWN"))
                if isinstance(sched, dict)
                else ("OK" if sched_ok else "UNKNOWN")
            ),
            "kill_switch": kill_active,
            "blockers": list(upbit_card.get("blockers") or [])[:5],
        },
        "upbit": upbit_card,
        "kiwoom": kiwoom_card,
        "today": {
            "realized_pnl": realized,
            "unrealized_pnl": unrealized,
            "total_pnl": total,
            # 오늘 손익 분해 (손익−손실−수수료 = realized_pnl)
            "profit_amount": _dec(summary.get("today_profit_amount")),
            "loss_amount": _dec(summary.get("today_loss_amount")),
            "fees": _dec(summary.get("today_fees")),
            "win_rate_pct": _dec(summary.get("today_win_rate_pct")),
            "closed_trade_count": int(summary.get("today_closed_trade_count") or 0),
            "symbol_count": int(summary.get("today_symbol_count") or 0),
            "avg_hold_sec": avg_hold_sec_i,
            # 총손익 = 자동매매 전체 거래 실현 순손익
            "cumulative_realized_pnl": _dec(summary.get("cumulative_realized_pnl")),
            "buy_count": int(activity.get("buy_count") or 0),
            "sell_count": int(activity.get("sell_count") or 0),
            "filled_count": int(activity.get("filled_count") or 0),
            "open_count": int(activity.get("open_count") or 0),
            "cancelled_count": int(activity.get("cancelled_count") or 0),
            "buy_amount": _dec(activity.get("buy_amount")),
            "sell_amount": _dec(activity.get("sell_amount")),
            "auto_buy_count": upbit_sides["auto_buy_count"]
            + kiwoom_sides["auto_buy_count"],
            "auto_sell_count": upbit_sides["auto_sell_count"]
            + kiwoom_sides["auto_sell_count"],
            "fill_count": upbit_sides["fill_count"] + kiwoom_sides["fill_count"],
            "by_broker": by_broker,
        },
        "positions": {
            "count": int(pos_raw.get("count") or len(positions)),
            "items": positions,
        },
        "recent_orders": recent_orders,
        "recent_events": recent_events,
        "ai": {
            "analysis_model": a_cfg.model,
            "trading_model": t_cfg.model,
            "teacher_model": te_cfg.model,
            "trading_mode": "SHADOW",
            "clean_count": clean_count,
            "clean_target": _CLEAN_TARGET,
            "sample_stage": sample_stage,
            "rag_label": "수집 중" if (clean_count or 0) < _CLEAN_TARGET else "표본 축적",
        },
    }


def get_mobile_overview_cached(session: Session) -> dict[str, Any]:
    """짧은 TTL 캐시 — 모바일 폴링용. mutation 없음."""

    def _build() -> dict[str, Any]:
        return build_mobile_overview(session)

    return process_ttl_cache.get_or_set(
        _CACHE_KEY,
        _build,
        ttl_seconds=_CACHE_TTL,
    )
