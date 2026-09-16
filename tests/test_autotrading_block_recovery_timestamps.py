"""Block event recovery timestamp semantics — no invented schedules."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from stock_platform.trading.autotrading_block_event import AutotradingBlockEventService


class _FakeSession:
    pass


def test_open_block_has_no_invented_schedule_or_attempt() -> None:
    svc = AutotradingBlockEventService(_FakeSession())  # type: ignore[arg-type]
    blocked = datetime(2026, 9, 6, 0, 9, 56, tzinfo=timezone.utc)
    open_row = SimpleNamespace(
        event_id=9,
        blocked_at=blocked,
        primary_reason_code="LIVE_OFF",
        primary_reason_text="실거래 사용 상태가 꺼져 있습니다.",
        secondary_reasons_json=["ARM_OFF"],
        kill_switch_scope=None,
        kill_switch_reason=None,
        source_component="ops_status",
    )

    def latest_open(**_kw):
        return open_row

    def latest_resolved(**_kw):
        return None

    svc.latest_open = latest_open  # type: ignore[method-assign]
    svc.latest_resolved = latest_resolved  # type: ignore[method-assign]
    payload = svc.ui_payload(user_broker_account_id=1380)
    assert payload["status"] == "BLOCKED"
    assert payload["blocked_at"]
    assert payload["recovery_scheduled_at"] is None
    assert payload["next_retry_at"] is None
    assert payload["recovery_attempted_at"] is None
    assert payload["recovery_started_at"] is None
    assert payload["recovered_at"] is None
    assert payload["recovery_status"] == "AWAITING_OPERATOR"
    assert payload["recovery_method"] == "NOT_ATTEMPTED"


def test_resolved_operator_approved_method() -> None:
    svc = AutotradingBlockEventService(_FakeSession())  # type: ignore[arg-type]
    blocked = datetime(2026, 9, 6, 0, 9, 56, tzinfo=timezone.utc)
    recovered = datetime(2026, 9, 6, 1, 0, 0, tzinfo=timezone.utc)
    resolved = SimpleNamespace(
        event_id=10,
        blocked_at=blocked,
        unblocked_at=recovered,
        resolved_at=recovered,
        primary_reason_code="LIVE_OFF",
        primary_reason_text="x",
        secondary_reasons_json=[],
        resolution_type="OPERATOR_APPROVED",
    )

    svc.latest_open = lambda **_kw: None  # type: ignore[method-assign]
    svc.latest_resolved = lambda **_kw: resolved  # type: ignore[method-assign]
    payload = svc.ui_payload(user_broker_account_id=1380)
    assert payload["status"] == "RESOLVED"
    assert payload["recovery_method"] == "OPERATOR_APPROVED"
    assert payload["recovery_status"] == "SUCCESS"
    assert payload["recovered_at"]
    assert payload["recovery_scheduled_at"] is None
