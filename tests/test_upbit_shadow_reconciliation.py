"""COMPLETED Shadow historical reconciliation — focused tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from stock_platform.operation.upbit_opportunity_shadow.candle_path import (
    MinuteBar,
    select_close_at_or_before,
)
from stock_platform.operation.upbit_opportunity_shadow.constants import (
    SHADOW_STATUS_COMPLETED,
)
from stock_platform.operation.upbit_opportunity_shadow.entities import (
    UpbitOpportunityShadowEntity,
)
from stock_platform.operation.upbit_opportunity_shadow.reconciliation import (
    ALLOWED_RECONCILE_SHADOW_IDS,
    APPROVAL_PHRASE,
    UpbitOpportunityShadowReconciliationService,
    _REFERENCE_CHECKPOINT,
)


def _bar(at: datetime, o: str, h: str, low: str, c: str) -> MinuteBar:
    return MinuteBar(
        candle_at=at,
        open=Decimal(o),
        high=Decimal(h),
        low=Decimal(low),
        close=Decimal(c),
    )


def _ok_window(
    *,
    minutes: int,
    t0: datetime,
    price: float,
    return_pct: float,
) -> dict:
    target = t0 + timedelta(minutes=minutes)
    return {
        "target_at": target.isoformat(),
        "observed_candle_at": target.isoformat(),
        "price": price,
        "return_pct": return_pct,
        "status": "OK",
    }


def _recomputed_from_checkpoint(
    shadow_id: int,
    *,
    t0: datetime,
    entry: float,
) -> dict:
    """체크포인트 숫자로 dry payload 구성 — DB write 하드코딩이 아님(테스트 목)."""

    ref = _REFERENCE_CHECKPOINT[shadow_id]
    windows = {}
    for m in (5, 15, 30, 60):
        ret = float(ref[f"return_{m}m_pct"])
        price = entry * (1.0 + ret / 100.0)
        windows[str(m)] = _ok_window(
            minutes=m, t0=t0, price=price, return_pct=ret
        )
    return {
        "ok": True,
        "symbol": "KRW-TEST",
        "entry_price": entry,
        "detected_at": t0.isoformat(),
        "windows": windows,
        "mfe_pct": float(ref["mfe_pct"]),
        "mae_pct": float(ref["mae_pct"]),
        "mfe_mae_detail": {"source": "test"},
        "tp_sl": {
            "tp_hit": bool(ref["tp_hit"]),
            "sl_hit": bool(ref["sl_hit"]),
            "tp_hit_at": None,
            "sl_hit_at": None,
            "first_hit": None,
            "detail": {},
        },
        "orders_created": 0,
    }


def _completed_row(
    shadow_id: int,
    *,
    symbol: str,
    entry: str,
    t0: datetime,
) -> UpbitOpportunityShadowEntity:
    return UpbitOpportunityShadowEntity(
        shadow_id=shadow_id,
        scanner_run_id="run-test",
        symbol=symbol,
        recommendation="ALLOW",
        status=SHADOW_STATUS_COMPLETED,
        scanner_rank=1,
        scanner_score=77.5,
        entry_price=Decimal(entry),
        assumed_amount_krw=Decimal("5000"),
        confidence=0.81,
        risk_level="MEDIUM",
        detected_at=t0,
        completed_at=t0 + timedelta(minutes=65),
        live_auto_start=False,
        evaluation_detail={"source": "legacy_ticker_stamp", "windows": {}},
        return_5m_pct=-1.0,
        return_15m_pct=-1.0,
        return_30m_pct=-1.0,
        return_60m_pct=-1.0,
        price_5m=Decimal(entry),
        price_15m=Decimal(entry),
        price_30m=Decimal(entry),
        price_60m=Decimal(entry),
        evaluated_5m_at=t0 + timedelta(minutes=5),
        evaluated_15m_at=t0 + timedelta(minutes=15),
        evaluated_30m_at=t0 + timedelta(minutes=30),
        evaluated_60m_at=t0 + timedelta(minutes=60),
        mfe_pct=-0.5,  # VIRTUAL 오류 형태(음수 MFE)
        mae_pct=0.093,  # SOL 오류 형태(양수 MAE)
        tp_hit=False,
        sl_hit=False,
    )


def _session_for(row: UpbitOpportunityShadowEntity) -> MagicMock:
    session = MagicMock()
    session.get.return_value = row
    session.commit = MagicMock()
    return session


def _patch_dry(monkeypatch, recomputed: dict):
    async def fake_dry(self, shadow_id: int):
        return {
            "ok": True,
            "shadow_id": shadow_id,
            "persist": False,
            "orders_created": 0,
            "recomputed": recomputed,
            "diff": {},
        }

    monkeypatch.setattr(
        "stock_platform.operation.upbit_opportunity_shadow.reconciliation."
        "UpbitOpportunityShadowEvaluator.dry_recompute",
        fake_dry,
    )


@pytest.mark.asyncio
async def test_preview_no_mutation(monkeypatch):
    t0 = datetime(2026, 8, 12, 10, 0, tzinfo=timezone.utc)
    row = _completed_row(1, symbol="KRW-VIRTUAL", entry="847", t0=t0)
    session = _session_for(row)
    recomputed = _recomputed_from_checkpoint(1, t0=t0, entry=847.0)
    _patch_dry(monkeypatch, recomputed)

    before_mfe = row.mfe_pct
    svc = UpbitOpportunityShadowReconciliationService(session, allow_sync=False)
    out = await svc.preview(1)

    assert out["ok"] is True
    assert out["mutated"] is False
    assert out["persist"] is False
    assert out["orders_created"] == 0
    assert out["code"] == "PREVIEW_OK"
    assert row.mfe_pct == before_mfe
    session.commit.assert_not_called()
    assert "fingerprint" in out


@pytest.mark.asyncio
async def test_apply_wrong_phrase_no_mutation(monkeypatch):
    t0 = datetime(2026, 8, 12, 10, 0, tzinfo=timezone.utc)
    row = _completed_row(1, symbol="KRW-VIRTUAL", entry="847", t0=t0)
    session = _session_for(row)
    recomputed = _recomputed_from_checkpoint(1, t0=t0, entry=847.0)
    _patch_dry(monkeypatch, recomputed)

    svc = UpbitOpportunityShadowReconciliationService(session, allow_sync=False)
    preview = await svc.preview(1)
    out = await svc.apply(
        1,
        expected_fingerprint=preview["fingerprint"],
        actor="admin",
        reason="test",
        approval_phrase="WRONG PHRASE",
    )
    assert out["ok"] is False
    assert out["code"] == "INVALID_APPROVAL_PHRASE"
    assert out["mutated"] is False
    assert out["orders_created"] == 0
    session.commit.assert_not_called()
    assert row.mfe_pct == -0.5


@pytest.mark.asyncio
async def test_apply_fingerprint_mismatch_no_mutation(monkeypatch):
    t0 = datetime(2026, 8, 12, 10, 0, tzinfo=timezone.utc)
    row = _completed_row(1, symbol="KRW-VIRTUAL", entry="847", t0=t0)
    session = _session_for(row)
    recomputed = _recomputed_from_checkpoint(1, t0=t0, entry=847.0)
    _patch_dry(monkeypatch, recomputed)

    svc = UpbitOpportunityShadowReconciliationService(session, allow_sync=False)
    out = await svc.apply(
        1,
        expected_fingerprint="deadbeef",
        actor="admin",
        reason="test",
        approval_phrase=APPROVAL_PHRASE,
    )
    assert out["ok"] is False
    assert out["code"] == "FINGERPRINT_MISMATCH"
    assert out["mutated"] is False
    session.commit.assert_not_called()


def test_apply_requires_approval_phrase_constant():
    assert APPROVAL_PHRASE == "RECONCILE UPBIT SHADOW HISTORY"
    assert ALLOWED_RECONCILE_SHADOW_IDS == frozenset({1, 2})


@pytest.mark.asyncio
async def test_shadow1_fixture_reconciliation(monkeypatch):
    t0 = datetime(2026, 8, 12, 10, 0, tzinfo=timezone.utc)
    row = _completed_row(1, symbol="KRW-VIRTUAL", entry="847", t0=t0)
    entry_price = row.entry_price
    amount = row.assumed_amount_krw
    score = row.scanner_score
    conf = row.confidence
    session = _session_for(row)
    recomputed = _recomputed_from_checkpoint(1, t0=t0, entry=847.0)
    _patch_dry(monkeypatch, recomputed)

    with patch(
        "stock_platform.api.deps_admin.AuditLogService.record",
        return_value=MagicMock(),
    ) as audit:
        svc = UpbitOpportunityShadowReconciliationService(
            session, allow_sync=False
        )
        preview = await svc.preview(1)
        assert preview["ok"] is True
        out = await svc.apply(
            1,
            expected_fingerprint=preview["fingerprint"],
            actor="admin",
            reason="historical_candle_reconciliation",
            approval_phrase=APPROVAL_PHRASE,
        )
        assert out["ok"] is True
        assert out["code"] == "RECONCILED"
        assert out["mutated"] is True
        assert out["orders_created"] == 0
        assert row.status == SHADOW_STATUS_COMPLETED
        assert row.entry_price == entry_price
        assert row.assumed_amount_krw == amount
        assert row.scanner_score == score
        assert row.confidence == conf
        assert row.recommendation == "ALLOW"
        assert row.mfe_pct == pytest.approx(0.118064, abs=5e-4)
        assert row.mae_pct == pytest.approx(-1.770956, abs=5e-4)
        assert row.mfe_pct > 0  # 음수 MFE 오류 교정
        assert row.return_5m_pct == pytest.approx(-0.472255, abs=5e-4)
        hist = (row.evaluation_detail or {}).get("reconciliation_history") or []
        assert len(hist) == 1
        assert hist[0]["original"]["mfe_pct"] == -0.5
        assert out["history_path"] == "evaluation_detail.reconciliation_history"
        session.commit.assert_called()
        audit.assert_called()


@pytest.mark.asyncio
async def test_shadow2_fixture_reconciliation(monkeypatch):
    t0 = datetime(2026, 8, 12, 11, 0, tzinfo=timezone.utc)
    row = _completed_row(2, symbol="KRW-SOL", entry="107100", t0=t0)
    session = _session_for(row)
    recomputed = _recomputed_from_checkpoint(2, t0=t0, entry=107100.0)
    _patch_dry(monkeypatch, recomputed)

    with patch(
        "stock_platform.api.deps_admin.AuditLogService.record",
        return_value=MagicMock(),
    ):
        svc = UpbitOpportunityShadowReconciliationService(
            session, allow_sync=False
        )
        preview = await svc.preview(2)
        out = await svc.apply(
            2,
            expected_fingerprint=preview["fingerprint"],
            actor="admin",
            reason="historical_candle_reconciliation",
            approval_phrase=APPROVAL_PHRASE,
        )
        assert out["ok"] is True
        assert out["code"] == "RECONCILED"
        assert row.mae_pct == pytest.approx(-0.186741, abs=5e-4)
        assert row.mae_pct < 0  # 양수 MAE 오류 교정
        assert row.mfe_pct == pytest.approx(0.280112, abs=5e-4)
        assert row.return_60m_pct == pytest.approx(0.186741, abs=5e-4)
        assert row.status == SHADOW_STATUS_COMPLETED
        assert row.symbol == "KRW-SOL"


@pytest.mark.asyncio
async def test_duplicate_apply_idempotent(monkeypatch):
    t0 = datetime(2026, 8, 12, 10, 0, tzinfo=timezone.utc)
    row = _completed_row(1, symbol="KRW-VIRTUAL", entry="847", t0=t0)
    session = _session_for(row)
    recomputed = _recomputed_from_checkpoint(1, t0=t0, entry=847.0)
    _patch_dry(monkeypatch, recomputed)

    with patch(
        "stock_platform.api.deps_admin.AuditLogService.record",
        return_value=MagicMock(),
    ):
        svc = UpbitOpportunityShadowReconciliationService(
            session, allow_sync=False
        )
        preview = await svc.preview(1)
        fp = preview["fingerprint"]
        first = await svc.apply(
            1,
            expected_fingerprint=fp,
            actor="admin",
            reason="r1",
            approval_phrase=APPROVAL_PHRASE,
        )
        assert first["code"] == "RECONCILED"
        hist_len = len(
            (row.evaluation_detail or {}).get("reconciliation_history") or []
        )
        mfe = row.mfe_pct
        second = await svc.apply(
            1,
            expected_fingerprint=fp,
            actor="admin",
            reason="r2",
            approval_phrase=APPROVAL_PHRASE,
        )
        assert second["ok"] is True
        assert second["code"] == "ALREADY_RECONCILED"
        assert second["mutated"] is False
        assert (
            len(
                (row.evaluation_detail or {}).get("reconciliation_history")
                or []
            )
            == hist_len
        )
        assert row.mfe_pct == mfe


@pytest.mark.asyncio
async def test_missing_candle_blocks_apply(monkeypatch):
    t0 = datetime(2026, 8, 12, 10, 0, tzinfo=timezone.utc)
    row = _completed_row(1, symbol="KRW-VIRTUAL", entry="847", t0=t0)
    session = _session_for(row)
    recomputed = _recomputed_from_checkpoint(1, t0=t0, entry=847.0)
    recomputed["windows"]["60"]["status"] = "MISSING"
    recomputed["windows"]["60"]["price"] = None
    recomputed["windows"]["60"]["return_pct"] = None
    _patch_dry(monkeypatch, recomputed)

    svc = UpbitOpportunityShadowReconciliationService(session, allow_sync=False)
    preview = await svc.preview(1)
    assert preview["ok"] is False
    assert preview["code"] == "RECONCILIATION_BLOCKED"
    out = await svc.apply(
        1,
        expected_fingerprint="anything",
        actor="admin",
        reason="test",
        approval_phrase=APPROVAL_PHRASE,
    )
    assert out["ok"] is False
    assert out["code"] == "RECONCILIATION_BLOCKED"
    assert out["mutated"] is False
    session.commit.assert_not_called()


def test_future_candle_not_used():
    """평가 경로: 미래 candle 선택 금지 (candle_path 정책 유지)."""

    t0 = datetime(2026, 8, 12, 10, 0, tzinfo=timezone.utc)
    now = t0 + timedelta(minutes=10)
    bars = [
        _bar(t0 + timedelta(minutes=i), "100", "101", "99", "100")
        for i in range(20)
    ]
    bar, status = select_close_at_or_before(
        bars,
        target_at=now + timedelta(minutes=5),
        now=now,
        max_lag_minutes=3,
    )
    assert status == "NOT_MATURED"
    assert bar is None


@pytest.mark.asyncio
async def test_non_allowlist_blocked():
    t0 = datetime(2026, 8, 12, 10, 0, tzinfo=timezone.utc)
    row = _completed_row(99, symbol="KRW-X", entry="1", t0=t0)
    session = _session_for(row)
    svc = UpbitOpportunityShadowReconciliationService(session, allow_sync=False)
    out = await svc.preview(99)
    assert out["ok"] is False
    assert out["code"] == "SHADOW_NOT_IN_ALLOWLIST"
    assert out["mutated"] is False


@pytest.mark.asyncio
async def test_no_trading_order_outbox_side_effects(monkeypatch):
    """재조정 경로는 주문/Outbox를 생성하지 않는다 (orders_created=0)."""

    t0 = datetime(2026, 8, 12, 10, 0, tzinfo=timezone.utc)
    row = _completed_row(1, symbol="KRW-VIRTUAL", entry="847", t0=t0)
    session = _session_for(row)
    recomputed = _recomputed_from_checkpoint(1, t0=t0, entry=847.0)
    _patch_dry(monkeypatch, recomputed)

    with patch(
        "stock_platform.api.deps_admin.AuditLogService.record",
        return_value=MagicMock(),
    ):
        svc = UpbitOpportunityShadowReconciliationService(
            session, allow_sync=False
        )
        preview = await svc.preview(1)
        out = await svc.apply(
            1,
            expected_fingerprint=preview["fingerprint"],
            actor="admin",
            reason="test",
            approval_phrase=APPROVAL_PHRASE,
        )
        assert out["orders_created"] == 0
        assert preview["orders_created"] == 0


@pytest.mark.asyncio
async def test_checkpoint_mismatch_blocks(monkeypatch):
    t0 = datetime(2026, 8, 12, 10, 0, tzinfo=timezone.utc)
    row = _completed_row(1, symbol="KRW-VIRTUAL", entry="847", t0=t0)
    session = _session_for(row)
    recomputed = _recomputed_from_checkpoint(1, t0=t0, entry=847.0)
    recomputed["mfe_pct"] = 9.999
    _patch_dry(monkeypatch, recomputed)

    svc = UpbitOpportunityShadowReconciliationService(session, allow_sync=False)
    out = await svc.preview(1)
    assert out["ok"] is False
    assert out["code"] == "RECONCILIATION_MISMATCH"
    assert out["mutated"] is False
