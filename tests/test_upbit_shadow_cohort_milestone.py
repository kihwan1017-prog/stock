"""Shadow cohort milestone watch — focused tests."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from stock_platform.operation.upbit_opportunity_shadow.cohort_milestone import (
    STATUS_ACCUMULATING,
    STATUS_READY,
    ShadowCohortMilestoneWatch,
    VALID_COHORT_THRESHOLD,
    NEW_POLICY_MATCH_THRESHOLD,
    _is_new_policy_finalization,
    _is_valid_cohort_row,
    compute_cohort_milestone_snapshot,
)
from stock_platform.operation.upbit_opportunity_shadow.constants import (
    SHADOW_STATUS_COMPLETED,
)
from stock_platform.operation.upbit_opportunity_shadow.entities import (
    UpbitOpportunityShadowEntity,
)


def _row(
    shadow_id: int,
    *,
    finalization: str | None = "last_known_price_at_target_v1",
    watch_code: str = "MATCH",
    watch_ok: bool = True,
    missing_5m: bool = False,
) -> UpbitOpportunityShadowEntity:
    windows = {}
    for m in (5, 15, 30, 60):
        windows[str(m)] = {
            "final": True,
            "status": "OK",
            "selection_type": "EXACT_TARGET_CANDLE",
            "return_pct": 0.1,
            "price": 100,
        }
    detail = {
        "windows": windows,
        "window_finalization": finalization,
        "mismatch_watch": {"ok": watch_ok, "code": watch_code},
    }
    row = UpbitOpportunityShadowEntity(
        shadow_id=shadow_id,
        scanner_run_id="r",
        symbol=f"KRW-T{shadow_id}",
        recommendation="ALLOW",
        status=SHADOW_STATUS_COMPLETED,
        entry_price=Decimal("100"),
        assumed_amount_krw=Decimal("5000"),
        detected_at=datetime(2026, 8, 13, 12, 0, tzinfo=timezone.utc),
        completed_at=datetime(2026, 8, 13, 13, 0, tzinfo=timezone.utc),
        live_auto_start=False,
        evaluation_detail=detail,
        return_5m_pct=None if missing_5m else 0.1,
        return_15m_pct=0.1,
        return_30m_pct=0.1,
        return_60m_pct=0.1,
        mfe_pct=0.2,
        mae_pct=-0.2,
        tp_hit=False,
        sl_hit=False,
    )
    return row


def test_valid_and_new_policy_helpers():
    ok = _row(1)
    assert _is_valid_cohort_row(ok) is True
    assert _is_new_policy_finalization(ok) is True

    legacy = _row(2, finalization="target_candle_close_v2")
    legacy.evaluation_detail["windows"] = {
        "5": {"final": True, "status": "OK", "return_pct": 0.1},
        "15": {"final": True, "status": "OK", "return_pct": 0.1},
        "30": {"final": True, "status": "OK", "return_pct": 0.1},
        "60": {"final": True, "status": "OK", "return_pct": 0.1},
    }
    assert _is_new_policy_finalization(legacy) is False

    bad = _row(3, missing_5m=True)
    assert _is_valid_cohort_row(bad) is False


def test_snapshot_accumulating_when_below_thresholds():
    rows = [_row(i) for i in range(1, 6)]  # 5 < 30 and < 10 thresholds? 5 < 10
    session = MagicMock()
    session.scalars.return_value = rows
    snap = compute_cohort_milestone_snapshot(session)
    assert snap["status"] == STATUS_ACCUMULATING
    assert snap["ready"] is False
    assert snap["valid_cohort_n"] == 5
    assert snap["mismatch_count"] == 0
    assert snap["orders_created"] == 0
    assert snap["auto_reconcile"] is False


def test_snapshot_ready_when_all_conditions_met():
    rows = [
        _row(i) for i in range(1, VALID_COHORT_THRESHOLD + 1)
    ]  # 30 valid + new policy match
    session = MagicMock()
    session.scalars.return_value = rows
    snap = compute_cohort_milestone_snapshot(session)
    assert snap["valid_cohort_n"] == 30
    assert snap["new_policy_match_n"] == 30
    assert snap["new_policy_match_n"] >= NEW_POLICY_MATCH_THRESHOLD
    assert snap["mismatch_count"] == 0
    assert snap["ready"] is True
    assert snap["status"] == STATUS_READY


def test_mismatch_blocks_ready():
    rows = [_row(i) for i in range(1, 31)]
    rows[0].evaluation_detail["mismatch_watch"] = {
        "ok": False,
        "code": "SHADOW_EVALUATION_MISMATCH",
    }
    # mismatched row also fails valid cohort
    session = MagicMock()
    session.scalars.return_value = rows
    snap = compute_cohort_milestone_snapshot(session)
    assert snap["mismatch_count"] == 1
    assert snap["ready"] is False
    assert snap["status"] == STATUS_ACCUMULATING


def test_observe_notifies_once(monkeypatch):
    rows = [_row(i) for i in range(1, 31)]
    session = MagicMock()
    session.scalars.return_value = rows

    monkeypatch.setattr(
        "stock_platform.operation.upbit_opportunity_shadow.cohort_milestone.get_settings",
        lambda: SimpleNamespace(
            upbit_scanner_shadow_cohort_milestone_watch_enabled=True
        ),
    )
    monkeypatch.setattr(
        "stock_platform.operation.upbit_opportunity_shadow.cohort_milestone._already_notified",
        lambda _s: False,
    )
    audit = MagicMock()
    monkeypatch.setattr(
        "stock_platform.api.deps_admin.AuditLogService",
        lambda _s: audit,
    )
    notified = {"n": 0}

    def fake_publish(snap):
        notified["n"] += 1

    monkeypatch.setattr(
        "stock_platform.operation.upbit_opportunity_shadow.cohort_milestone.publish_shadow_cohort_milestone",
        fake_publish,
    )

    out = ShadowCohortMilestoneWatch(session).observe(notify=True)
    assert out["status"] == STATUS_READY
    assert out["notified"] is True
    assert out["orders_created"] == 0
    assert notified["n"] == 1
    audit.record.assert_called_once()
    assert audit.record.call_args.kwargs["event_type"] == STATUS_READY

    # second call — already notified
    monkeypatch.setattr(
        "stock_platform.operation.upbit_opportunity_shadow.cohort_milestone._already_notified",
        lambda _s: True,
    )
    out2 = ShadowCohortMilestoneWatch(session).observe(notify=True)
    assert out2["already_notified"] is True
    assert out2["notified"] is False
    assert notified["n"] == 1  # no second telegram


def test_observe_accumulating_no_notify(monkeypatch):
    rows = [_row(i) for i in range(1, 5)]
    session = MagicMock()
    session.scalars.return_value = rows
    monkeypatch.setattr(
        "stock_platform.operation.upbit_opportunity_shadow.cohort_milestone.get_settings",
        lambda: SimpleNamespace(
            upbit_scanner_shadow_cohort_milestone_watch_enabled=True
        ),
    )
    with patch(
        "stock_platform.operation.upbit_opportunity_shadow.cohort_milestone.publish_shadow_cohort_milestone"
    ) as pub:
        out = ShadowCohortMilestoneWatch(session).observe(notify=True)
    assert out["status"] == STATUS_ACCUMULATING
    assert out["notified"] is False
    pub.assert_not_called()
