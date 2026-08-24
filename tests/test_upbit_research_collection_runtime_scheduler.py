"""Focused tests — Upbit research collection runtime + scheduler."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from stock_platform.api.v1.admin_autotrading_readiness import router as readiness_router
from stock_platform.operation.upbit_market_context.research_collection_scheduler import (
    UpbitMarketContextResearchScheduler,
)
from stock_platform.operation.upbit_market_context.research_collection_status import (
    build_research_collection_status,
)
from stock_platform.operation.upbit_opportunity_shadow.clean_forward_research import (
    CLEAN_FORWARD_EPOCH_START,
    TARGET_CLEAN_MIN,
)


def test_collection_status_route_registered() -> None:
    paths = [
        getattr(r, "path", "")
        for r in readiness_router.routes
    ]
    assert any(
        "research/collection-status" in (p or "") for p in paths
    )


def test_collection_status_route_200(monkeypatch: pytest.MonkeyPatch) -> None:
    app = FastAPI()
    app.include_router(readiness_router)

    async def _admin():
        return SimpleNamespace(username="admin", user_id=1)

    from stock_platform.api.deps_admin import require_admin
    from stock_platform.database.session import get_db_session

    app.dependency_overrides[require_admin] = _admin
    app.dependency_overrides[get_db_session] = lambda: MagicMock()

    monkeypatch.setattr(
        "stock_platform.operation.upbit_market_context.research_collection_status.build_research_collection_status",
        lambda session, user_broker_account_id=None: {
            "schema": "upbit_research_collection_status_v1",
            "user_broker_account_id": user_broker_account_id,
            "clean_forward": {"count": 37, "target_primary": 500},
            "mutations": {"REAL_ORDER_MUTATION": 0},
        },
    )

    client = TestClient(app)
    res = client.get("/api/v1/admin/autotrading/uba/1380/research/collection-status")
    assert res.status_code == 200
    body = res.json()
    assert body["clean_forward"]["count"] == 37
    assert body["user_broker_account_id"] == 1380


def test_clean_count_reflects_assign(monkeypatch: pytest.MonkeyPatch) -> None:
    now = datetime.now(timezone.utc)
    clean_at = max(CLEAN_FORWARD_EPOCH_START + timedelta(hours=1), now - timedelta(minutes=10))
    session = MagicMock()
    session.scalars.return_value = []

    monkeypatch.setattr(
        "stock_platform.operation.upbit_market_context.research_collection_status.partition_forward_rows",
        lambda _r: {
            "legacy_total": 459,
            "legacy_rows": [object()] * 459,
            "new_stamped_count": 17,
            "clean_new_count": 37,
        },
    )
    monkeypatch.setattr(
        "stock_platform.operation.upbit_market_context.research_collection_status.assign_clean_forward_obs",
        lambda _r: [SimpleNamespace(detected_at=clean_at) for _ in range(37)],
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
        "_scheduler_health",
    ):
        monkeypatch.setattr(
            f"stock_platform.operation.upbit_market_context.research_collection_status.{name}",
            lambda *a, **k: {
                "status": "OK",
                "status_ko": "정상",
                "rows": 10,
                "symbols": 10,
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
                "running": True,
                "auto_collect": "ON",
                "jobs": [],
                "market": {"interval_seconds": 600, "enabled": True, "scheduled": True},
                "asset": {"interval_seconds": 600, "enabled": True, "scheduled": True},
                "news": {"interval_seconds": 900, "enabled": True, "scheduled": True},
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
    monkeypatch.setattr(
        "stock_platform.operation.upbit_market_context.research_collection_status._enrich_source_with_scheduler",
        lambda block, *_a, **_k: block,
    )

    out = build_research_collection_status(session, user_broker_account_id=1380)
    assert out["clean_forward"]["count"] == 37
    assert out["clean_forward"]["target_primary"] == TARGET_CLEAN_MIN
    assert out["reference"]["legacy_count"] == 459
    assert out["reference"]["backfill_count"] == 17
    assert out["scheduler"]["auto_collect"] == "ON"
    assert out["llm"]["trigger"] == "CANDIDATE_DRIVEN"
    assert out["clean_forward"]["scheduler_fake_rows"] is False
    assert out["mutations"]["REAL_ORDER_MUTATION"] == 0
    assert out["mutations"]["UBA1381_MUTATION"] == 0


def test_scheduler_registration_and_no_duplicate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("UPBIT_MARKET_CONTEXT_COLLECTION_ENABLED", "true")
    monkeypatch.setenv("UPBIT_MARKET_CONTEXT_COLLECTION_INTERVAL_SECONDS", "600")
    monkeypatch.setenv("UPBIT_MARKET_CONTEXT_FNG_INTERVAL_SECONDS", "3600")
    from stock_platform.common.settings import clear_settings_cache

    clear_settings_cache()
    sched = UpbitMarketContextResearchScheduler()
    sched.configure(force=True)
    sched.configure(force=True)  # duplicate 방지 — replace_existing
    job_ids = [j.id for j in sched._scheduler.get_jobs()]
    assert job_ids.count(sched.MARKET_JOB_ID) == 1
    assert job_ids.count(sched.FNG_JOB_ID) == 1
    assert sched.market_interval_seconds() == 600
    assert sched.asset_interval_seconds() == 600
    assert sched.fng_interval_seconds() == 3600
    st = sched.status()
    assert st["creates_clean_forward"] is False
    assert st["live_order"] is False


def test_scheduler_does_not_create_clean_rows() -> None:
    """CLEAN은 scanner/shadow lifecycle 전용 — market scheduler 금지."""

    sched = UpbitMarketContextResearchScheduler()
    assert "creates_clean_forward" in sched.status()
    assert sched.status()["creates_clean_forward"] is False


def test_candidate_llm_not_periodic() -> None:
    from stock_platform.operation.upbit_market_context.research_collection_status import (
        _scheduler_health,
    )

    health = _scheduler_health()
    assert health["llm"]["periodic"] is False
    assert health["llm"]["trigger"] == "CANDIDATE_DRIVEN"
    assert health["clean_forward"]["fake_rows_forbidden"] is True


def test_collection_failure_does_not_mutate_trading(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """research failure → REAL/LIVE/Risk mutate 0."""

    session = MagicMock()
    session.scalars.return_value = []
    monkeypatch.setattr(
        "stock_platform.operation.upbit_market_context.research_collection_status.partition_forward_rows",
        lambda _r: {
            "legacy_total": 0,
            "legacy_rows": [],
            "new_stamped_count": 0,
            "clean_new_count": 0,
        },
    )
    monkeypatch.setattr(
        "stock_platform.operation.upbit_market_context.research_collection_status.assign_clean_forward_obs",
        lambda _r: [],
    )
    monkeypatch.setattr(
        "stock_platform.operation.upbit_market_context.research_collection_status.sample_gate",
        lambda n: "COLLECTION_ONLY",
    )
    monkeypatch.setattr(
        "stock_platform.operation.upbit_market_context.research_collection_status._snapshot_table_stats",
        lambda *a, **k: {"status": "ERROR", "status_ko": "오류", "rows": 0},
    )
    monkeypatch.setattr(
        "stock_platform.operation.upbit_market_context.research_collection_status._asset_table_stats",
        lambda *a, **k: {"status": "ERROR", "status_ko": "오류", "rows": 0, "symbols": 0},
    )
    monkeypatch.setattr(
        "stock_platform.operation.upbit_market_context.research_collection_status._news_stats",
        lambda *a, **k: {"status": "WAITING", "status_ko": "대기", "recent_count": 0},
    )
    monkeypatch.setattr(
        "stock_platform.operation.upbit_market_context.research_collection_status._llm_stats",
        lambda *a, **k: {
            "status": "WAITING",
            "status_ko": "대기",
            "today_count": 0,
            "total": 0,
            "allow": 0,
            "hold": 0,
            "reduce": 0,
            "failed": 0,
        },
    )
    monkeypatch.setattr(
        "stock_platform.operation.upbit_market_context.research_collection_status._scheduler_health",
        lambda: {
            "running": False,
            "auto_collect": "OFF",
            "jobs": [],
            "market": {"interval_seconds": 600, "enabled": False},
            "asset": {"interval_seconds": 600, "enabled": False},
            "news": {"interval_seconds": 900, "enabled": False},
        },
    )
    monkeypatch.setattr(
        "stock_platform.operation.upbit_market_context.research_collection_status._enrich_source_with_scheduler",
        lambda block, *_a, **_k: block,
    )
    monkeypatch.setattr(
        "stock_platform.operation.upbit_market_context.research_collection_status.summarize_entry_quality_experiment_from_shadows",
        lambda _r: {"SAMPLE_GATE": "COLLECTION_ONLY", "BASELINE": {}, "BEST_FILTER_CURRENTLY": None},
    )

    out = build_research_collection_status(session, user_broker_account_id=1380)
    assert out["mutations"]["REAL_ORDER_MUTATION"] == 0
    assert out["mutations"]["LIVE_ARM_MUTATION"] == 0
    assert out["mutations"]["RISK_MUTATION"] == 0
    assert out["mutations"]["SLOT_POLICY_MUTATION"] == 0
    assert out["mutations"]["UBA1381_MUTATION"] == 0
    assert out["live_order"] is False


def test_uba_isolation_field_present(monkeypatch: pytest.MonkeyPatch) -> None:
    session = MagicMock()
    session.scalars.return_value = []
    for name in (
        "partition_forward_rows",
        "assign_clean_forward_obs",
        "sample_gate",
        "_snapshot_table_stats",
        "_asset_table_stats",
        "_news_stats",
        "_llm_stats",
        "_scheduler_health",
        "_enrich_source_with_scheduler",
        "summarize_entry_quality_experiment_from_shadows",
    ):
        if name == "partition_forward_rows":
            monkeypatch.setattr(
                f"stock_platform.operation.upbit_market_context.research_collection_status.{name}",
                lambda _r: {
                    "legacy_total": 0,
                    "legacy_rows": [],
                    "new_stamped_count": 0,
                },
            )
        elif name == "assign_clean_forward_obs":
            monkeypatch.setattr(
                f"stock_platform.operation.upbit_market_context.research_collection_status.{name}",
                lambda _r: [],
            )
        elif name == "sample_gate":
            monkeypatch.setattr(
                f"stock_platform.operation.upbit_market_context.research_collection_status.{name}",
                lambda n: "COLLECTION_ONLY",
            )
        elif name == "summarize_entry_quality_experiment_from_shadows":
            monkeypatch.setattr(
                f"stock_platform.operation.upbit_market_context.research_collection_status.{name}",
                lambda _r: {
                    "SAMPLE_GATE": "COLLECTION_ONLY",
                    "BASELINE": {},
                    "BEST_FILTER_CURRENTLY": None,
                },
            )
        elif name == "_enrich_source_with_scheduler":
            monkeypatch.setattr(
                f"stock_platform.operation.upbit_market_context.research_collection_status.{name}",
                lambda block, *_a, **_k: block,
            )
        elif name == "_scheduler_health":
            monkeypatch.setattr(
                f"stock_platform.operation.upbit_market_context.research_collection_status.{name}",
                lambda: {
                    "running": True,
                    "auto_collect": "ON",
                    "jobs": [],
                    "market": {"interval_seconds": 600, "enabled": True},
                    "asset": {"interval_seconds": 600, "enabled": True},
                    "news": {"interval_seconds": 900, "enabled": True},
                },
            )
        else:
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
                    "last_collected_at": None,
                    "last_analysis_at": None,
                },
            )

    a = build_research_collection_status(session, user_broker_account_id=1380)
    b = build_research_collection_status(session, user_broker_account_id=1381)
    assert a["user_broker_account_id"] == 1380
    assert b["user_broker_account_id"] == 1381
    # 연구 데이터는 플랫폼 공통이지만 UBA id는 응답에 격리 표기
    assert a["clean_forward"]["count"] == b["clean_forward"]["count"]
