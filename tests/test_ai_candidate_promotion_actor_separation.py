"""Promotion dual-approval actor 분리 — DB/HTTP 없이 계약만 검증."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from stock_platform.ai.candidate_promotion.service import (
    AICandidatePromotionError,
    AICandidatePromotionService,
)


def _svc() -> AICandidatePromotionService:
    return AICandidatePromotionService.__new__(AICandidatePromotionService)


def test_requester_cannot_first_approve() -> None:
    svc = _svc()
    row = SimpleNamespace(requested_by="admin:7")
    with pytest.raises(AICandidatePromotionError) as exc:
        svc._assert_actor_separation(row, "admin:7", stage="FIRST")
    assert exc.value.code == "SELF_APPROVAL_BLOCKED"


def test_other_admin_can_first_approve() -> None:
    svc = _svc()
    row = SimpleNamespace(requested_by="admin:7")
    svc._assert_actor_separation(row, "admin:564", stage="FIRST")


def test_first_approver_cannot_final_approve() -> None:
    svc = _svc()
    row = SimpleNamespace(requested_by="admin:7")
    with pytest.raises(AICandidatePromotionError) as exc:
        svc._assert_actor_separation(
            row,
            "admin:564",
            stage="FINAL",
            first_approver="admin:564",
        )
    assert exc.value.code == "SELF_APPROVAL_BLOCKED"


def test_final_must_differ_from_requester_and_first() -> None:
    svc = _svc()
    row = SimpleNamespace(requested_by="admin:7")
    svc._assert_actor_separation(
        row,
        "admin:565",
        stage="FINAL",
        first_approver="admin:564",
    )


def test_dry_run_run_preview_jsonb_without_decimal() -> None:
    from datetime import date
    from types import SimpleNamespace
    import json

    from stock_platform.ai.candidate_promotion.mapping import (
        build_candidate_run_preview,
    )

    queue = SimpleNamespace(
        exchange_code="KRX",
        queue_id=1,
        market_type="STOCK",
        source_type="CANDIDATE_CONSENSUS",
    )
    preview = build_candidate_run_preview(
        queue=queue,  # type: ignore[arg-type]
        promotion_request_id=1,
        as_of_date=date(2026, 8, 19),
    )
    json.dumps(preview)  # default=str 없이 JSONB flush 가능해야 한다
    assert preview["minimum_score"] == "0"
    """commit()은 confirm=true 없으면 CONFIRM_REQUIRED — 이번 STEP에서 commit POST 금지 계약."""
    from inspect import signature

    sig = signature(AICandidatePromotionService.commit)
    assert "confirm" in sig.parameters
    assert "idempotency_key" in sig.parameters
