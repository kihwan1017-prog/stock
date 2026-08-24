"""KIWOOM research context adapter — existing SoT only (no new scrapers)."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from stock_platform.ai.context_builder import CandidateContextBuilder
from stock_platform.operation.dual_llm.markets import MARKET_KIWOOM
from stock_platform.realtime.strategy_signal import StrategySignal


def _as_date(ts: datetime | None) -> date:
    if ts is None:
        return datetime.now(timezone.utc).date()
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ts.astimezone(timezone.utc).date()


def build_kiwoom_research_context(
    session: Session,
    *,
    signal: StrategySignal,
) -> dict[str, Any]:
    """ENTRY evaluation snapshot용 context — as_of = signal.event_time (lookahead 금지)."""

    as_of = _as_date(signal.event_time or signal.generated_at)
    builder = CandidateContextBuilder(session)
    raw = builder.build(
        exchange_code="KRX",
        symbol=str(signal.symbol).upper(),
        as_of_date=as_of,
    )
    price = raw.get("price") if isinstance(raw.get("price"), dict) else {}
    indicators = raw.get("indicators") if isinstance(raw.get("indicators"), dict) else {}
    news = raw.get("news") if isinstance(raw.get("news"), list) else []
    disclosures = (
        raw.get("disclosures") if isinstance(raw.get("disclosures"), list) else []
    )
    candidate_score = (
        raw.get("candidate_score")
        if isinstance(raw.get("candidate_score"), dict)
        else {}
    )

    # disclosure/news timestamp safety — as_of 이후 항목 제외
    as_of_dt = datetime.combine(as_of, datetime.min.time(), tzinfo=timezone.utc)
    safe_news: list[dict[str, Any]] = []
    for n in news:
        if not isinstance(n, dict):
            continue
        pub = n.get("published_at")
        if pub:
            try:
                pts = datetime.fromisoformat(str(pub).replace("Z", "+00:00"))
                if pts > as_of_dt + __import__("datetime").timedelta(days=1):
                    continue
            except ValueError:
                pass
        safe_news.append(
            {
                "title": n.get("title"),
                "published_at": n.get("published_at"),
                "summary": str(n.get("summary") or "")[:200],
            }
        )

    safe_disc: list[dict[str, Any]] = []
    for d in disclosures:
        if not isinstance(d, dict):
            continue
        safe_disc.append(
            {
                "report_nm": d.get("report_nm") or d.get("title"),
                "rcept_dt": d.get("rcept_dt") or d.get("published_at"),
                "summary": str(d.get("summary") or d.get("corp_cls") or "")[:120],
            }
        )

    meta = signal.metadata if isinstance(signal.metadata, dict) else {}
    short_ma = meta.get("short_average")
    long_ma = meta.get("long_average")
    ma_sep = None
    try:
        if short_ma is not None and long_ma is not None and float(long_ma) != 0:
            ma_sep = ((float(short_ma) - float(long_ma)) / abs(float(long_ma))) * 100.0
    except (TypeError, ValueError):
        ma_sep = None

    technical = {
        "rsi14": indicators.get("rsi14") or indicators.get("rsi"),
        "ma_separation_pct": ma_sep,
        "ma5": short_ma,
        "ma20": long_ma,
        "volume_ratio": price.get("volume_ratio") or indicators.get("volume_ratio"),
        "daily_return": price.get("daily_return") or price.get("change_rate"),
        "turnover": price.get("turnover") or price.get("trade_value"),
        "pre_entry_return": None,
        "near_high_distance": indicators.get("dist_from_high"),
        "source": "CandidateContextBuilder+MA_metadata",
    }

    return {
        "market": MARKET_KIWOOM,
        "exchange_code": "KRX",
        "symbol": str(signal.symbol).upper(),
        "context_as_of": as_of.isoformat(),
        "evaluated_at": (
            (signal.event_time or signal.generated_at).astimezone(timezone.utc).isoformat()
            if (signal.event_time or signal.generated_at)
            else None
        ),
        "candidate": {
            "symbol": str(signal.symbol).upper(),
            "recommendation": "ALLOW",  # REAL path already decided BUY — research baseline
            "score": candidate_score.get("score"),
            "scanner_score": candidate_score.get("score"),
            "reason_code": signal.reason_code,
            "signal_type": signal.signal_type,
        },
        "technical": technical,
        "market_context": {
            "market_type": signal.market_type,
            "broker_code": signal.broker_code,
            "session": "KRX",
            "note": "임의 외부 지수 없음 — 기존 SoT만 사용",
        },
        "asset_context": {
            "price": price.get("close") or price.get("trade_price"),
            "daily_return": technical.get("daily_return"),
            "volume": price.get("volume"),
            "turnover": technical.get("turnover"),
        },
        "news": safe_news[:8],
        "disclosures": safe_disc[:8],
        "provenance": {
            "uba_id": (
                int(signal.account_id)
                if str(signal.account_kind or "").upper() == "USER_BROKER"
                else None
            ),
            "strategy_id": signal.strategy_id,
            "strategy_version": signal.strategy_version,
            "scope_key": signal.scope_key,
            "signal_id": signal.signal_id,
            "fingerprint": signal.fingerprint,
            "account_kind": signal.account_kind,
            "source": "MA_ENTRY_EVALUATION",
            "forced": False,
            "synthetic": False,
            "imported_position": False,
        },
        "reference_price": str(signal.reference_price),
        "research_only": True,
        "lookahead_forbidden": True,
    }
