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
    assert ALLOWED_RECONCILE_SHADOW_IDS == frozenset({1, 2, 3, 19})
    from stock_platform.operation.upbit_opportunity_shadow.reconciliation import (
        APPROVAL_PHRASE_BY_SHADOW,
        PROVENANCE_ONLY_SHADOW_IDS,
    )

    assert APPROVAL_PHRASE_BY_SHADOW[3] == "RECONCILE SHADOW 3 EVALUATION"
    assert APPROVAL_PHRASE_BY_SHADOW[19] == "RECONCILE SHADOW 19 PROVENANCE"
    assert PROVENANCE_ONLY_SHADOW_IDS == frozenset({19})
    assert 20 not in ALLOWED_RECONCILE_SHADOW_IDS
    assert 21 not in ALLOWED_RECONCILE_SHADOW_IDS


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


@pytest.mark.asyncio
async def test_shadow3_phrase_and_return_30_reconcile(monkeypatch):
    """#3 전용 phrase + return_30m 교정 + 재apply idempotent."""

    from stock_platform.operation.upbit_opportunity_shadow.reconciliation import (
        APPROVAL_PHRASE_BY_SHADOW,
    )

    t0 = datetime(2026, 8, 12, 22, 10, 52, tzinfo=timezone.utc)
    row = _completed_row(3, symbol="KRW-DOGE", entry="98.1", t0=t0)
    row.return_5m_pct = -0.101937
    row.return_15m_pct = 0.0
    row.return_30m_pct = 0.0
    row.return_60m_pct = 0.101937
    row.price_30m = Decimal("98.1")
    row.mfe_pct = 0.203874
    row.mae_pct = -0.203874
    session = _session_for(row)
    recomputed = _recomputed_from_checkpoint(3, t0=t0, entry=98.1)
    _patch_dry(monkeypatch, recomputed)

    wrong = await UpbitOpportunityShadowReconciliationService(
        session, allow_sync=False
    ).apply(
        3,
        expected_fingerprint="x" * 64,
        actor="admin",
        reason="test",
        approval_phrase=APPROVAL_PHRASE,
    )
    assert wrong["code"] == "INVALID_APPROVAL_PHRASE"
    assert wrong["mutated"] is False

    with patch(
        "stock_platform.api.deps_admin.AuditLogService.record",
        return_value=MagicMock(),
    ):
        svc = UpbitOpportunityShadowReconciliationService(
            session, allow_sync=False
        )
        preview = await svc.preview(3)
        assert preview["code"] == "PREVIEW_OK"
        assert preview["approval_phrase_required"] == (
            "RECONCILE SHADOW 3 EVALUATION"
        )
        assert any(
            c["field"] == "return_30m_pct" for c in preview["changed_fields"]
        )
        out = await svc.apply(
            3,
            expected_fingerprint=preview["fingerprint"],
            actor="admin",
            reason="fix_return_30m",
            approval_phrase=APPROVAL_PHRASE_BY_SHADOW[3],
        )
        assert out["code"] == "RECONCILED"
        assert out["mutated"] is True
        assert row.return_30m_pct == pytest.approx(0.101937)
        assert float(row.price_30m) == pytest.approx(98.2)

        preview2 = await svc.preview(3)
        out2 = await svc.apply(
            3,
            expected_fingerprint=preview2["fingerprint"],
            actor="admin",
            reason="idem",
            approval_phrase=APPROVAL_PHRASE_BY_SHADOW[3],
        )
        assert out2["code"] == "ALREADY_RECONCILED"
        assert out2["mutated"] is False
        assert out2["orders_created"] == 0


@pytest.mark.asyncio
async def test_shadow19_provenance_preview_no_write(monkeypatch):
    """#19: numeric MATCH · provenance-only PREVIEW · WRITE 0."""

    from stock_platform.operation.upbit_opportunity_shadow.reconciliation import (
        APPROVAL_PHRASE_BY_SHADOW,
    )

    t0 = datetime(2026, 8, 13, 12, 23, 4, 100869, tzinfo=timezone.utc)
    row = _completed_row(19, symbol="KRW-RE", entry="643", t0=t0)
    row.return_5m_pct = -0.311042
    row.return_15m_pct = -0.466563
    row.return_30m_pct = -1.088647
    row.return_60m_pct = 0.311042
    row.price_5m = Decimal("641")
    row.price_15m = Decimal("640")
    row.price_30m = Decimal("636")
    row.price_60m = Decimal("645")
    row.mfe_pct = 0.622084
    row.mae_pct = -1.399689
    row.evaluation_detail = {
        "source": "minute_candle_historical_v1",
        "window_finalization": "target_candle_close_v2",
        "windows": {
            "5": {
                "final": True,
                "price": 641,
                "status": "OK",
                "return_pct": -0.311042,
                "observed_candle_at": "2026-08-13T12:28:00+00:00",
                "target_candle_start": "2026-08-13T12:28:00+00:00",
                "target_candle_end": "2026-08-13T12:29:00+00:00",
                "target_at": (t0 + timedelta(minutes=5)).isoformat(),
            },
            "15": {
                "final": True,
                "price": 640,
                "status": "OK",
                "return_pct": -0.466563,
                "observed_candle_at": "2026-08-13T12:38:00+00:00",
                "target_candle_start": "2026-08-13T12:38:00+00:00",
                "target_candle_end": "2026-08-13T12:39:00+00:00",
                "target_at": (t0 + timedelta(minutes=15)).isoformat(),
            },
            "30": {
                "price": 636,
                "status": "OK",
                "return_pct": -1.088647,
                "observed_candle_at": "2026-08-13T12:52:00+00:00",
                "target_at": (t0 + timedelta(minutes=30)).isoformat(),
            },
            "60": {
                "final": True,
                "price": 645,
                "status": "OK",
                "return_pct": 0.311042,
                "observed_candle_at": "2026-08-13T13:23:00+00:00",
                "target_candle_start": "2026-08-13T13:23:00+00:00",
                "target_candle_end": "2026-08-13T13:24:00+00:00",
                "target_at": (t0 + timedelta(minutes=60)).isoformat(),
            },
        },
        "mismatch_watch": {
            "ok": False,
            "code": "SHADOW_EVALUATION_MISMATCH",
        },
    }

    recomputed = _recomputed_from_checkpoint(19, t0=t0, entry=643.0)
    # 30m LAST_KNOWN provenance
    w30 = recomputed["windows"]["30"]
    w30.update(
        {
            "price": 636.0,
            "return_pct": -1.088647,
            "observed_candle_at": "2026-08-13T12:52:00+00:00",
            "target_candle_start": "2026-08-13T12:53:00+00:00",
            "target_candle_end": "2026-08-13T12:54:00+00:00",
            "final": True,
            "selection_type": "LAST_KNOWN_BEFORE_TARGET",
            "lag_seconds": 60.0,
            "fallback_reason": "TARGET_CANDLE_ABSENT_CONFIRMED",
            "source": "market.candle_minute",
        }
    )
    for m in ("5", "15", "60"):
        recomputed["windows"][m].update(
            {
                "final": True,
                "selection_type": "EXACT_TARGET_CANDLE",
                "lag_seconds": 4.100869,
                "fallback_reason": None,
                "source": "market.candle_minute",
                "target_candle_start": recomputed["windows"][m][
                    "observed_candle_at"
                ],
                "target_candle_end": (
                    datetime.fromisoformat(
                        recomputed["windows"][m]["observed_candle_at"]
                    )
                    + timedelta(minutes=1)
                ).isoformat(),
            }
        )
    recomputed["windows"]["5"]["price"] = 641.0
    recomputed["windows"]["5"]["return_pct"] = -0.311042
    recomputed["windows"]["15"]["price"] = 640.0
    recomputed["windows"]["15"]["return_pct"] = -0.466563
    recomputed["windows"]["60"]["price"] = 645.0
    recomputed["windows"]["60"]["return_pct"] = 0.311042
    recomputed["max_prior_lag_seconds"] = 180
    recomputed["target_resolve"] = {
        "2026-08-13T12:53:00+00:00": {
            "status": "TARGET_CANDLE_ABSENT_CONFIRMED",
            "api_rows": 5,
        }
    }

    session = _session_for(row)
    _patch_dry(monkeypatch, recomputed)
    before_ret = row.return_30m_pct
    before_detail = dict(row.evaluation_detail)

    svc = UpbitOpportunityShadowReconciliationService(session, allow_sync=False)
    out = await svc.preview(19)
    assert out["ok"] is True
    assert out["code"] == "PREVIEW_OK"
    assert out["mode"] == "provenance_only"
    assert out["mutated"] is False
    assert out["persist"] is False
    assert out["orders_created"] == 0
    assert out["numeric_changed_fields"] == []
    assert out["provenance_changed_fields"]
    assert any(
        c["field"].endswith("selection_type")
        for c in out["provenance_changed_fields"]
    )
    assert (
        out["approval_phrase_required"]
        == APPROVAL_PHRASE_BY_SHADOW[19]
        == "RECONCILE SHADOW 19 PROVENANCE"
    )
    assert out["expected_mismatch_after_apply"]["code"] == "MATCH"
    assert out["expected_mismatch_after_apply"]["mismatch_count_delta"] == -1
    # WRITE 금지 — preview 후 DB 상태 동일
    assert row.return_30m_pct == before_ret
    assert row.evaluation_detail == before_detail
    session.commit.assert_not_called()


@pytest.mark.asyncio
async def test_shadow20_not_in_allowlist():
    """#20 reconciliation 금지."""

    t0 = datetime(2026, 8, 13, 12, 23, 4, tzinfo=timezone.utc)
    row = _completed_row(20, symbol="KRW-VIRTUAL", entry="822", t0=t0)
    session = _session_for(row)
    svc = UpbitOpportunityShadowReconciliationService(session, allow_sync=False)
    out = await svc.preview(20)
    assert out["ok"] is False
    assert out["code"] == "SHADOW_NOT_IN_ALLOWLIST"
    assert out["mutated"] is False
    session.commit.assert_not_called()
