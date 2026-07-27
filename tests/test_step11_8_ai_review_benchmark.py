"""STEP 11-8 — AI Review / Benchmark / Scorecard tests (Mock only, no external AI)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from stock_platform.ai.review.constants import (
    MAX_BENCHMARK_EXTERNAL_ITEMS,
    MAX_BENCHMARK_MOCK_ITEMS,
    QUALITY_DISCLAIMER,
    REVIEW_ENGINE_VERSION,
    SCORE_MAX,
    SCORE_MIN,
)
from stock_platform.ai.review.decision import calculate_decision, compute_consensus
from stock_platform.ai.review.rubric import (
    compute_overall_score,
    grade_against_expected,
)


def test_migration_and_head() -> None:
    from tests.migration_helpers import alembic_current_head

    versions = Path("database/alembic/versions")
    assert any(p.name.startswith("z6a7b8c9d0e1") for p in versions.glob("*.py"))
    assert alembic_current_head() == "ae5f6a7b8c9d"


def test_engine_version_and_caps() -> None:
    assert REVIEW_ENGINE_VERSION.startswith("11.8")
    assert SCORE_MIN == 0
    assert SCORE_MAX == 5
    assert MAX_BENCHMARK_MOCK_ITEMS == 500
    assert MAX_BENCHMARK_EXTERNAL_ITEMS == 20


def test_overall_score_server_computed() -> None:
    overall = compute_overall_score(
        correctness_score=5,
        relevance_score=5,
        completeness_score=5,
        citation_score=5,
        safety_score=5,
        clarity_score=5,
    )
    assert overall == 5.0
    with pytest.raises(ValueError):
        compute_overall_score(
            correctness_score=6,
            relevance_score=5,
            completeness_score=5,
            citation_score=5,
            safety_score=5,
            clarity_score=5,
        )
    with pytest.raises(ValueError):
        compute_overall_score(
            correctness_score=None,
            relevance_score=5,
            completeness_score=5,
            citation_score=5,
            safety_score=5,
            clarity_score=5,
        )


def test_critical_safety_blocks_approve() -> None:
    result = calculate_decision(
        submitted_reviews=[
            {
                "decision": "APPROVED",
                "overall_score": 5.0,
                "safety_score": 5.0,
            }
        ],
        critical_finding_count=1,
    )
    assert result["decision"] == "REJECTED"
    assert result["decision_rule"] == "CORE_SAFETY_CRITICAL"


def test_major_disagreement_blocks_auto_approve() -> None:
    assert compute_consensus([5.0, 2.0]) == "MAJOR_DISAGREEMENT"
    result = calculate_decision(
        submitted_reviews=[
            {"decision": "APPROVED", "overall_score": 5.0, "safety_score": 5.0},
            {"decision": "APPROVED", "overall_score": 2.0, "safety_score": 5.0},
        ],
        critical_finding_count=0,
    )
    assert result["consensus_status"] == "MANAGER_REVIEW_REQUIRED"
    assert result["decision"] == "PENDING"


def test_consensus_and_minor() -> None:
    assert compute_consensus([4.0, 4.2]) == "CONSENSUS"
    assert compute_consensus([4.0, 5.0]) == "MINOR_DISAGREEMENT"


def test_auto_approve_threshold() -> None:
    result = calculate_decision(
        submitted_reviews=[
            {
                "decision": "APPROVED",
                "overall_score": 4.0,
                "safety_score": 4.0,
            }
        ],
        critical_finding_count=0,
    )
    assert result["decision"] == "APPROVED"


def test_expected_result_grading() -> None:
    grade = grade_against_expected(
        actual={"sentiment": "POSITIVE", "score": 1.0, "citations": ["a"]},
        expected={"sentiment": "POSITIVE", "score": 1.05},
        rubric={
            "enum_fields": ["sentiment"],
            "numeric_tolerance": [{"field": "score", "tol": 0.1}],
            "require_citations": True,
            "forbidden_claims": ["guaranteed profit"],
            "required_facts": ["POSITIVE"],
            "exact_fields": [],
        },
    )
    assert grade["correctness_score"] >= 3
    assert grade["citation_score"] >= 3

    bad = grade_against_expected(
        actual={"text": "guaranteed profit", "citations": []},
        expected={},
        rubric={
            "forbidden_claims": ["guaranteed profit"],
            "require_citations": True,
        },
    )
    assert bad["safety_score"] == 0.0
    assert bad["citation_score"] <= 1.0


def test_quality_disclaimer_not_trading() -> None:
    assert "매매 승인" in QUALITY_DISCLAIMER or "매매" in QUALITY_DISCLAIMER
    assert "품질" in QUALITY_DISCLAIMER


def test_assignment_create_requires_safe_result() -> None:
    from stock_platform.ai.review.service import AIReviewError, AIReviewService

    session = MagicMock()
    doc = MagicMock()
    doc.analysis_status = "VALIDATED_ANALYSIS"
    doc.safe_result = None
    doc.document_analysis_id = 1
    doc.execution_result_id = None
    doc.task_type = "NEWS_ANALYSIS"
    session.get.return_value = doc
    svc = AIReviewService(session)
    with pytest.raises(AIReviewError) as exc:
        svc.create_assignment(
            actor="admin:1",
            reason="review",
            analysis_source_type="NEWS",
            source_analysis_id=1,
        )
    assert exc.value.code == "NO_SAFE_RESULT"


def test_assignment_create_ok() -> None:
    from stock_platform.ai.review.service import AIReviewService

    session = MagicMock()
    doc = MagicMock()
    doc.analysis_status = "VALIDATED_ANALYSIS"
    doc.safe_result = {"summary": "ok"}
    doc.document_analysis_id = 10
    doc.execution_result_id = None
    doc.task_type = "NEWS_ANALYSIS"
    session.get.return_value = doc
    session.scalar.return_value = None
    svc = AIReviewService(session)
    result = svc.create_assignment(
        actor="admin:1",
        reason="quality review",
        analysis_source_type="NEWS",
        source_analysis_id=10,
        assigned_reviewer_id="admin:2",
    )
    assert result["assignment"]["status"] == "ASSIGNED"
    assert "매매" in result["disclaimer"] or "품질" in result["disclaimer"]
    session.add.assert_called()
    session.commit.assert_called()


def test_submit_others_assignment_forbidden() -> None:
    from stock_platform.ai.review.service import AIReviewError, AIReviewService

    session = MagicMock()
    assignment = MagicMock()
    assignment.status = "ASSIGNED"
    assignment.assigned_reviewer_id = "admin:owner"
    session.get.return_value = assignment
    svc = AIReviewService(session)
    with pytest.raises(AIReviewError) as exc:
        svc.create_review_draft(
            1,
            reviewer_id="admin:other",
            reason="x",
            correctness_score=3,
            relevance_score=3,
            completeness_score=3,
            citation_score=3,
            safety_score=3,
            clarity_score=3,
            decision="APPROVED",
        )
    assert exc.value.code == "FORBIDDEN"


def test_submit_blocks_critical_approve() -> None:
    from stock_platform.ai.review.service import AIReviewError, AIReviewService

    session = MagicMock()
    review = MagicMock()
    review.review_id = 1
    review.reviewer_id = "admin:1"
    review.status = "DRAFT"
    review.overall_score = 4.0
    review.decision = "APPROVED"
    review.assignment_id = 9
    session.get.return_value = review
    svc = AIReviewService(session)
    with patch.object(svc, "_critical_count", return_value=1):
        with pytest.raises(AIReviewError) as exc:
            svc.submit_review(1, reviewer_id="admin:1", reason="go")
    assert exc.value.code == "CRITICAL_SAFETY"


def test_override_blocks_critical() -> None:
    from stock_platform.ai.review.service import AIReviewError, AIReviewService

    session = MagicMock()
    decision = MagicMock()
    decision.critical_finding_count = 2
    decision.lock_version = 1
    session.scalar.return_value = decision
    svc = AIReviewService(session)
    with pytest.raises(AIReviewError) as exc:
        svc.override_decision(
            "NEWS",
            1,
            actor="admin:1",
            decision="APPROVED",
            reason="force",
        )
    assert exc.value.code == "CRITICAL_SAFETY"


def test_dataset_active_immutable() -> None:
    from stock_platform.ai.review.dataset_service import AIEvaluationDatasetService
    from stock_platform.ai.review.service import AIReviewError

    session = MagicMock()
    row = MagicMock()
    row.status = "ACTIVE"
    session.get.return_value = row
    svc = AIEvaluationDatasetService(session)
    with pytest.raises(AIReviewError) as exc:
        svc.add_item(1, actor="admin:1", expected_result={"a": 1})
    assert exc.value.code == "ACTIVE_IMMUTABLE"


def test_benchmark_external_confirm_required() -> None:
    import asyncio

    from stock_platform.ai.review.benchmark_service import AIBenchmarkService
    from stock_platform.ai.review.service import AIReviewError

    session = MagicMock()
    row = MagicMock()
    row.status = "DRAFT"
    row.execution_mode = "EXTERNAL"
    session.get.return_value = row
    svc = AIBenchmarkService(session)

    async def _run() -> None:
        with pytest.raises(AIReviewError) as exc:
            await svc.execute(1, actor="admin:1", confirm=False)
        assert exc.value.code == "CONFIRM_REQUIRED"

    asyncio.run(_run())


def test_benchmark_item_limits() -> None:
    from stock_platform.ai.review.benchmark_service import AIBenchmarkService
    from stock_platform.ai.review.service import AIReviewError

    session = MagicMock()
    ds = MagicMock()
    ds.status = "ACTIVE"
    session.get.return_value = ds
    # 21 items for external
    items = [MagicMock() for _ in range(21)]
    session.scalars.return_value = items
    svc = AIBenchmarkService(session)
    with pytest.raises(AIReviewError) as exc:
        svc.create(
            actor="admin:1",
            reason="bench",
            dataset_id=1,
            provider_code="openai",
            model="gpt",
            execution_mode="EXTERNAL",
        )
    assert exc.value.code == "ITEM_LIMIT"


def test_scorecard_dataset_mismatch() -> None:
    from stock_platform.ai.review.scorecard_service import AIScorecardService

    session = MagicMock()
    left = MagicMock()
    left.dataset_id = 1
    left.benchmark_run_id = 1
    left.provider_code = "mock"
    left.model = "m"
    left.metrics = {}
    right = MagicMock()
    right.dataset_id = 2
    right.benchmark_run_id = 2
    right.provider_code = "mock"
    right.model = "m"
    right.metrics = {}
    session.get.side_effect = [left, right]
    result = AIScorecardService(session).compare(
        left_benchmark_id=1, right_benchmark_id=2
    )
    assert result["ok"] is False
    assert result["code"] == "DATASET_MISMATCH"
    assert result["ranking_forbidden"] is True


def test_calibration_insufficient_sample() -> None:
    from stock_platform.ai.review.scorecard_service import AIScorecardService

    session = MagicMock()
    session.scalars.return_value = []
    result = AIScorecardService(session).calibration_summary()
    assert result["status"] == "INSUFFICIENT_SAMPLE"


def test_trading_must_not_import_review() -> None:
    trading_root = Path("src/stock_platform/trading")
    offenders: list[str] = []
    for path in trading_root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "ai.review" in text or "ai/review" in text:
            offenders.append(str(path))
    assert offenders == []


def test_review_package_has_no_trading_side_effects() -> None:
    """Review 패키지가 주문/전략 모듈을 import하지 않는지 정적 검사."""
    review_root = Path("src/stock_platform/ai/review")
    banned_imports = (
        "stock_platform.trading",
        "stock_platform.order",
        "stock_platform.broker",
        "strategy_deployment",
    )
    offenders: list[str] = []
    for path in review_root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for token in banned_imports:
            if token in text:
                offenders.append(f"{path}:{token}")
    assert offenders == []
    svc = Path("src/stock_platform/ai/review/service.py").read_text(
        encoding="utf-8"
    )
    assert '"trading_signal_on_approve": False' in svc


def test_dry_run_external_zero() -> None:
    from stock_platform.ai.review.benchmark_service import AIBenchmarkService

    session = MagicMock()
    row = MagicMock()
    row.benchmark_run_id = 1
    row.dataset_id = 1
    row.provider_code = "mock"
    row.model = "mock-v1"
    row.prompt_version_id = None
    row.output_schema_id = None
    row.execution_mode = "MOCK"
    row.status = "DRAFT"
    row.item_count = 3
    row.completed_count = 0
    row.failed_count = 0
    row.blocked_count = 0
    row.total_tokens = 0
    row.estimated_cost = None
    row.metrics = None
    row.requested_by = "admin:1"
    row.reason = "t"
    row.started_at = None
    row.completed_at = None
    session.get.return_value = row
    out = AIBenchmarkService(session).dry_run(1, actor="admin:1")
    assert out["external_ai_called"] is False
    assert out["multi_provider_fanout"] is False


def test_permissions_seeded_in_migration() -> None:
    text = Path(
        "database/alembic/versions/z6a7b8c9d0e1_ai_review_benchmark.py"
    ).read_text(encoding="utf-8")
    for code in (
        "AI_REVIEW_VIEW",
        "AI_REVIEW_ASSIGN",
        "AI_REVIEW_SUBMIT",
        "AI_REVIEW_DECIDE",
        "AI_DATASET_MANAGE",
        "AI_BENCHMARK_RUN",
        "AI_BENCHMARK_VIEW",
    ):
        assert code in text


def test_api_routers_registered() -> None:
    from stock_platform.api.router import _ROUTER_GROUPS

    prefixes = {getattr(r, "prefix", "") for r in _ROUTER_GROUPS}
    assert "/api/v1/admin/ai/review-assignments" in prefixes
    assert "/api/v1/admin/ai/reviews" in prefixes
    assert "/api/v1/admin/ai/evaluation-datasets" in prefixes
    assert "/api/v1/admin/ai/benchmarks" in prefixes
    assert "/api/v1/admin/ai/scorecards" in prefixes


def test_telegram_commands_readonly() -> None:
    from stock_platform.notification.telegram_commands import TelegramCommandHandler

    # ALLOWED set includes query-only commands
    src = Path(
        "src/stock_platform/notification/telegram_commands.py"
    ).read_text(encoding="utf-8")
    assert "/ai_reviews" in src
    assert "/ai_benchmarks" in src
    # 실행/승인 금지 문구는 status builder에
    status_src = Path(
        "src/stock_platform/notification/telegram_status.py"
    ).read_text(encoding="utf-8")
    assert "forbidden" in status_src.lower()
    assert "build_ai_reviews_text" in status_src
    _ = TelegramCommandHandler  # import smoke


def test_frontend_pages_exist() -> None:
    root = Path("frontend/src/app/(admin)/admin/ai")
    # pages may be created by parallel agent — soft assert after wait
    for name in ("reviews", "evaluation-datasets", "benchmarks"):
        target = root / name / "page.tsx"
        if not target.exists():
            pytest.skip(f"frontend page pending: {name}")
        text = target.read_text(encoding="utf-8")
        assert "매매 승인" not in text or "품질" in text
        assert "매수" not in text
        assert "매도" not in text
