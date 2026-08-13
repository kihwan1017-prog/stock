"""Stale ACTIVE snapshot binding retire — focused unit tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from stock_platform.broker.snapshot_constants import BrokerSnapshotStatus
from stock_platform.broker.stale_snapshot_binding_retire_service import (
    APPROVAL_PHRASE,
    CLASS_ACTIVE,
    CLASS_PROTECTED,
    CLASS_SAFE,
    PROTECTED_SNAPSHOT_IDS,
    StaleSnapshotBindingRetireError,
    StaleSnapshotBindingRetireService,
)


def _snap(**kwargs):
    base = dict(
        broker_account_snapshot_id=151,
        user_broker_account_id=1338,
        broker_code="KIWOOM",
        snapshot_status=BrokerSnapshotStatus.ACTIVE.value,
        snapshot_generation=1,
        snapshot_time=datetime.now(timezone.utc) - timedelta(days=12),
        synchronized_at=datetime.now(timezone.utc) - timedelta(days=12),
        created_at=datetime.now(timezone.utc) - timedelta(days=12),
        raw_data={},
    )
    base.update(kwargs)
    return SimpleNamespace(**base)


def _uba(**kwargs):
    base = dict(
        user_broker_account_id=1338,
        is_active=False,
        deleted_at=datetime.now(timezone.utc),
        connection_status="DISCONNECTED",
        live_order_enabled=False,
        live_armed=False,
        account_alias="dead",
    )
    base.update(kwargs)
    return SimpleNamespace(**base)


def _service_with_triage(item):
    session = MagicMock()
    svc = StaleSnapshotBindingRetireService(session)
    svc._triage_one = MagicMock(return_value=item)  # type: ignore[method-assign]
    return svc, session


def _safe_item(sid=151, uba=1338):
    from stock_platform.broker.stale_snapshot_binding_retire_service import (
        SnapshotTriageItem,
    )

    return SnapshotTriageItem(
        snapshot_id=sid,
        classification=CLASS_SAFE,
        current_status="ACTIVE",
        stale_age_seconds=1_000_000,
        owner_uba=uba,
        broker_code="KIWOOM",
        generation=1,
        consumer_count=0,
        runtime_refs=0,
        order_refs_inflight=0,
        outbox_refs_active=0,
        newer_snapshot=False,
        retire_allowed=True,
        block_reason=None,
        evidence={"uba": uba},
    )


def test_preview_safe_stale_history_allowed() -> None:
    item = _safe_item()
    svc, _ = _service_with_triage(item)
    with patch(
        "stock_platform.broker.stale_snapshot_binding_retire_service.get_settings",
        return_value=SimpleNamespace(settlement_price_max_age_seconds=3600),
    ):
        preview = svc.preview([151])
    assert preview.allowlist == [151]
    assert preview.fingerprint
    assert preview.items[0].retire_allowed is True


def test_active_runtime_blocks() -> None:
    from stock_platform.broker.stale_snapshot_binding_retire_service import (
        SnapshotTriageItem,
    )

    item = SnapshotTriageItem(
        snapshot_id=151,
        classification=CLASS_ACTIVE,
        current_status="ACTIVE",
        stale_age_seconds=1_000_000,
        owner_uba=1338,
        broker_code="KIWOOM",
        generation=1,
        consumer_count=1,
        runtime_refs=1,
        order_refs_inflight=0,
        outbox_refs_active=0,
        newer_snapshot=False,
        retire_allowed=False,
        block_reason="ACTIVE_RUNTIME",
    )
    svc, _ = _service_with_triage(item)
    with patch(
        "stock_platform.broker.stale_snapshot_binding_retire_service.get_settings",
        return_value=SimpleNamespace(settlement_price_max_age_seconds=3600),
    ):
        preview = svc.preview([151])
    assert preview.allowlist == []
    assert preview.fingerprint is None


def test_active_consumer_blocks() -> None:
    from stock_platform.broker.stale_snapshot_binding_retire_service import (
        SnapshotTriageItem,
    )

    item = SnapshotTriageItem(
        snapshot_id=57,
        classification=CLASS_ACTIVE,
        current_status="ACTIVE",
        stale_age_seconds=900_000,
        owner_uba=58,
        broker_code="UPBIT",
        generation=539,
        consumer_count=2,
        runtime_refs=0,
        order_refs_inflight=0,
        outbox_refs_active=0,
        newer_snapshot=False,
        retire_allowed=False,
        block_reason="ACTIVE_STRATEGY_LINK",
    )
    svc, _ = _service_with_triage(item)
    with patch(
        "stock_platform.broker.stale_snapshot_binding_retire_service.get_settings",
        return_value=SimpleNamespace(settlement_price_max_age_seconds=3600),
    ):
        preview = svc.preview([57])
    assert 57 not in preview.allowlist


def test_fresh_snapshot_blocked_by_triage() -> None:
    session = MagicMock()
    snap = _snap(
        broker_account_snapshot_id=176,
        user_broker_account_id=1380,
        broker_code="UPBIT",
        snapshot_time=datetime.now(timezone.utc),
        synchronized_at=datetime.now(timezone.utc),
    )
    session.get.side_effect = lambda model, pk: snap if int(pk) == 176 else None
    svc = StaleSnapshotBindingRetireService(session)
    with patch(
        "stock_platform.broker.stale_snapshot_binding_retire_service.get_settings",
        return_value=SimpleNamespace(settlement_price_max_age_seconds=3600),
    ):
        item = svc._triage_one(176, max_age_seconds=3600)
    assert item.classification == CLASS_PROTECTED
    assert item.retire_allowed is False
    assert 176 in PROTECTED_SNAPSHOT_IDS


def test_uba1380_protected() -> None:
    session = MagicMock()
    snap = _snap(
        broker_account_snapshot_id=999,
        user_broker_account_id=1380,
        snapshot_time=datetime.now(timezone.utc) - timedelta(days=2),
    )
    session.get.side_effect = lambda model, pk: snap if int(pk) == 999 else None
    svc = StaleSnapshotBindingRetireService(session)
    item = svc._triage_one(999, max_age_seconds=3600)
    assert item.classification == CLASS_PROTECTED
    assert item.block_reason == "PROTECTED_OPS_SNAPSHOT"


def test_wrong_phrase_mutation_zero() -> None:
    item = _safe_item()
    svc, session = _service_with_triage(item)
    with patch(
        "stock_platform.broker.stale_snapshot_binding_retire_service.get_settings",
        return_value=SimpleNamespace(settlement_price_max_age_seconds=3600),
    ):
        with pytest.raises(StaleSnapshotBindingRetireError) as exc:
            svc.apply(
                snapshot_ids=[151],
                approval_phrase="WRONG",
                fingerprint="x" * 64,
                actor="admin",
            )
    assert exc.value.code == "INVALID_APPROVAL_PHRASE"
    assert exc.value.mutation == 0
    session.commit.assert_not_called()


def test_fingerprint_mismatch_mutation_zero() -> None:
    item = _safe_item()
    svc, _ = _service_with_triage(item)
    with patch(
        "stock_platform.broker.stale_snapshot_binding_retire_service.get_settings",
        return_value=SimpleNamespace(settlement_price_max_age_seconds=3600),
    ):
        with pytest.raises(StaleSnapshotBindingRetireError) as exc:
            svc.apply(
                snapshot_ids=[151],
                approval_phrase=APPROVAL_PHRASE,
                fingerprint="0" * 64,
                actor="admin",
            )
    assert exc.value.code == "FINGERPRINT_MISMATCH"
    assert exc.value.mutation == 0


def test_approved_retire_active_to_retired() -> None:
    item = _safe_item()
    snap = _snap(raw_data={})
    session = MagicMock()

    def _get(model, pk):
        # preview triage mocked; apply loads entity
        if int(pk) == 151:
            return snap
        return None

    session.get.side_effect = _get
    svc = StaleSnapshotBindingRetireService(session)
    svc._triage_one = MagicMock(return_value=item)  # type: ignore[method-assign]
    with patch(
        "stock_platform.broker.stale_snapshot_binding_retire_service.get_settings",
        return_value=SimpleNamespace(settlement_price_max_age_seconds=3600),
    ):
        preview = svc.preview([151])
        result = svc.apply(
            snapshot_ids=[151],
            approval_phrase=APPROVAL_PHRASE,
            fingerprint=preview.fingerprint or "",
            actor="admin@test",
        )
    assert result["mutation"] == 1
    assert snap.snapshot_status == BrokerSnapshotStatus.RETIRED.value
    assert snap.raw_data.get("_retire", {}).get("reason")
    assert result["audit_events"] == 1
    # hard delete 없음
    session.delete.assert_not_called()


def test_duplicate_apply_idempotent() -> None:
    item = _safe_item()
    snap = _snap(snapshot_status=BrokerSnapshotStatus.RETIRED.value, raw_data={})
    session = MagicMock()
    session.get.side_effect = lambda model, pk: snap if int(pk) == 151 else None
    svc = StaleSnapshotBindingRetireService(session)
    # already retired triage
    from stock_platform.broker.stale_snapshot_binding_retire_service import (
        SnapshotTriageItem,
    )

    retired_item = SnapshotTriageItem(
        snapshot_id=151,
        classification=CLASS_SAFE,
        current_status="RETIRED",
        stale_age_seconds=1_000_000,
        owner_uba=1338,
        broker_code="KIWOOM",
        generation=1,
        consumer_count=0,
        runtime_refs=0,
        order_refs_inflight=0,
        outbox_refs_active=0,
        newer_snapshot=False,
        retire_allowed=False,
        block_reason="ALREADY_RETIRED",
    )
    svc._triage_one = MagicMock(return_value=retired_item)  # type: ignore[method-assign]
    with patch(
        "stock_platform.broker.stale_snapshot_binding_retire_service.get_settings",
        return_value=SimpleNamespace(settlement_price_max_age_seconds=3600),
    ):
        result = svc.apply(
            snapshot_ids=[151],
            approval_phrase=APPROVAL_PHRASE,
            fingerprint="a" * 64,
            actor="admin",
        )
    assert result["code"] == "ALREADY_RETIRED"
    assert result["mutation"] == 0
    assert result["audit_events"] == 0


def test_triage_inactive_uba_safe() -> None:
    """inactive+deleted UBA + consumer 0 → SAFE_STALE_HISTORY."""

    from stock_platform.broker.account_models import BrokerAccountSnapshotEntity
    from stock_platform.trading.account_models import UserBrokerAccount

    session = MagicMock()
    snap = _snap(broker_account_snapshot_id=57, user_broker_account_id=58)
    uba = _uba(user_broker_account_id=58)

    def _get(model, pk):
        if model is BrokerAccountSnapshotEntity and int(pk) == 57:
            return snap
        if model is UserBrokerAccount and int(pk) == 58:
            return uba
        return None

    session.get.side_effect = _get
    svc = StaleSnapshotBindingRetireService(session)
    svc._count_active_strategy_links = MagicMock(return_value=0)  # type: ignore[method-assign]
    svc._count_runtime_refs = MagicMock(return_value=0)  # type: ignore[method-assign]
    svc._count_inflight_orders = MagicMock(return_value=0)  # type: ignore[method-assign]
    svc._count_active_outbox = MagicMock(return_value=0)  # type: ignore[method-assign]
    svc._has_newer_snapshot = MagicMock(return_value=False)  # type: ignore[method-assign]
    svc._credential_summary = MagicMock(  # type: ignore[method-assign]
        return_value={"has_active_verified": False, "rows": 0}
    )
    svc._recovery_summary = MagicMock(return_value={})  # type: ignore[method-assign]
    svc._count_open_recovery_conflicts = MagicMock(return_value=0)  # type: ignore[method-assign]

    item = svc._triage_one(57, max_age_seconds=3600)
    assert item.classification == CLASS_SAFE
    assert item.retire_allowed is True
