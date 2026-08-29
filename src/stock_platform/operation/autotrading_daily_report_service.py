# -*- coding: utf-8 -*-
"""자동매매 일일 운영보고 — READ ONLY 집계 (REAL decision 무영향)."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Literal
from zoneinfo import ZoneInfo

from sqlalchemy import and_, select, text
from sqlalchemy.orm import Session

from stock_platform.common.settings import get_settings
from stock_platform.operation.autotrading_performance_service import (
    AutotradingPerformanceService,
)
from stock_platform.operation.autotrading_research.status import (
    build_cross_market_research_status_for_daily_report,
)
from stock_platform.order.entities import TradingOrderEntity
from stock_platform.trading.autotrading_data_trust import current_data_trust_summary
from stock_platform.trading.uba_operational_summary import (
    build_uba_daily_report_ops_projection,
)
_KST = ZoneInfo("Asia/Seoul")
MarketFilter = Literal["ALL", "UPBIT", "KIWOOM"]

_DEFAULT_UPBIT_UBA = 1380
_DEFAULT_KIWOOM_UBA = 1381

_HEALTH_LABEL = {
    "GREEN": "🟢 정상",
    "YELLOW": "🟡 정상 대기",
    "ORANGE": "🟠 확인 필요",
    "RED": "🔴 장애",
}


def _kst_day_bounds(report_date: date) -> tuple[datetime, datetime]:
    start = datetime(
        report_date.year, report_date.month, report_date.day, tzinfo=_KST
    )
    end = start + timedelta(days=1)
    return start.astimezone(timezone.utc), end.astimezone(timezone.utc)


def _dec(v: Any) -> float:
    if v is None or v == "":
        return 0.0
    try:
        return float(Decimal(str(v)))
    except Exception:  # noqa: BLE001
        return 0.0


def _order_day_stats(
    session: Session,
    *,
    uba_id: int,
    start_utc: datetime,
    end_utc: datetime,
) -> dict[str, Any]:
    buy = sell = buy_fill = sell_fill = 0
    buy_amount = sell_amount = 0.0
    last_order_at: datetime | None = None
    last_fill_at: datetime | None = None
    last_order: dict[str, Any] | None = None
    last_fill: dict[str, Any] | None = None

    rows = session.scalars(
        select(TradingOrderEntity)
        .where(
            and_(
                TradingOrderEntity.user_broker_account_id == int(uba_id),
                TradingOrderEntity.created_at >= start_utc,
                TradingOrderEntity.created_at < end_utc,
            )
        )
        .order_by(TradingOrderEntity.created_at.desc())
    ).all()

    for order in rows:
        side = str(getattr(order, "side_code", "") or "").upper()
        st = str(getattr(order, "status_code", "") or "").upper()
        amt = _dec(getattr(order, "requested_amount", None))
        if side in {"BUY", "BID"}:
            buy += 1
            buy_amount += amt
        elif side in {"SELL", "ASK"}:
            sell += 1
            sell_amount += amt
        filled = st in {"FILLED", "DONE", "COMPLETED", "PARTIALLY_FILLED"}
        if filled:
            if side in {"BUY", "BID"}:
                buy_fill += 1
            elif side in {"SELL", "ASK"}:
                sell_fill += 1
            if last_fill_at is None:
                last_fill_at = order.created_at
                last_fill = {
                    "order_id": int(order.order_id),
                    "symbol": getattr(order, "symbol", None),
                    "side": side,
                    "status": st,
                    "created_at": order.created_at.isoformat()
                    if order.created_at
                    else None,
                }
        if last_order_at is None:
            last_order_at = order.created_at
            last_order = {
                "order_id": int(order.order_id),
                "symbol": getattr(order, "symbol", None),
                "side": side,
                "status": st,
                "created_at": order.created_at.isoformat()
                if order.created_at
                else None,
            }

    return {
        "buy_order_count": buy,
        "sell_order_count": sell,
        "buy_fill_count": buy_fill,
        "sell_fill_count": sell_fill,
        "buy_amount": round(buy_amount, 2),
        "sell_amount": round(sell_amount, 2),
        "last_order": last_order,
        "last_fill": last_fill,
    }


def _pipeline_unique_stages(
    session: Session,
    *,
    uba_id: int,
    start_utc: datetime,
    end_utc: datetime,
) -> dict[str, int]:
    """UPBIT entry trace — selection_id 기준 unique stage count (당일).

    기존 8회 COUNT DISTINCT → FILTER 집계 1회 (결과 equivalence 유지).
    """

    row = session.execute(
        text(
            """
            SELECT
              COUNT(DISTINCT selection_id) FILTER (
                WHERE stage = 'ENTRY_PASS'
              ) AS entry_pass,
              COUNT(DISTINCT selection_id) FILTER (
                WHERE stage = 'SIGNAL_EMITTED'
              ) AS signal_emitted,
              COUNT(DISTINCT selection_id) FILTER (
                WHERE stage = 'EXECUTOR_RECEIVED'
              ) AS executor_received,
              COUNT(DISTINCT selection_id) FILTER (
                WHERE stage = 'BEGIN_ENTRY_ACCEPTED'
              ) AS begin_entry_accepted,
              COUNT(DISTINCT selection_id) FILTER (
                WHERE stage IN ('ORDER_CREATED', 'ADMISSION_PASS')
              ) AS order_stage,
              COUNT(DISTINCT selection_id) FILTER (
                WHERE stage IN ('FILL', 'ORDER_FILLED')
              ) AS fill_stage
            FROM operation.upbit_entry_execution_trace
            WHERE user_broker_account_id = :uba
              AND created_at >= :start_utc AND created_at < :end_utc
              AND selection_id IS NOT NULL
              AND stage IN (
                'ENTRY_PASS',
                'SIGNAL_EMITTED',
                'EXECUTOR_RECEIVED',
                'BEGIN_ENTRY_ACCEPTED',
                'ORDER_CREATED',
                'ADMISSION_PASS',
                'FILL',
                'ORDER_FILLED'
              )
            """
        ),
        {"uba": int(uba_id), "start_utc": start_utc, "end_utc": end_utc},
    ).mappings().first()
    entry_pass = int((row or {}).get("entry_pass") or 0)
    return {
        "CANDIDATE": entry_pass,
        "AI_ALLOW": entry_pass,
        "TECHNICAL_PASS": entry_pass,
        "SIGNAL_EMITTED": int((row or {}).get("signal_emitted") or 0),
        "EXECUTOR_RECEIVED": int((row or {}).get("executor_received") or 0),
        "BEGIN_ENTRY_ACCEPTED": int((row or {}).get("begin_entry_accepted") or 0),
        "ORDER": int((row or {}).get("order_stage") or 0),
        "FILL": int((row or {}).get("fill_stage") or 0),
    }


def _is_kiwoom_expected_post_close(ops: dict[str, Any]) -> bool:
    """KRX 장종료 + LIVE OFF + Feed DISCONNECTED = 정상 장후 상태."""

    phase = str(
        ops.get("krx_session_phase") or ops.get("market_session") or ""
    ).upper()
    live = str(ops.get("live") or "").upper()
    feed = str((ops.get("market_feed") or {}).get("status") or "").upper()
    rel = ops.get("reliability") if isinstance(ops.get("reliability"), dict) else {}
    funnel = ops.get("kiwoom_funnel") if isinstance(ops.get("kiwoom_funnel"), dict) else {}
    if not funnel:
        funnel = rel.get("kiwoom_funnel") if isinstance(rel.get("kiwoom_funnel"), dict) else {}
    if str(funnel.get("FIRST_ZERO_STAGE") or funnel.get("first_zero_stage") or "").upper() == "MARKET_CLOSED":
        return True
    if phase in {"CLOSED", "AFTER", "HOLIDAY", "POST_CLOSE"} or "CLOSE" in phase:
        return live == "OFF" and feed in {"DISCONNECTED", "REAL_IDLE", "IDLE"}
    return False


def _incidents_active(
    session: Session,
    *,
    market: str | None = None,
) -> list[dict[str, Any]]:
    """미복구 incident — overall health 판정용."""

    params: dict[str, Any] = {}
    market_clause = ""
    if market:
        params["market"] = str(market).upper()
        market_clause = "AND market = :market"
    rows = session.execute(
        text(
            f"""
            SELECT incident_id, market, uba_id, signature, classification,
                   first_zero_stage, root_cause, started_at, recovered_at,
                   self_heal_level
            FROM operation.autotrading_incident_ledger
            WHERE recovered_at IS NULL
            {market_clause}
            ORDER BY started_at ASC
            """
        ),
        params,
    ).mappings().all()
    return [_incident_row_to_dict(row) for row in rows]


def _incident_row_to_dict(row: Any) -> dict[str, Any]:
    started = row.get("started_at")
    recovered = row.get("recovered_at")
    return {
        "incident_id": int(row["incident_id"]),
        "market": row.get("market"),
        "signature": row.get("signature"),
        "classification": row.get("classification"),
        "started_at": started.isoformat() if started else None,
        "recovered_at": recovered.isoformat() if recovered else None,
        "recovered": recovered is not None,
        "root_cause": row.get("root_cause"),
        "first_zero_stage": row.get("first_zero_stage"),
    }


def _incidents_for_day(
    session: Session,
    *,
    start_utc: datetime,
    end_utc: datetime,
    market: str | None = None,
) -> list[dict[str, Any]]:
    params: dict[str, Any] = {"start_utc": start_utc, "end_utc": end_utc}
    market_clause = ""
    if market:
        params["market"] = str(market).upper()
        market_clause = "AND market = :market"
    rows = session.execute(
        text(
            f"""
            SELECT incident_id, market, uba_id, signature, classification,
                   first_zero_stage, root_cause, started_at, recovered_at,
                   self_heal_level
            FROM operation.autotrading_incident_ledger
            WHERE started_at >= :start_utc AND started_at < :end_utc
            {market_clause}
            ORDER BY started_at ASC
            """
        ),
        params,
    ).mappings().all()
    items: list[dict[str, Any]] = [_incident_row_to_dict(row) for row in rows]
    return items


def _why_no_trade_ko(
    *,
    broker: str,
    ops: dict[str, Any],
    funnel_first_zero: str | None,
    funnel_reason: str | None,
) -> list[str]:
    """사용자 친화 미거래 사유 — raw code는 detail에만."""

    rel = ops.get("reliability") if isinstance(ops.get("reliability"), dict) else {}
    cls = str(rel.get("no_trade_classification") or "").upper()
    messages: list[str] = []

    if broker == "KIWOOM":
        phase = str(ops.get("krx_session_phase") or ops.get("market_session") or "").upper()
        if phase in {"CLOSED", "AFTER", "HOLIDAY"} or "CLOSE" in phase:
            messages.append("현재 정규장이 종료되었습니다.")
        feed = str((ops.get("market_feed") or {}).get("status") or "").upper()
        if (
            feed in {"DISCONNECTED", "UNHEALTHY", "REAL_STALE"}
            and not _is_kiwoom_expected_post_close(ops)
        ):
            messages.append("시세 연결 상태를 확인해야 합니다.")
        if funnel_first_zero == "NO_GOLDEN_CROSS_SIGNAL" or cls == "NORMAL_NO_SIGNAL":
            messages.append("오늘 Golden Cross가 발생하지 않았습니다.")
            return messages

    if cls == "NORMAL_NO_SIGNAL":
        messages.append("현재 매수 조건을 충족한 종목이 없습니다.")
    elif cls == "NORMAL_POLICY_BLOCK":
        reason = str((rel.get("no_trade_detail") or {}).get("reason") or "")
        if reason == "DAILY_LIMIT":
            messages.append("일일 매수 한도에 도달했습니다.")
        elif reason == "SLOT_FULL_WAITING":
            messages.append(
                "진입 조건은 충족했지만 포트폴리오 한도로 대기 중입니다."
            )
        else:
            messages.append("후보는 발견됐지만 정책 조건에서 대기 중입니다.")
    elif cls in {"WAITING_SLOT_STARVATION", "PIPELINE_STALL"}:
        messages.append(
            "진입 조건은 충족했지만 포트폴리오 한도로 대기 중입니다."
        )
    elif cls == "SYSTEM_FAILURE" or rel.get("partial_restore"):
        messages.append("시스템 점검이 필요합니다.")
    elif funnel_first_zero in {"ENTRY_PASS", "SIGNAL_EMITTED", "BEGIN_ENTRY"}:
        messages.append("후보는 발견됐지만 기술조건에서 제외되었습니다.")

    if not messages:
        top = str(funnel_reason or rel.get("first_zero_reason") or "").strip()
        if top:
            messages.append("오늘 자동매매 신호 조건을 충족한 거래가 없었습니다.")
        else:
            messages.append("오늘 자동매매 체결 거래가 없었습니다.")
    return messages


def _health_class(
    *,
    broker: str,
    ops: dict[str, Any],
    order_stats: dict[str, Any],
) -> tuple[str, str]:
    if broker == "KIWOOM" and _is_kiwoom_expected_post_close(ops):
        return "YELLOW", _HEALTH_LABEL["YELLOW"]

    rel = ops.get("reliability") if isinstance(ops.get("reliability"), dict) else {}
    cls = str(rel.get("no_trade_classification") or "").upper()
    health = str(rel.get("health_state") or "").upper()
    feed = str((ops.get("market_feed") or {}).get("status") or "").upper()

    if health == "BROKEN" or cls == "SYSTEM_FAILURE" or rel.get("partial_restore"):
        return "RED", _HEALTH_LABEL["RED"]
    if feed in {"DISCONNECTED", "UNHEALTHY", "REAL_STALE"} or health == "DEGRADED":
        if broker == "KIWOOM" and _is_kiwoom_expected_post_close(ops):
            return "YELLOW", _HEALTH_LABEL["YELLOW"]
        return "ORANGE", _HEALTH_LABEL["ORANGE"]
    if cls in {"NORMAL_NO_SIGNAL", "NORMAL_POLICY_BLOCK", "WAITING_SLOT_STARVATION"}:
        return "YELLOW", _HEALTH_LABEL["YELLOW"]
    if cls == "PIPELINE_STALL":
        return "ORANGE", _HEALTH_LABEL["ORANGE"]
    if order_stats.get("buy_fill_count") or order_stats.get("sell_fill_count"):
        return "GREEN", _HEALTH_LABEL["GREEN"]
    if str(ops.get("auto_trading_state") or "").upper() == "RUNNING":
        return "YELLOW", _HEALTH_LABEL["YELLOW"]
    return "GREEN", _HEALTH_LABEL["GREEN"]


def _kiwoom_ma_state(ops: dict[str, Any]) -> str | None:
    rel = ops.get("reliability") if isinstance(ops.get("reliability"), dict) else {}
    fz = str(rel.get("first_zero_stage") or "").upper()
    if fz == "NO_GOLDEN_CROSS_SIGNAL":
        return "BELOW"
    funnel = rel.get("funnel") if isinstance(rel.get("funnel"), dict) else {}
    reasons = funnel.get("reasons") or []
    if any("GOLDEN_CROSS" in str(r).upper() for r in reasons):
        return "NEW_GOLDEN_CROSS"
    if str(ops.get("auto_trading_state") or "").upper() == "RUNNING":
        return "ABOVE_NO_NEW_CROSS"
    return None


def _market_section(
    session: Session,
    *,
    broker: str,
    uba_id: int,
    report_date: date,
    start_utc: datetime,
    end_utc: datetime,
    include_current_ops: bool,
) -> dict[str, Any]:
    ops = (
        build_uba_daily_report_ops_projection(
            session, user_broker_account_id=int(uba_id)
        )
        if include_current_ops
        else {}
    )
    order_stats = _order_day_stats(
        session, uba_id=uba_id, start_utc=start_utc, end_utc=end_utc
    )

    perf = AutotradingPerformanceService(session).build(
        broker=broker,  # type: ignore[arg-type]
        period="TODAY" if report_date == datetime.now(_KST).date() else "ALL",
        include_ops=False,
    )
    broker_perf = perf
    if broker != "ALL":
        summary = perf.get("summary") if isinstance(perf.get("summary"), dict) else {}
    else:
        summary = {}

    # 당일이 아니면 closed_at 필터로 재집계 — 간단히 summary 사용
    summary = perf.get("summary") if isinstance(perf.get("summary"), dict) else {}
    realized = _dec(summary.get("realized_pnl") or summary.get("net_pnl"))
    unrealized = _dec(summary.get("unrealized_pnl"))
    open_count = len(perf.get("open_positions") or [])

    rel = ops.get("reliability") if isinstance(ops.get("reliability"), dict) else {}
    funnel = rel.get("funnel") if isinstance(rel.get("funnel"), dict) else {}
    funnel_fz = funnel.get("first_zero_stage") or rel.get("first_zero_stage")
    funnel_reason = funnel.get("first_zero_reason") or rel.get("first_zero_reason")

    health_code, health_label = _health_class(
        broker=broker, ops=ops, order_stats=order_stats
    )
    trust = current_data_trust_summary(
        session, market=broker, uba_id=int(uba_id)
    )

    daily_entry = {}
    fm = ops.get("full_market") if isinstance(ops.get("full_market"), dict) else {}
    if isinstance(fm.get("daily_entry"), dict):
        daily_entry = fm["daily_entry"]

    short_term: dict[str, Any] = {}
    if broker == "UPBIT":
        short_term = {
            "daily_entry_used": fm.get("daily_entry_used")
            or daily_entry.get("entry_count"),
            "daily_entry_limit": fm.get("daily_entry_limit")
            or daily_entry.get("entry_limit"),
            # LIMITED|UNLIMITED — magic value(0/-1)로 unlimited 표현 금지
            "daily_entry_limit_mode": fm.get("daily_entry_limit_mode")
            or daily_entry.get("mode")
            or "LIMITED",
            "daily_entry_label_ko": fm.get("daily_entry_label_ko")
            or daily_entry.get("label_ko"),
            "auto_slot_used": fm.get("auto_slot_used"),
            "auto_slot_limit": fm.get("auto_slot_limit"),
            "manual_holdings": fm.get("manual_holdings"),
            "unknown_holdings": fm.get("unknown_holdings"),
            "account_total_holdings": fm.get("account_total_holdings"),
        }
        try:
            from stock_platform.operation.upbit_full_market.natural_auto_performance import (
                build_natural_auto_performance_windows,
            )

            short_term["performance_windows"] = (
                build_natural_auto_performance_windows(
                    session, user_broker_account_id=int(uba_id)
                )
            )
        except Exception:  # noqa: BLE001
            short_term["performance_windows"] = {"error": "UNAVAILABLE"}
        try:
            from stock_platform.operation.upbit_opportunity_shadow.exit_strategy_shadow.summary import (
                summarize_exit_strategy_shadow,
            )

            ess = summarize_exit_strategy_shadow(
                session, user_broker_account_id=int(uba_id)
            )
            short_term["exit_shadow"] = {
                "natural_entries": ess.get("natural_entries"),
                "active_experiments": ess.get("active_experiments"),
                "matured_or_triggered": ess.get("matured_or_triggered"),
                "best_net_variant": (ess.get("best_net_variant") or {}).get(
                    "variant_code"
                ),
                "best_pf_variant": (ess.get("best_pf_variant") or {}).get(
                    "variant_code"
                ),
                "research_only": True,
            }
        except Exception:  # noqa: BLE001
            short_term["exit_shadow"] = {"error": "UNAVAILABLE"}

    pipeline = {}
    if broker == "UPBIT":
        pipeline = _pipeline_unique_stages(
            session, uba_id=uba_id, start_utc=start_utc, end_utc=end_utc
        )

    section: dict[str, Any] = {
        "market": broker,
        "uba_id": int(uba_id),
        "health_code": health_code,
        "health_label": health_label,
        "auto_trading_state": ops.get("auto_trading_state"),
        "auto_trading_ready": rel.get("auto_trading_ready"),
        "feed_status": (ops.get("market_feed") or {}).get("status"),
        "data_trust": trust,
        "live": ops.get("live"),
        "arm": ops.get("arm"),
        "trading_summary": {
            **order_stats,
            "realized_pnl": realized,
            "unrealized_pnl": unrealized,
            "open_position_count": open_count,
        },
        "daily_entry": daily_entry,
        "short_term_operation": short_term,
        "open_positions": (perf.get("open_positions") or [])[:10],
        "recent_trades": (perf.get("recent_closed_trades") or [])[:5],
        "why_no_trade": _why_no_trade_ko(
            broker=broker,
            ops=ops,
            funnel_first_zero=str(funnel_fz) if funnel_fz else None,
            funnel_reason=str(funnel_reason) if funnel_reason else None,
        ),
        "pipeline": pipeline,
    }
    # Long-hold summary — open_positions만 재사용 (N+1 금지)
    if broker == "UPBIT":
        try:
            from stock_platform.notification.alert_v2.display import (
                format_holding_duration,
            )
            from stock_platform.operation.upbit_long_hold_watch.checkpoints import (
                select_latest_checkpoint,
            )

            lh_rows = []
            for pos in perf.get("open_positions") or []:
                if not isinstance(pos, dict):
                    continue
                ownership = str(
                    pos.get("ownership")
                    or pos.get("ownership_code")
                    or "STRATEGY_OWNED"
                ).upper()
                if ownership != "STRATEGY_OWNED":
                    continue
                age = pos.get("holding_seconds") or pos.get("age_seconds")
                try:
                    age_f = float(age) if age is not None else None
                except (TypeError, ValueError):
                    age_f = None
                if age_f is None:
                    continue
                cp = select_latest_checkpoint(age_f)
                if cp is None:
                    continue
                lh_rows.append(
                    {
                        "symbol": pos.get("symbol"),
                        "holding_label": format_holding_duration(age_f),
                        "estimated_pnl_rate_pct": pos.get("return_rate_pct")
                        or pos.get("pnl_rate_pct"),
                        "checkpoint": cp,
                    }
                )
            section["long_hold_summary"] = {
                "count": len(lh_rows),
                "positions": lh_rows,
                "note": "장기보유 감시(자동매도 아님)",
            }
        except Exception:  # noqa: BLE001
            section["long_hold_summary"] = {
                "count": 0,
                "positions": [],
                "note": "unavailable",
            }
    if broker == "KIWOOM":
        section["market_session"] = ops.get("krx_session_phase") or ops.get(
            "market_session"
        )
        section["ma_state"] = _kiwoom_ma_state(ops)
    return section


def build_autotrading_daily_report(
    session: Session,
    *,
    report_date: date | None = None,
    market: MarketFilter = "ALL",
) -> dict[str, Any]:
    """Canonical 일일 운영보고 — mutation 없음."""

    settings = get_settings()
    rd = report_date or datetime.now(_KST).date()
    start_utc, end_utc = _kst_day_bounds(rd)
    is_today = rd == datetime.now(_KST).date()

    upbit_uba = int(
        getattr(settings, "mobile_default_upbit_uba_id", None) or _DEFAULT_UPBIT_UBA
    )
    kiwoom_uba = int(
        getattr(settings, "mobile_default_kiwoom_uba_id", None) or _DEFAULT_KIWOOM_UBA
    )

    upbit = kiwoom = None
    if market in {"ALL", "UPBIT"}:
        upbit = _market_section(
            session,
            broker="UPBIT",
            uba_id=upbit_uba,
            report_date=rd,
            start_utc=start_utc,
            end_utc=end_utc,
            include_current_ops=is_today,
        )
    if market in {"ALL", "KIWOOM"}:
        kiwoom = _market_section(
            session,
            broker="KIWOOM",
            uba_id=kiwoom_uba,
            report_date=rd,
            start_utc=start_utc,
            end_utc=end_utc,
            include_current_ops=is_today,
        )

    incidents_today = _incidents_for_day(
        session, start_utc=start_utc, end_utc=end_utc
    )
    active_incidents = _incidents_active(session)
    resolved_today = [
        i for i in incidents_today if i.get("recovered")
    ]

    research = build_cross_market_research_status_for_daily_report(
        session, upbit_uba_id=upbit_uba, kiwoom_uba_id=kiwoom_uba
    )
    overall = "YELLOW"
    codes = [
        (upbit or {}).get("health_code"),
        (kiwoom or {}).get("health_code"),
    ]
    # overall RED — active incident 또는 per-market RED만 (장후 Kiwoom YELLOW는 제외)
    if any(c == "RED" for c in codes) or active_incidents:
        if active_incidents and not any(c == "RED" for c in codes):
            overall = "ORANGE"
        else:
            overall = "RED" if any(c == "RED" for c in codes) else "ORANGE"
    elif any(c == "ORANGE" for c in codes):
        overall = "ORANGE"
    elif all(c == "GREEN" for c in codes if c):
        overall = "GREEN"

    overall_label = {
        "GREEN": "🟢 정상 운영",
        "YELLOW": "🟡 정상 대기",
        "ORANGE": "🟠 확인 필요",
        "RED": "🔴 확인 필요",
    }.get(overall, "🟡 정상 대기")

    return {
        "report_date": rd.isoformat(),
        "report_date_kst": rd.isoformat(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "market_filter": market,
        "overall_health_code": overall,
        "overall_health_label": overall_label,
        "upbit": upbit,
        "kiwoom": kiwoom,
        "incidents": {
            "today_count": len(incidents_today),
            "open_count": len(active_incidents),
            "active_count": len(active_incidents),
            "resolved_today_count": len(resolved_today),
            "items": incidents_today,
            "active_items": active_incidents,
            "historical_items": incidents_today,
        },
        "research": research,
        "read_only": True,
    }


def format_daily_report_telegram(report: dict[str, Any]) -> str:
    """Telegram 본문 — fail-open용 순수 문자열."""

    rd = report.get("report_date") or ""
    lines = [f"[시스템] 자동매매 일일보고", str(rd), ""]

    for key, label in (("upbit", "업비트"), ("kiwoom", "키움")):
        sec = report.get(key)
        if not isinstance(sec, dict):
            continue
        ts = sec.get("trading_summary") if isinstance(sec.get("trading_summary"), dict) else {}
        why = sec.get("why_no_trade") or []
        lines.append(f"[{label}]")
        lines.append(f"상태: {sec.get('health_label', '—')}")
        lines.append(f"매수: {ts.get('buy_order_count', 0)}")
        lines.append(f"매도: {ts.get('sell_order_count', 0)}")
        lines.append(f"실현손익: {ts.get('realized_pnl', 0)}")
        lines.append(f"보유: {ts.get('open_position_count', 0)}")
        if why:
            lines.append(f"미거래 사유: {why[0]}")
        lines.append("")

    inc = report.get("incidents") if isinstance(report.get("incidents"), dict) else {}
    lines.append(f"시스템 장애: {inc.get('today_count', 0)}건")
    lines.append(f"현재 미복구 장애: {inc.get('open_count', 0)}건")
    return "\n".join(lines)


def telegram_dedupe_key(report_date: date) -> str:
    return f"DAILY_TRADING_REPORT:{report_date.isoformat()}"


def was_daily_report_sent(session: Session, report_date: date) -> bool:
    from stock_platform.notification.inbox_repository import NotificationInboxRepository

    key = telegram_dedupe_key(report_date)
    return NotificationInboxRepository(session).find_by_dedupe(key) is not None
