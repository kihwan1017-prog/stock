"""Derived clone provenance — unit regression (test DB 불필요)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from stock_platform.ai.strategy_draft_approval.explainability import (
    _EvidenceCollector,
    _build_provenance_evidence,
)
from stock_platform.ai.strategy_draft_approval.readiness import (
    resolve_strategy_provenance,
)

pytestmark = pytest.mark.unit


def _derived_definition(**overrides):
    row = MagicMock()
    row.strategy_id = 17579
    row.source_strategy_id = 17486
    row.definition_hash = "hash-clone"
    row.definition_version = 1
    row.approval_id = 212
    row.strategy_request_id = 23766
    row.candidate_id = 875
    row.candidate_fingerprint = "fp" * 32
    for key, value in overrides.items():
        setattr(row, key, value)
    return row


def test_resolve_native_delegates_to_validate_provenance(monkeypatch) -> None:
    """D — native strategy는 draft-derived validate_provenance를 사용한다."""
    native = _derived_definition(source_strategy_id=None)

    monkeypatch.setattr(
        "stock_platform.ai.strategy_draft_approval.readiness._require_definition",
        lambda _s, _i: native,
    )
    monkeypatch.setattr(
        "stock_platform.ai.strategy_draft_approval.readiness.validate_provenance",
        lambda _s, sid: {
            "valid": True,
            "failures": [],
            "chain": {"strategy_definition_id": sid, "source_draft_id": 315},
        },
    )

    result = resolve_strategy_provenance(MagicMock(), 100)
    assert result["provenance_mode"] == "DRAFT_DERIVED"
    assert result["valid"] is True
    assert result["chain"]["source_draft_id"] == 315


def test_resolve_valid_derived_clone_passes(monkeypatch) -> None:
    """A — source equivalence 성공 시 provenance valid."""
    derived = _derived_definition()

    monkeypatch.setattr(
        "stock_platform.ai.strategy_draft_approval.readiness._require_definition",
        lambda _s, _i: derived,
    )
    monkeypatch.setattr(
        "stock_platform.ai.strategy_draft_approval.readiness.evaluate_derived_source_equivalence",
        lambda _s, _d: {
            "equivalent": True,
            "source_ready": True,
            "failures": [],
            "source_strategy_id": 17486,
            "evidence_inherited": False,
        },
    )

    result = resolve_strategy_provenance(MagicMock(), 17579)
    assert result["provenance_mode"] == "DERIVED_SOURCE_EQUIVALENCE"
    assert result["valid"] is True
    assert result["chain"]["derived_clone"] is True
    assert result["chain"]["source_strategy_id"] == 17486
    assert result["chain"]["source_equivalent"] is True


def test_resolve_tampered_derived_clone_blocks(monkeypatch) -> None:
    """B — equivalence 실패 clone은 provenance invalid."""
    derived = _derived_definition()

    monkeypatch.setattr(
        "stock_platform.ai.strategy_draft_approval.readiness._require_definition",
        lambda _s, _i: derived,
    )
    monkeypatch.setattr(
        "stock_platform.ai.strategy_draft_approval.readiness.evaluate_derived_source_equivalence",
        lambda _s, _d: {
            "equivalent": False,
            "source_ready": True,
            "failures": ["DERIVED_STRATEGY_PARAMETER_DRIFT:max_order_amount"],
            "source_strategy_id": 17486,
            "evidence_inherited": False,
        },
    )

    result = resolve_strategy_provenance(MagicMock(), 17579)
    assert result["valid"] is False
    assert "DERIVED_STRATEGY_PARAMETER_DRIFT:max_order_amount" in result["failures"]


def test_resolve_missing_source_blocks(monkeypatch) -> None:
    """C — source strategy 없음 → FAIL."""
    derived = _derived_definition(source_strategy_id=999999)

    monkeypatch.setattr(
        "stock_platform.ai.strategy_draft_approval.readiness._require_definition",
        lambda _s, _i: derived,
    )
    monkeypatch.setattr(
        "stock_platform.ai.strategy_draft_approval.readiness.evaluate_derived_source_equivalence",
        lambda _s, _d: {
            "equivalent": False,
            "source_ready": False,
            "failures": ["SOURCE_STRATEGY_MISSING"],
            "source_strategy_id": 999999,
            "evidence_inherited": False,
        },
    )

    result = resolve_strategy_provenance(MagicMock(), 17579)
    assert result["valid"] is False
    assert "SOURCE_STRATEGY_MISSING" in result["failures"]


def test_explainability_provenance_uses_resolver_for_derived_clone(monkeypatch) -> None:
    """Explainability provenance evidence가 resolver 결과를 반영한다."""
    monkeypatch.setattr(
        "stock_platform.ai.strategy_draft_approval.explainability.resolve_strategy_provenance",
        lambda _s, _sid: {
            "valid": True,
            "failures": [],
            "provenance_mode": "DERIVED_SOURCE_EQUIVALENCE",
            "chain": {
                "strategy_definition_id": 17579,
                "source_strategy_id": 17486,
                "derived_clone": True,
                "source_equivalent": True,
            },
        },
    )

    evidence = _EvidenceCollector()
    payload, outcome = _build_provenance_evidence(
        MagicMock(),
        17579,
        current_executable_hash="exec-hash",
        selected_executable_hashes={},
        evidence=evidence,
    )
    assert payload["all_provenance_matches"] is True
    assert payload["chain"]["derived_clone"] is True
    assert payload["chain"]["source_strategy_id"] == 17486
    assert outcome.summary_bucket == "POSITIVE"
