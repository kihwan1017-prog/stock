"""Tests — Upbit market context LLM research pipeline (no REAL orders)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from stock_platform.operation.upbit_market_context.as_of import (
    assert_no_lookahead,
    select_latest_as_of,
    validate_bundle_no_lookahead,
)
from stock_platform.operation.upbit_market_context.collectors import (
    blocked_datalab_placeholder,
    build_market_metrics_from_tickers,
    dedupe_news_items,
)
from stock_platform.operation.upbit_market_context.early_dump_research import (
    early_dump_research_design,
    llm_quality_accept,
)
from stock_platform.operation.upbit_market_context.schemas import (
    LlmContextInput,
    fail_open_output,
    parse_llm_output,
)
from stock_platform.operation.upbit_market_context.source_registry import (
    QUALITY_BLOCKED,
    source_audit_report,
)
from stock_platform.operation.upbit_market_context.snapshot_service import (
    heuristic_llm_analyze,
)
from stock_platform.operation.upbit_market_context.telegram_enrichment import (
    build_optional_telegram_suffix,
    market_mood_ko,
)


def test_source_audit_blocks_datalab_api() -> None:
    audit = source_audit_report()
    assert audit["DATA_COLLECTION_METHOD"]["datalab_scrape"] is False
    assert "upbit_datalab_indices" in audit["WEB_ONLY_SOURCES"]
    assert "upbit_quotation_ticker" in audit["OFFICIAL_API_AVAILABLE"]


def test_no_lookahead_violation() -> None:
    det = datetime(2026, 8, 24, 10, 0, tzinfo=timezone.utc)
    ok = assert_no_lookahead(
        detected_at=det,
        context_timestamp=det - timedelta(minutes=1),
        field="fear",
    )
    bad = assert_no_lookahead(
        detected_at=det,
        context_timestamp=det + timedelta(minutes=1),
        field="fear",
    )
    assert ok["ok"] is True
    assert bad["ok"] is False
    assert bad["reason"] == "LOOKAHEAD_VIOLATION"


def test_select_latest_as_of() -> None:
    det = datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)
    rows = [
        {
            "source_timestamp": det - timedelta(hours=2),
            "value_json": {"v": 1},
        },
        {
            "source_timestamp": det - timedelta(minutes=5),
            "value_json": {"v": 2},
        },
        {
            "source_timestamp": det + timedelta(minutes=1),
            "value_json": {"v": 3},
        },
    ]
    picked = select_latest_as_of(rows, detected_at=det)
    assert picked is not None
    assert picked["value_json"]["v"] == 2


def test_validate_bundle() -> None:
    det = datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)
    res = validate_bundle_no_lookahead(
        detected_at=det,
        parts={"a": det - timedelta(seconds=1), "b": det + timedelta(seconds=1)},
    )
    assert res["ok"] is False
    assert len(res["violations"]) == 1


def test_ticker_metrics_and_ranks() -> None:
    tickers = [
        {
            "market": "KRW-AAA",
            "signed_change_rate": 0.01,
            "acc_trade_price_24h": 1000,
            "trade_price": 1,
        },
        {
            "market": "KRW-BBB",
            "signed_change_rate": -0.02,
            "acc_trade_price_24h": 5000,
            "trade_price": 2,
        },
        {
            "market": "BTC-XXX",
            "signed_change_rate": 0.5,
            "acc_trade_price_24h": 9e9,
            "trade_price": 3,
        },
    ]
    rows = build_market_metrics_from_tickers(tickers)
    adv = next(r for r in rows if r["feature_key"] == "advancing_asset_ratio")
    assert adv["value_json"]["advancing"] == 1
    assets = [r for r in rows if r.get("symbol")]
    assert len(assets) == 2
    bbb = next(r for r in assets if r["symbol"] == "KRW-BBB")
    assert bbb["value_json"]["turnover_rank"] == 1


def test_datalab_placeholder_blocked() -> None:
    row = blocked_datalab_placeholder("upbit10")
    assert row["quality"] == QUALITY_BLOCKED
    assert row["raw_provenance"]["decision"] == "NO_SCRAPE"


def test_dedupe_news() -> None:
    items = [
        {"headline": "A", "published_at": "t1", "source": "upbit"},
        {"headline": "A", "published_at": "t1", "source": "upbit"},
        {"headline": "B", "published_at": "t2", "source": "upbit"},
    ]
    assert len(dedupe_news_items(items)) == 2


def test_llm_schema_fail_open() -> None:
    out = parse_llm_output({"recommendation": "BUY", "confidence": 1})
    assert out.recommendation == "HOLD"
    assert out.context_unavailable is True
    out2 = parse_llm_output(
        {
            "recommendation": "ALLOW",
            "confidence": 0.7,
            "entry_quality_score": 80,
            "risk_flags": ["OVERHEATED", "UNKNOWN_FLAG"],
            "positive_factors": [],
            "negative_factors": [],
            "short_reason_ko": "ok",
        }
    )
    assert out2.recommendation == "ALLOW"
    assert out2.risk_flags == ["OVERHEATED"]


def test_heuristic_llm_flags_spike() -> None:
    inp = LlmContextInput(
        context_as_of=datetime.now(timezone.utc).isoformat(),
        candidate={"symbol": "KRW-TEST"},
        technical={"rsi14": 75, "pre_entry_return_5m": 0.8, "volume_surge": 3.0},
        market_context={},
    )
    out = heuristic_llm_analyze(inp)
    assert "RECENT_SPIKE" in out.risk_flags or "OVERHEATED" in out.risk_flags
    assert out.recommendation in {"ALLOW", "HOLD", "REDUCE"}
    assert llm_quality_accept(out) is False


def test_fail_open_does_not_block() -> None:
    out = fail_open_output(reason="provider down")
    assert llm_quality_accept(out) is True  # fail-open keep


def test_early_dump_design_excludes_legacy() -> None:
    d = early_dump_research_design()
    assert d["legacy_excluded"] is True
    assert d["real_promotion_auto"] is False
    assert d["REAL_14_REFERENCE"]["rt"] == 14


def test_telegram_suffix_not_spammy() -> None:
    assert build_optional_telegram_suffix({}) is None
    s = build_optional_telegram_suffix(
        {"advancing_ratio": 0.7, "llm_risk_short": "과열"}
    )
    assert s is not None
    assert "강세" in s
    assert market_mood_ko(0.3, 20) in {"약세", "공포"}
