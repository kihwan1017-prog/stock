"""STEP 11-10 — Multi-AI Consensus tests (Mock/deterministic only)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from stock_platform.ai.candidate_consensus.calculation import (
    AIConsensusCalculationService,
    strip_forbidden_fields,
)
from stock_platform.ai.candidate_consensus.constants import (
    CONSENSUS_ENGINE_VERSION,
    FORBIDDEN_RESULT_KEYS,
    MAX_BATCH_DETERMINISTIC,
    MAX_MEMBERS,
    MIN_MEMBERS,
    REFERENCE_DISCLAIMER,
    WEIGHT_VERSION,
)
from stock_platform.ai.candidate_consensus.independence import (
    AIConsensusIndependenceService,
)
from stock_platform.ai.candidate_consensus.weight import AIConsensusWeightService
from stock_platform.ai.execution.constants import EXECUTABLE_TASK_TYPES
from stock_platform.ai.review.constants import SOURCE_TYPES


def test_migration_head() -> None:
    from tests.migration_helpers import assert_revision_is_ancestor_of_head

    versions = Path("database/alembic/versions")
    assert any(p.name.startswith("ac3d4e5f6a7b") for p in versions.glob("*.py"))
    assert_revision_is_ancestor_of_head("ae5f6a7b8c9d")


def test_consensus_tasks_executable() -> None:
    assert "STOCK_CANDIDATE_CONSENSUS" in EXECUTABLE_TASK_TYPES
    assert "CRYPTO_CANDIDATE_CONSENSUS" in EXECUTABLE_TASK_TYPES


def test_review_source_includes_consensus() -> None:
    assert "CANDIDATE_CONSENSUS" in SOURCE_TYPES


def test_constants() -> None:
    assert CONSENSUS_ENGINE_VERSION.startswith("11.10")
    assert WEIGHT_VERSION.startswith("weight-")
    assert MIN_MEMBERS == 2
    assert MAX_MEMBERS == 5
    assert MAX_BATCH_DETERMINISTIC == 100
    assert "참고용" in REFERENCE_DISCLAIMER


def test_forbidden_fields_stripped() -> None:
    cleaned, violations = strip_forbidden_fields(
        {
            "summary": "ok",
            "buy": True,
            "recommendation": "hold",
            "target_price": 100,
        }
    )
    assert "buy" not in cleaned
    assert "recommendation" not in cleaned
    assert violations
    assert "buy" in FORBIDDEN_RESULT_KEYS


def test_independence_classify() -> None:
    svc = AIConsensusIndependenceService()
    members = [
        {"provider_code": "openai", "model": "gpt-4"},
        {"provider_code": "anthropic", "model": "claude-3"},
    ]
    result = svc.classify(members)
    assert all(r["independence_status"] == "INDEPENDENT" for r in result)

    dup = svc.classify(
        [
            {"provider_code": "openai", "model": "gpt-4"},
            {"provider_code": "openai", "model": "gpt-4"},
        ]
    )
    assert dup[0]["independence_status"] == "DUPLICATE"

    family = svc.classify(
        [
            {"provider_code": "openai", "model": "gpt-4"},
            {"provider_code": "openai_compatible", "model": "llama"},
        ]
    )
    assert all(r["independence_status"] == "SAME_PROVIDER_FAMILY" for r in family)


def test_weight_and_calculation() -> None:
    members = [
        {
            "assessment_id": 1,
            "included": True,
            "provider_code": "openai",
            "model": "gpt-4",
            "review_decision": "APPROVED",
            "analytical_score": 70,
            "risk_score": 40,
            "confidence": 0.8,
            "conflict_status": "NO_CONFLICT",
            "data_quality": "HIGH",
            "result_body": {
                "positive_factors": [{"code": "growth", "summary": "ok"}],
                "risk_factors": [],
            },
            "independence_status": "INDEPENDENT",
            "provider_family": "openai",
        },
        {
            "assessment_id": 2,
            "included": True,
            "provider_code": "anthropic",
            "model": "claude-3",
            "review_decision": "APPROVED",
            "analytical_score": 75,
            "risk_score": 45,
            "confidence": 0.75,
            "conflict_status": "NO_CONFLICT",
            "data_quality": "HIGH",
            "result_body": {
                "positive_factors": [{"code": "growth", "summary": "ok2"}],
                "risk_factors": [],
            },
            "independence_status": "INDEPENDENT",
            "provider_family": "anthropic",
        },
    ]
    classified = AIConsensusIndependenceService().classify(members)
    weighted = AIConsensusWeightService(MagicMock()).compute_weights(classified)
    outcome = AIConsensusCalculationService().calculate(weighted)
    assert outcome["ok"] is True
    assert outcome["external_ai_called"] is False
    assert 0 <= outcome["analytical_score"] <= 100
    assert outcome["agreement_level"] == "STRONG_AGREEMENT"


def test_create_does_not_auto_calculate() -> None:
    from stock_platform.ai.candidate_consensus.service import AIConsensusService

    session = MagicMock()
    session.scalar.return_value = None
    svc = AIConsensusService(session)
    selection = {
        "eligible": True,
        "included": [
            {
                "assessment_id": 1,
                "market_type": "STOCK",
                "exchange_code": "KRX",
                "symbol": "005930",
                "instrument_key": "KRX:005930",
                "assessment_type": "STOCK",
                "evidence_bundle_hash": "abc",
                "result_hash": "h1",
                "provider_code": "mock",
                "model": "mock-v1",
                "assessment_status": "VALIDATED",
            },
            {
                "assessment_id": 2,
                "market_type": "STOCK",
                "exchange_code": "KRX",
                "symbol": "005930",
                "instrument_key": "KRX:005930",
                "assessment_type": "STOCK",
                "evidence_bundle_hash": "abc",
                "result_hash": "h2",
                "provider_code": "openai",
                "model": "gpt-4",
                "assessment_status": "VALIDATED",
            },
        ],
        "excluded": [],
        "warnings": [],
        "instrument": {
            "market_type": "STOCK",
            "exchange_code": "KRX",
            "symbol": "005930",
            "instrument_key": "KRX:005930",
            "assessment_type": "STOCK",
        },
        "evidence_bundle_hash": "abc",
    }
    with (
        patch.object(svc._eligibility, "select_members", return_value=selection),
        patch.object(svc, "_store_member_rows"),
        patch.object(svc, "_history"),
        patch.object(
            svc,
            "_public",
            return_value={"consensus_status": "DRAFT", "id": 1},
        ),
    ):
        result = svc.create(
            actor="admin:1",
            reason="draft only",
            assessment_ids=[1, 2],
            idempotency_key="idem-1",
        )
    assert result["consensus"]["consensus_status"] == "DRAFT"


def test_batch_limit() -> None:
    from stock_platform.ai.candidate_consensus.batch_service import (
        AIConsensusBatchService,
    )
    from stock_platform.ai.candidate_consensus.service import AIConsensusError

    svc = AIConsensusBatchService(MagicMock())
    big_map = {f"KRX:{i:06d}": [1, 2] for i in range(101)}
    with pytest.raises(AIConsensusError) as exc:
        svc.create_batch(
            actor="admin:1",
            reason="batch",
            instrument_assessments=big_map,
            idempotency_key="b1",
        )
    assert exc.value.code == "BATCH_LIMIT"


def test_no_strategy_imports() -> None:
    root = Path("src/stock_platform/ai/candidate_consensus")
    banned = (
        "strategy.candidate",
        "CandidateAnalysisOrchestrator",
        "CandidatePositionPlan",
    )
    offenders: list[str] = []
    for path in root.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        for token in banned:
            if token in text:
                offenders.append(f"{path}:{token}")
    assert offenders == []


def test_seed_consensus_prompts_present() -> None:
    from stock_platform.ai.prompt import seed_data

    codes = {p["code"] for p in seed_data.SEED_PROMPTS}
    schemas = {s["code"] for s in seed_data.SEED_SCHEMAS}
    assert "STOCK_CANDIDATE_CONSENSUS_BASE" in codes
    assert "CRYPTO_CANDIDATE_CONSENSUS_BASE" in codes
    assert "STOCK_CANDIDATE_CONSENSUS_RESULT_V1" in schemas
    assert "CRYPTO_CANDIDATE_CONSENSUS_RESULT_V1" in schemas


def test_api_router_registered() -> None:
    from stock_platform.api.router import _ROUTER_GROUPS

    prefixes = {getattr(r, "prefix", "") for r in _ROUTER_GROUPS}
    assert "/api/v1/admin/ai/candidate-consensuses" in prefixes


def test_dashboard_block_wired() -> None:
    src = Path(
        "src/stock_platform/operation/operations_center_dashboard_service.py"
    ).read_text(encoding="utf-8")
    assert "ai_candidate_consensuses" in src
    assert "_ai_candidate_consensuses_block" in src
    assert "external_calls_on_read" in src


def test_telegram_readonly_command() -> None:
    src = Path(
        "src/stock_platform/notification/telegram_commands.py"
    ).read_text(encoding="utf-8")
    assert "/ai_consensus" in src
    status = Path(
        "src/stock_platform/notification/telegram_status.py"
    ).read_text(encoding="utf-8")
    assert "build_ai_consensus_text" in status
    assert "forbidden" in status.lower()


def test_frontend_page_exists() -> None:
    path = Path(
        "frontend/src/app/(admin)/admin/ai/candidate-consensuses/page.tsx"
    )
    assert path.exists()
    text = path.read_text(encoding="utf-8")
    assert "REFERENCE_DISCLAIMER" in text
    assert "품질 승인" in text
    assert "title={REFERENCE_DISCLAIMER}" in text
    assert "addonBefore" not in text
    assert "rowKey" in text
    assert ", index" not in text
    # 면책 문구에는 '후보 등록'이 포함될 수 있음 — 금지 버튼만 검사
    assert ">후보 등록<" not in text
    assert ">매수<" not in text
    assert ">매도<" not in text
    assert ">주문<" not in text
    assert ">전략 생성<" not in text
