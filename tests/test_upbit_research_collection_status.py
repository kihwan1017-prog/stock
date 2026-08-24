"""Unit tests — Upbit research collection status aggregate (READ ONLY)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

from stock_platform.operation.upbit_market_context.research_collection_status import (
    _overall_ko,
    _sample_stage_ko,
    _status_from_age,
    build_research_collection_status,
)
from stock_platform.operation.upbit_opportunity_shadow.clean_forward_research import (
    CLEAN_FORWARD_EPOCH_START,
    TARGET_CLEAN_MIN,
    TARGET_CLEAN_RECOMMENDED,
)
from stock_platform.operation.upbit_opportunity_shadow.constants import (
    SHADOW_STATUS_COMPLETED,
)


def test_sample_stage_ko_collection_only() -> None:
    out = _sample_stage_ko("COLLECTION_ONLY")
    assert out["sample_stage_ko"] == "수집 단계"
    assert "REAL" in out["sample_stage_desc_ko"]


def test_waiting_not_error_status() -> None:
    assert _status_from_age(None, stale_after_sec=60) == "WAITING"
    assert _status_from_age(10.0, stale_after_sec=60) == "OK"
    assert _status_from_age(120.0, stale_after_sec=60) == "STALE"
    assert _status_from_age(10.0, stale_after_sec=60, has_error=True) == "ERROR"
    assert _overall_ko("WAITING") == "신규 후보 대기"
    assert "ERROR" not in _overall_ko("WAITING")


def _shadow(
    *,
    shadow_id: int,
    detected_at: datetime,
    detail: dict | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        shadow_id=shadow_id,
        symbol="KRW-TEST",
        status=SHADOW_STATUS_COMPLETED,
        deleted_at=None,
        detected_at=detected_at,
        entry_price=100.0,
        recommendation="ALLOW",
        detail=detail
        or {
            "price_source": "candle_open",
            "research_quality": {"clean_forward": True},
            "forward_outcome": {
                "net_pnl_krw": -10.0,
                "gross_pnl_krw": -5.0,
                "estimated_fee_krw": 5.0,
            },
            "features": {
                "rsi14": 55.0,
                "ma_separation_pct": 0.2,
                "volume_surge": 1.2,
            },
            "mfe_pct": 0.5,
            "mae_pct": -1.0,
            "return_5m_pct": -0.8,
        },
    )


def test_build_status_clean_targets_and_isolation(monkeypatch) -> None:
    now = datetime.now(timezone.utc)
    # CLEAN epoch 이후
    clean_at = max(CLEAN_FORWARD_EPOCH_START + timedelta(hours=1), now - timedelta(minutes=30))
    rows = [
        _shadow(shadow_id=1, detected_at=clean_at),
        _shadow(shadow_id=2, detected_at=clean_at - timedelta(minutes=5)),
    ]

    session = MagicMock()
    session.scalars.return_value = rows

    # snapshot / news / llm helpers → stub
    monkeypatch.setattr(
        "stock_platform.operation.upbit_market_context.research_collection_status._snapshot_table_stats",
        lambda *a, **k: {
            "status": "OK",
            "status_ko": "정상",
            "rows": 10,
            "today_new": 2,
            "last_collected_at": now.isoformat(),
            "age_seconds": 60,
        },
    )
    monkeypatch.setattr(
        "stock_platform.operation.upbit_market_context.research_collection_status._asset_table_stats",
        lambda *a, **k: {
            "status": "OK",
            "status_ko": "정상",
            "rows": 200,
            "symbols": 50,
            "today_new": 5,
            "last_collected_at": now.isoformat(),
            "age_seconds": 60,
        },
    )
    monkeypatch.setattr(
        "stock_platform.operation.upbit_market_context.research_collection_status._news_stats",
        lambda *a, **k: {
            "status": "OK",
            "status_ko": "정상",
            "recent_count": 42,
            "upbit_notice_count": 3,
            "candidate_linked_count": 15,
            "last_collected_at": now.isoformat(),
            "age_seconds": 120,
        },
    )
    monkeypatch.setattr(
        "stock_platform.operation.upbit_market_context.research_collection_status._llm_stats",
        lambda *a, **k: {
            "status": "OK",
            "status_ko": "정상",
            "total": 25,
            "today_count": 25,
            "allow": 8,
            "hold": 14,
            "reduce": 3,
            "failed": 0,
            "last_analysis_at": now.isoformat(),
            "age_seconds": 90,
        },
    )
    monkeypatch.setattr(
        "stock_platform.operation.upbit_market_context.research_collection_status.summarize_entry_quality_experiment_from_shadows",
        lambda _rows: {
            "SAMPLE_GATE": "COLLECTION_ONLY",
            "BASELINE": {"net": -100.0, "PF": 0.5, "early_dump_rate": 0.4},
            "BEST_FILTER_CURRENTLY": {
                "code": "E2",
                "name_ko": "MA 이격 ≥ 0.15%",
                "net_filter_benefit": 10.0,
            },
        },
    )
    # classify path may exclude stubs — force clean via assign/partition
    monkeypatch.setattr(
        "stock_platform.operation.upbit_market_context.research_collection_status.partition_forward_rows",
        lambda _rows: {
            "legacy_total": 459,
            "legacy_rows": [object()] * 459,
            "new_stamped_count": 17,
            "clean_new_count": 2,
        },
    )
    monkeypatch.setattr(
        "stock_platform.operation.upbit_market_context.research_collection_status.assign_clean_forward_obs",
        lambda _rows: [
            SimpleNamespace(detected_at=clean_at),
            SimpleNamespace(detected_at=clean_at - timedelta(minutes=10)),
        ],
    )
    monkeypatch.setattr(
        "stock_platform.operation.upbit_market_context.research_collection_status.sample_gate",
        lambda n: "COLLECTION_ONLY" if n < 100 else "DIAGNOSTIC_ONLY",
    )

    out = build_research_collection_status(session, user_broker_account_id=1380)

    assert out["schema"] == "upbit_research_collection_status_v1"
    assert out["user_broker_account_id"] == 1380
    assert out["clean_forward"]["count"] == 2
    assert out["clean_forward"]["target_primary"] == TARGET_CLEAN_MIN
    assert out["clean_forward"]["target_recommended"] == TARGET_CLEAN_RECOMMENDED
    assert out["clean_forward"]["sample_stage"] == "COLLECTION_ONLY"
    assert out["clean_forward"]["sample_stage_ko"] == "수집 단계"
    assert out["clean_forward"]["today_new"] >= 0
    assert out["clean_forward"]["last_new_at"] is not None

    # Legacy/Backfill isolation — not summed into CLEAN
    assert out["reference"]["legacy_count"] == 459
    assert out["reference"]["backfill_count"] == 17
    assert out["clean_forward"]["count"] != (
        out["reference"]["legacy_count"] + out["reference"]["backfill_count"]
    )

    assert out["market_context"]["status"] == "OK"
    assert out["market_context"]["rows"] == 10
    assert out["asset_context"]["symbols"] == 50
    assert out["news"]["recent_count"] == 42
    assert out["llm"]["allow"] == 8
    assert out["experiment"]["best_candidate"] == "E2"
    assert out["experiment"]["sample_warning"] is True
    assert out["experiment"]["provisional_badge"] is True
    assert out["mutations"]["REAL_ORDER_MUTATION"] == 0
    assert out["mutations"]["LIVE_ARM_MUTATION"] == 0
    assert out["mutations"]["UBA1381_MUTATION"] == 0


def test_clean_unchanged_is_waiting_not_error(monkeypatch) -> None:
    """CLEAN count stagnant → WAITING, never ERROR solely from that."""

    now = datetime.now(timezone.utc)
    old = now - timedelta(hours=8)
    session = MagicMock()
    session.scalars.return_value = []

    monkeypatch.setattr(
        "stock_platform.operation.upbit_market_context.research_collection_status.partition_forward_rows",
        lambda _r: {
            "legacy_total": 459,
            "legacy_rows": [],
            "new_stamped_count": 0,
            "clean_new_count": 1,
        },
    )
    monkeypatch.setattr(
        "stock_platform.operation.upbit_market_context.research_collection_status.assign_clean_forward_obs",
        lambda _r: [SimpleNamespace(detected_at=old)],
    )
    monkeypatch.setattr(
        "stock_platform.operation.upbit_market_context.research_collection_status.sample_gate",
        lambda n: "COLLECTION_ONLY",
    )
    for name in (
        "_snapshot_table_stats",
        "_asset_table_stats",
        "_news_stats",
        "_llm_stats",
    ):
        monkeypatch.setattr(
            f"stock_platform.operation.upbit_market_context.research_collection_status.{name}",
            lambda *a, **k: {
                "status": "OK",
                "status_ko": "정상",
                "rows": 1,
                "symbols": 1,
                "today_new": 0,
                "recent_count": 1,
                "today_count": 0,
                "allow": 0,
                "hold": 0,
                "reduce": 0,
                "failed": 0,
                "total": 0,
                "last_collected_at": now.isoformat(),
                "last_analysis_at": now.isoformat(),
                "age_seconds": 10,
            },
        )
    monkeypatch.setattr(
        "stock_platform.operation.upbit_market_context.research_collection_status.summarize_entry_quality_experiment_from_shadows",
        lambda _r: {
            "SAMPLE_GATE": "COLLECTION_ONLY",
            "BASELINE": {},
            "BEST_FILTER_CURRENTLY": None,
        },
    )

    out = build_research_collection_status(session, user_broker_account_id=1380)
    assert out["clean_forward"]["status"] == "WAITING"
    assert out["overall_status"] in {"WAITING", "COLLECTING", "PARTIAL"}
    assert out["overall_status"] != "ERROR"
