"""AutoTrading process version / trace — observability unit tests."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

from stock_platform.operation.autotrading_process_version.constants import (
    CHANGE_OBSERVABILITY,
    CHANGE_UI,
    STATUS_ACTIVE,
    STATUS_RETIRED,
)
from stock_platform.operation.autotrading_process_version.service import (
    _fingerprint,
    _scrub_secrets,
    append_trace_event_fail_open,
    assert_historical_immutable,
)


def test_fingerprint_stable_and_secret_excluded() -> None:
    a = _fingerprint({"x": 1, "components": {"ENTRY": {"version_code": "V1"}}})
    b = _fingerprint({"components": {"ENTRY": {"version_code": "V1"}}, "x": 1})
    assert a == b
    scrubbed = _scrub_secrets(
        {"rsi_max": 70, "api_key": "SECRET", "telegram_token": "t"}
    )
    assert "api_key" not in scrubbed
    assert "telegram_token" not in scrubbed
    assert scrubbed["rsi_max"] == 70


def test_ui_only_change_type_does_not_imply_real_policy() -> None:
    assert CHANGE_UI != CHANGE_OBSERVABILITY
    # REAL process semantics version must not bump for UI-only (policy enum check)
    assert CHANGE_UI == "UI_ONLY"


def test_historical_retired_version_immutable_helper() -> None:
    session = MagicMock()
    row = MagicMock()
    row.status = STATUS_RETIRED
    session.get.return_value = row
    assert assert_historical_immutable(session, process_version_id=1) is True


def test_trace_persist_fail_open() -> None:
    session = MagicMock()
    session.commit.side_effect = RuntimeError("db down")
    out = append_trace_event_fail_open(
        session,
        trace_id=1,
        market="UPBIT",
        symbol="KRW-X",
        stage="ORDER",
        event_type="CREATE",
        occurred_at=datetime.now(timezone.utc),
        status="PASS",
        reason_code=None,
        summary="x",
        process_version_id=1,
        source_refs={},
    )
    assert out["ok"] is False
    assert out["code"] == "AUTOTRADING_TRACE_PERSIST_FAILED"


def test_active_status_constant() -> None:
    assert STATUS_ACTIVE == "ACTIVE"
