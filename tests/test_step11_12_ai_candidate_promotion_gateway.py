"""STEP 11-12 — Candidate Promotion Gateway tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from stock_platform.ai.candidate_promotion.constants import (
    MAX_BATCH,
    PROMOTION_RUN_TYPE,
    REFERENCE_DISCLAIMER,
    SCORE_FORMULA_VERSION,
)
from stock_platform.ai.candidate_promotion.score import compute_promotion_score
from stock_platform.ai.execution.constants import EXECUTABLE_TASK_TYPES


def test_migration_head() -> None:
    from tests.migration_helpers import alembic_current_head

    versions = Path("database/alembic/versions")
    assert any(p.name.startswith("ad4e5f6a7b8c") for p in versions.glob("*.py"))
    assert alembic_current_head() == "ae5f6a7b8c9d"


def test_no_new_execution_tasks() -> None:
    assert "CANDIDATE_PROMOTION" not in EXECUTABLE_TASK_TYPES
    assert PROMOTION_RUN_TYPE not in EXECUTABLE_TASK_TYPES


def test_constants() -> None:
    assert PROMOTION_RUN_TYPE == "AI_REVIEW_PROMOTION"
    assert MAX_BATCH == 20
    assert SCORE_FORMULA_VERSION.startswith("promotion-score")
    assert "매수" in REFERENCE_DISCLAIMER or "Candidate" in REFERENCE_DISCLAIMER


def test_score_formula_not_raw_confidence() -> None:
    # confidence=1.0만으로 고점수 불가 — 다른 요인 반영
    high_conf = compute_promotion_score(
        review_overall_scores=[2.0],
        source_quality_score=20.0,
        confidence=1.0,
        agreement_level="WEAK",
        risk_score=80.0,
        warning_count=2,
        has_critical=False,
    )
    assert high_conf["total_score"] < 80
    assert high_conf["formula_version"] == SCORE_FORMULA_VERSION
    # AI confidence를 total로 직접 사용하지 않음
    assert high_conf["total_score"] != 100.0
    assert high_conf["total_score"] != 1.0


def test_critical_blocks_score() -> None:
    blocked = compute_promotion_score(
        review_overall_scores=[5.0],
        source_quality_score=90.0,
        confidence=0.9,
        agreement_level="HIGH",
        risk_score=10.0,
        has_critical=True,
    )
    assert blocked["total_score"] == 0.0
    assert blocked["components"].get("blocked") is True


def test_get_latest_run_defaults_daily() -> None:
    import inspect

    from stock_platform.screener.run_repository import CandidateRunRepository

    sig = inspect.signature(CandidateRunRepository.get_latest_run)
    assert sig.parameters["run_type"].default == "DAILY"


def test_candidate_runs_api_forbids_promotion_type() -> None:
    src = Path("src/stock_platform/api/v1/candidate_runs.py").read_text(
        encoding="utf-8"
    )
    assert "AI_REVIEW_PROMOTION" in src
    assert "PROMOTION_RUN_TYPE_FORBIDDEN" in src


def test_no_trading_imports_in_package() -> None:
    root = Path("src/stock_platform/ai/candidate_promotion")
    banned = (
        "from stock_platform.trading",
        "from stock_platform.order",
        "from stock_platform.runtime",
        "from stock_platform.scheduler",
        "from stock_platform.strategy",
    )
    for path in root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for token in banned:
            assert token not in text, f"{path}: {token}"


def test_api_router_registered() -> None:
    from stock_platform.api.router import _ROUTER_GROUPS

    prefixes = {getattr(r, "prefix", "") for r in _ROUTER_GROUPS}
    assert "/api/v1/admin/ai/candidate-promotions" in prefixes


def test_dashboard_and_telegram_wired() -> None:
    dash = Path(
        "src/stock_platform/operation/operations_center_dashboard_service.py"
    ).read_text(encoding="utf-8")
    assert "ai_candidate_promotions" in dash
    assert "_ai_candidate_promotions_block" in dash
    cmds = Path(
        "src/stock_platform/notification/telegram_commands.py"
    ).read_text(encoding="utf-8")
    assert "/ai_candidate_promotions" in cmds
    status = Path(
        "src/stock_platform/notification/telegram_status.py"
    ).read_text(encoding="utf-8")
    assert "build_ai_candidate_promotions_text" in status
    assert "forbidden" in status.lower()


def test_frontend_page() -> None:
    path = Path(
        "frontend/src/app/(admin)/admin/ai/candidate-promotions/page.tsx"
    )
    assert path.exists()
    text = path.read_text(encoding="utf-8")
    assert "App.useApp()" in text
    assert "REFERENCE_DISCLAIMER" in text
    assert "title={REFERENCE_DISCLAIMER}" in text
    assert "addonBefore" not in text
    assert ">매수<" not in text
    assert ">매도<" not in text
    assert ">주문<" not in text
    assert "Commit" in text


def test_batch_limit() -> None:
    from unittest.mock import MagicMock

    from stock_platform.ai.candidate_promotion.batch_service import (
        AICandidatePromotionBatchService,
    )
    from stock_platform.ai.candidate_promotion.service import (
        AICandidatePromotionError,
    )

    svc = AICandidatePromotionBatchService(MagicMock())
    with pytest.raises(AICandidatePromotionError) as exc:
        svc.create_batch(
            actor="admin:1",
            reason="batch",
            queue_ids=list(range(1, 22)),
            idempotency_key="b1",
        )
    assert exc.value.code == "BATCH_LIMIT"
