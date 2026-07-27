"""STEP 11-11 — AI Candidate Recommendation Queue integration tests."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from stock_platform.ai.candidate_recommendation_queue.constants import (
    MAX_BATCH_CREATE,
    QUEUE_STATUS,
    REFERENCE_DISCLAIMER,
)
from stock_platform.ai.candidate_recommendation_queue.rubric import compute_overall_score
from stock_platform.ai.execution.constants import EXECUTABLE_TASK_TYPES


def test_migration_head() -> None:
    from tests.migration_helpers import alembic_current_head

    versions = Path("database/alembic/versions")
    assert any(p.name.startswith("ac3d4e5f6a7b") for p in versions.glob("*.py"))
    assert alembic_current_head() == "ae5f6a7b8c9d"


def test_queue_tasks_not_in_executable() -> None:
    """Queue는 AI Execution task 추가 없음."""
    for token in (
        "CANDIDATE_RECOMMENDATION_QUEUE",
        "RECOMMENDATION_QUEUE",
        "AI_CANDIDATE_QUEUE",
    ):
        assert not any(token in t for t in EXECUTABLE_TASK_TYPES)


def test_constants() -> None:
    assert "APPROVED_FOR_CONSIDERATION" in QUEUE_STATUS
    assert MAX_BATCH_CREATE == 100
    assert "후보 등록" in REFERENCE_DISCLAIMER or "Candidate" in REFERENCE_DISCLAIMER


def test_rubric_overall_server_side() -> None:
    overall = compute_overall_score(
        eligibility_score=4.0,
        analytical_quality_score=4.0,
        evidence_quality_score=4.0,
        risk_awareness_score=4.0,
        consistency_score=4.0,
        safety_score=4.0,
    )
    assert overall == 4.0


def test_batch_limit() -> None:
    from stock_platform.ai.candidate_recommendation_queue.batch_service import (
        AIRecommendationQueueBatchService,
    )
    from stock_platform.ai.candidate_recommendation_queue.service import (
        AIRecommendationQueueError,
    )

    svc = AIRecommendationQueueBatchService(MagicMock())
    sources = [{"source_type": "CANDIDATE_ASSESSMENT", "candidate_assessment_id": i} for i in range(101)]
    with pytest.raises(AIRecommendationQueueError) as exc:
        svc.create_batch(
            actor="admin:1",
            reason="batch",
            sources=sources,
            idempotency_key="b1",
        )
    assert exc.value.code == "BATCH_LIMIT"


def test_no_trading_imports_in_package() -> None:
    root = Path("src/stock_platform/ai/candidate_recommendation_queue")
    banned_import_prefixes = (
        "from stock_platform.strategy",
        "from stock_platform.trading",
        "from stock_platform.order",
        "from stock_platform.runtime",
        "from stock_platform.scheduler",
        "import stock_platform.strategy",
        "import stock_platform.trading",
    )
    offenders: list[str] = []
    for path in root.rglob("*.py"):
        for line_no, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            stripped = line.strip()
            if not stripped.startswith(("from ", "import ")):
                continue
            for prefix in banned_import_prefixes:
                if prefix in stripped:
                    offenders.append(f"{path}:{line_no}:{stripped}")
    assert offenders == []


def test_api_router_registered() -> None:
    from stock_platform.api.router import _ROUTER_GROUPS

    prefixes = {getattr(r, "prefix", "") for r in _ROUTER_GROUPS}
    assert "/api/v1/admin/ai/candidate-recommendation-queues" in prefixes


def test_dashboard_block_wired() -> None:
    src = Path(
        "src/stock_platform/operation/operations_center_dashboard_service.py"
    ).read_text(encoding="utf-8")
    assert "ai_candidate_recommendation_queues" in src
    assert "_ai_candidate_recommendation_queues_block" in src
    assert "external_calls_on_read" in src


def test_telegram_readonly_command() -> None:
    src = Path(
        "src/stock_platform/notification/telegram_commands.py"
    ).read_text(encoding="utf-8")
    assert "/ai_candidate_queue" in src
    status = Path(
        "src/stock_platform/notification/telegram_status.py"
    ).read_text(encoding="utf-8")
    assert "build_ai_candidate_queue_text" in status
    assert "forbidden" in status.lower()


def test_frontend_page_exists() -> None:
    path = Path(
        "frontend/src/app/(admin)/admin/ai/candidate-recommendation-queues/page.tsx"
    )
    assert path.exists()
    text = path.read_text(encoding="utf-8")
    assert "REFERENCE_DISCLAIMER" in text
    assert "기존 후보 등록 검토 가능" in text
    assert "title={REFERENCE_DISCLAIMER}" in text
    assert "addonBefore" not in text
    assert "rowKey" in text
    assert ", index" not in text
    assert ">후보 등록<" not in text
    assert ">매수<" not in text
    assert ">매도<" not in text
    assert ">주문<" not in text
    assert ">전략<" not in text
    assert ">LIVE<" not in text
    assert ">ARM<" not in text


def test_assessment_consensus_queue_links() -> None:
    for rel in (
        "frontend/src/app/(admin)/admin/ai/candidate-assessments/page.tsx",
        "frontend/src/app/(admin)/admin/ai/candidate-consensuses/page.tsx",
    ):
        text = Path(rel).read_text(encoding="utf-8")
        assert "검토 큐 등록" in text
        assert "aiCandidateRecommendationQueues" in text
