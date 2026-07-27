"""STEP 11-9 — AI Candidate Assessment Draft tests (Mock only)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from stock_platform.ai.candidate_assessment.constants import (
    ASSESSMENT_ENGINE_VERSION,
    FORBIDDEN_RESULT_KEYS,
    MAX_BATCH_EXTERNAL,
    MAX_BATCH_MOCK,
    MAX_CONFIDENCE_MAJOR_CONFLICT,
    REFERENCE_DISCLAIMER,
)
from stock_platform.ai.candidate_assessment.eligibility import (
    AICandidateEligibilityService,
)
from stock_platform.ai.candidate_assessment.scoring import (
    apply_confidence_caps,
    clamp_score,
    compute_analytical_score,
    strip_forbidden_fields,
    validate_result_payload,
)
from stock_platform.ai.execution.constants import (
    BLOCKED_TASK_TYPES,
    EXECUTABLE_TASK_TYPES,
)
from stock_platform.ai.review.constants import SOURCE_TYPES


def test_migration_and_head() -> None:
    from tests.migration_helpers import alembic_current_head

    versions = Path("database/alembic/versions")
    assert any(p.name.startswith("aa1b2c3d4e5f") for p in versions.glob("*.py"))
    assert alembic_current_head() == "ae5f6a7b8c9d"


def test_candidate_tasks_executable() -> None:
    assert "STOCK_CANDIDATE_ANALYSIS" in EXECUTABLE_TASK_TYPES
    assert "CRYPTO_CANDIDATE_ANALYSIS" in EXECUTABLE_TASK_TYPES
    assert "STRATEGY_DRAFT" in BLOCKED_TASK_TYPES
    assert "RISK_REVIEW" in BLOCKED_TASK_TYPES


def test_review_source_includes_candidate_assessment() -> None:
    assert "CANDIDATE_ASSESSMENT" in SOURCE_TYPES


def test_batch_caps() -> None:
    assert MAX_BATCH_MOCK == 100
    assert MAX_BATCH_EXTERNAL == 10
    assert ASSESSMENT_ENGINE_VERSION.startswith("11.9")


def test_disclaimer_not_trading() -> None:
    assert "참고용" in REFERENCE_DISCLAIMER
    assert "매매 후보" in REFERENCE_DISCLAIMER or "주문" in REFERENCE_DISCLAIMER


def test_eligibility_stock_krx() -> None:
    svc = AICandidateEligibilityService(MagicMock())
    result = svc.validate(
        market_type="STOCK",
        exchange_code="KRX",
        symbol="005930",
    )
    assert result["allowed"] is True
    assert result["assessment_type"] == "STOCK"


def test_eligibility_crypto_upbit() -> None:
    svc = AICandidateEligibilityService(MagicMock())
    result = svc.validate(
        market_type="CRYPTO",
        exchange_code="UPBIT",
        symbol="KRW-BTC",
    )
    assert result["allowed"] is True
    assert result["assessment_type"] == "CRYPTO"


def test_eligibility_market_mismatch() -> None:
    svc = AICandidateEligibilityService(MagicMock())
    result = svc.validate(
        market_type="STOCK",
        exchange_code="UPBIT",
        symbol="005930",
    )
    assert result["allowed"] is False


def test_forbidden_fields_stripped() -> None:
    cleaned, violations = strip_forbidden_fields(
        {
            "summary": "ok",
            "buy": True,
            "sell": False,
            "target_price": 100,
            "candidate_approved": True,
            "analytical_score": 50,
        }
    )
    assert "buy" not in cleaned
    assert "sell" not in cleaned
    assert "target_price" not in cleaned
    assert "candidate_approved" not in cleaned
    assert cleaned["summary"] == "ok"
    assert violations
    for key in ("buy", "sell", "target_price", "candidate_approved"):
        assert key in FORBIDDEN_RESULT_KEYS


def test_scores_and_confidence_caps() -> None:
    assert clamp_score(150) == 100
    assert clamp_score(-1) == 0
    overall = compute_analytical_score(
        {
            "news_score": 80,
            "disclosure_score": 70,
            "chart_score": 60,
            "market_score": 50,
            "evidence_quality_score": 90,
        }
    )
    assert 0 <= overall <= 100
    capped = apply_confidence_caps(
        0.95,
        has_review=False,
        conflict_status="MAJOR_CONFLICT",
        temporal_status="STALE",
        metadata_only=True,
    )
    assert capped <= MAX_CONFIDENCE_MAJOR_CONFLICT


def test_validate_result_payload() -> None:
    findings = validate_result_payload(
        {"buy": 1, "summary": "x"},
        task_type="STOCK_CANDIDATE_ANALYSIS",
    )
    assert findings


def test_create_does_not_auto_execute() -> None:
    from stock_platform.ai.candidate_assessment.service import (
        AICandidateAssessmentService,
    )

    session = MagicMock()
    session.scalar.return_value = None
    svc = AICandidateAssessmentService(session)
    create_request = MagicMock(return_value={"request": {"id": 99}})
    svc._exec.create_request = create_request
    with (
        patch.object(
            svc._eligibility,
            "validate",
            return_value={
                "allowed": True,
                "assessment_type": "STOCK",
                "market_type": "STOCK",
                "exchange_code": "KRX",
                "symbol": "005930",
                "instrument_id": None,
                "instrument_key": "KRX:005930",
                "warnings": [],
                "reasons": [],
            },
        ),
        patch.object(
            svc._evidence,
            "build_bundle",
            return_value={
                "ok": True,
                "items": [],
                "hash": "abc",
                "temporal_status": "UNKNOWN",
                "conflict_status": "INSUFFICIENT_EVIDENCE",
                "evidence_quality": "LOW",
                "data_quality": "UNKNOWN",
                "counts": {
                    "news": 0,
                    "disclosure": 0,
                    "chart": 0,
                    "market": 0,
                    "included": 0,
                },
            },
        ),
        patch.object(
            svc,
            "_resolve_prompt_config",
            return_value={
                "eligible": True,
                "blockers": [],
                "task_type": "STOCK_CANDIDATE_ANALYSIS",
                "prompt_template_id": 1,
                "prompt_version_id": 1,
                "schema_id": 1,
                "policy_ids": [],
            },
        ),
        patch.object(svc, "_store_evidence_rows"),
        patch.object(svc, "_history"),
        patch.object(svc, "_public", return_value={"assessment_status": "DRAFT", "id": 1}),
    ):
        result = svc.create(
            actor="admin:1",
            reason="draft only",
            market_type="STOCK",
            exchange_code="KRX",
            symbol="005930",
            idempotency_key="idem-1",
            execution_mode="MOCK",
        )
    assert result["assessment"]["assessment_status"] == "DRAFT"
    create_request.assert_called_once()


def test_batch_external_limit() -> None:
    from stock_platform.ai.candidate_assessment.batch_service import (
        AICandidateAssessmentBatchService,
    )
    from stock_platform.ai.candidate_assessment.service import (
        AICandidateAssessmentError,
    )

    svc = AICandidateAssessmentBatchService(MagicMock())
    instruments = [{"symbol": f"S{i}"} for i in range(11)]
    with pytest.raises(AICandidateAssessmentError) as exc:
        svc.create_batch(
            actor="admin:1",
            reason="batch",
            market_type="STOCK",
            exchange_code="KRX",
            instruments=instruments,
            execution_mode="EXTERNAL",
            provider_code="openai",
            model="gpt",
            prompt_version_id=None,
            confirm=True,
            idempotency_key="b1",
        )
    assert exc.value.code == "BATCH_LIMIT"


def test_trading_must_not_import_candidate_assessment() -> None:
    for root_name in ("trading", "order", "screener", "scheduler"):
        root = Path(f"src/stock_platform/{root_name}")
        if not root.exists():
            continue
        offenders: list[str] = []
        for path in root.rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            if "candidate_assessment" in text:
                offenders.append(str(path))
        assert offenders == [], offenders


def test_candidate_assessment_no_legacy_candidate_write() -> None:
    root = Path("src/stock_platform/ai/candidate_assessment")
    banned = (
        "strategy.candidate",
        "CandidateAnalysisOrchestrator",
        "CandidatePositionPlan",
        "position_plan",
    )
    offenders: list[str] = []
    for path in root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for token in banned:
            if token in text:
                offenders.append(f"{path}:{token}")
    assert offenders == []
    # 금지 필드 목록에 submit_order가 있는 것은 정상 (차단용)
    from stock_platform.ai.candidate_assessment.constants import FORBIDDEN_RESULT_KEYS

    assert "submit_order" in FORBIDDEN_RESULT_KEYS


def test_api_router_registered() -> None:
    from stock_platform.api.router import _ROUTER_GROUPS

    prefixes = {getattr(r, "prefix", "") for r in _ROUTER_GROUPS}
    assert "/api/v1/admin/ai/candidate-assessments" in prefixes


def test_telegram_readonly_command() -> None:
    src = Path(
        "src/stock_platform/notification/telegram_commands.py"
    ).read_text(encoding="utf-8")
    assert "/ai_candidate_assessments" in src
    status = Path(
        "src/stock_platform/notification/telegram_status.py"
    ).read_text(encoding="utf-8")
    assert "build_ai_candidate_assessments_text" in status
    assert "forbidden" in status.lower()


def test_frontend_page_exists() -> None:
    path = Path(
        "frontend/src/app/(admin)/admin/ai/candidate-assessments/page.tsx"
    )
    assert path.exists()
    text = path.read_text(encoding="utf-8")
    assert "참고용" in text
    assert "품질 승인" in text or "AI 후보 평가" in text
    assert "후보 등록" not in text
    assert ">매수<" not in text
    assert ">매도<" not in text
    assert 'children: "매수"' not in text
    assert 'children: "매도"' not in text


def test_seed_prompts_present() -> None:
    from stock_platform.ai.prompt import seed_data

    codes = {p["code"] for p in seed_data.SEED_PROMPTS}
    schemas = {s["code"] for s in seed_data.SEED_SCHEMAS}
    assert "STOCK_CANDIDATE_ASSESSMENT_BASE" in codes
    assert "CRYPTO_CANDIDATE_ASSESSMENT_BASE" in codes
    assert "STOCK_CANDIDATE_ASSESSMENT_RESULT_V1" in schemas
    assert "CRYPTO_CANDIDATE_ASSESSMENT_RESULT_V1" in schemas
