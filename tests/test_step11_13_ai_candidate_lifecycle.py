"""STEP 11-13 — AI Candidate Lifecycle & Provenance tests."""

from __future__ import annotations

from pathlib import Path

from stock_platform.ai.candidate_lifecycle.constants import LIFECYCLE_STATUS
from stock_platform.ai.candidate_lifecycle.revalidation import compare_fingerprints
from stock_platform.ai.candidate_lifecycle.transitions import can_transition
from stock_platform.ai.execution.constants import EXECUTABLE_TASK_TYPES


def test_migration_head() -> None:
    from tests.migration_helpers import alembic_current_head

    versions = Path("database/alembic/versions")
    assert any(p.name.startswith("ae5f6a7b8c9d") for p in versions.glob("*.py"))
    assert alembic_current_head() == "ae5f6a7b8c9d"


def test_constants_and_transitions() -> None:
    assert "PROMOTED" in LIFECYCLE_STATUS
    assert "ACTIVE_REVIEW" in LIFECYCLE_STATUS
    assert can_transition("PROMOTED", "ACTIVE_REVIEW") is True
    assert can_transition("PROMOTED", "REVOKED") is True


def test_fingerprint_compare() -> None:
    fp = "abc123" * 10 + "abcd"
    matched = compare_fingerprints(expected=fp, actual=fp)
    assert matched["matched"] is True
    assert matched["status"] == "PASSED"

    mismatched = compare_fingerprints(expected=fp, actual=fp + "x")
    assert mismatched["matched"] is False
    assert mismatched["status"] == "FAILED"
    assert "FINGERPRINT_MISMATCH" in mismatched["warnings"]


def test_no_new_execution_tasks() -> None:
    assert "CANDIDATE_LIFECYCLE" not in EXECUTABLE_TASK_TYPES
    assert "LIFECYCLE_REVALIDATION" not in EXECUTABLE_TASK_TYPES


def test_api_modules_and_prefixes() -> None:
    router_src = Path("src/stock_platform/api/router.py").read_text(encoding="utf-8")
    assert "admin_ai_candidate_lifecycle_router" in router_src
    assert "admin_ai_candidate_lifecycle_candidates_router" in router_src
    assert "user_ai_candidate_lifecycle_router" in router_src

    admin_src = Path(
        "src/stock_platform/api/v1/admin_ai_candidate_lifecycle.py"
    ).read_text(encoding="utf-8")
    assert 'prefix="/api/v1/admin/ai/candidate-lifecycle"' in admin_src
    assert 'prefix="/api/v1/admin/ai/candidates"' in admin_src
    assert "CANDIDATE_EXPIRED" in admin_src
    assert "CANDIDATE_LIFECYCLE_STATUS_CHANGED" in admin_src

    user_src = Path(
        "src/stock_platform/api/v1/user_ai_candidate_lifecycle.py"
    ).read_text(encoding="utf-8")
    assert 'prefix="/api/v1/user/ai-candidates"' in user_src


def test_dashboard_and_telegram_wired() -> None:
    dash = Path(
        "src/stock_platform/operation/operations_center_dashboard_service.py"
    ).read_text(encoding="utf-8")
    assert "ai_candidate_lifecycle" in dash
    assert "_ai_candidate_lifecycle_block" in dash
    cmds = Path(
        "src/stock_platform/notification/telegram_commands.py"
    ).read_text(encoding="utf-8")
    assert "/ai_candidate_lifecycle" in cmds
    status = Path(
        "src/stock_platform/notification/telegram_status.py"
    ).read_text(encoding="utf-8")
    assert "build_ai_candidate_lifecycle_text" in status
    assert "forbidden" in status.lower()


def test_frontend_page() -> None:
    path = Path(
        "frontend/src/app/(admin)/admin/ai/candidate-lifecycle/page.tsx"
    )
    assert path.exists()
    text = path.read_text(encoding="utf-8")
    assert "App.useApp()" in text
    assert "REFERENCE_DISCLAIMER" in text
    assert "title={REFERENCE_DISCLAIMER}" in text
    assert "Expire" in text
    assert ">매수<" not in text
    assert ">매도<" not in text


def test_docs_soft_expire_only() -> None:
    doc = Path(
        "docs/ai/STEP11_13_AI_CANDIDATE_LIFECYCLE_PROVENANCE.md"
    ).read_text(encoding="utf-8")
    lowered = doc.lower()
    assert "soft" in lowered
    assert "expire/revoke" in lowered or "soft expire" in lowered
    assert "ae5f6a7b8c9d" in doc


def test_step11_12_migration_still_exists() -> None:
    from tests.migration_helpers import alembic_current_head

    versions = Path("database/alembic/versions")
    assert any(p.name.startswith("ad4e5f6a7b8c") for p in versions.glob("*.py"))
    assert alembic_current_head() == "ae5f6a7b8c9d"


def test_promotion_commit_calls_ensure_lifecycle() -> None:
    src = Path("src/stock_platform/ai/candidate_promotion/service.py").read_text(
        encoding="utf-8"
    )
    assert "ensure_lifecycle" in src
    assert "candidate_result.result_id" in src
