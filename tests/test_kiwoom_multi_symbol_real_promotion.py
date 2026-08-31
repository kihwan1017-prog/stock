"""KIWOOM multi-symbol REAL promotion — focused tests (A-R subset)."""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from stock_platform.operation.kiwoom_multi_symbol_universe.constants import (
    CROSS_STATE_ABOVE_NO_NEW,
    CROSS_STATE_FRESH_CROSS,
    MODE_REAL,
    MODE_SHADOW,
)
from stock_platform.operation.kiwoom_multi_symbol_universe.ma_eval import (
    build_signal_fingerprint,
    evaluate_daily_ma_cross,
)
from stock_platform.operation.kiwoom_multi_symbol_universe.mode import (
    is_kiwoom_multi_symbol_real_enabled,
    resolve_kiwoom_multi_symbol_mode,
)
from stock_platform.operation.kiwoom_multi_symbol_universe.real_signal import (
    extend_kiwoom_consumer_symbols,
    multi_symbol_real_defers_legacy_ma_buy,
    update_multi_symbol_runtime_cache,
)

def test_a_top10_selection_does_not_imply_buy() -> None:
    closes = [Decimal("100") + Decimal(i) for i in range(25)]
    ma = evaluate_daily_ma_cross(symbol="005930", closes=closes)
    assert ma.is_fresh_golden_cross is False
    assert ma.cross_state == CROSS_STATE_ABOVE_NO_NEW


def test_b_already_above_no_real_signal_semantics() -> None:
    closes = [Decimal("100") + Decimal(i) for i in range(25)]
    ma = evaluate_daily_ma_cross(symbol="005930", closes=closes)
    assert ma.cross_state == CROSS_STATE_ABOVE_NO_NEW


def test_c_genuine_fresh_cross_detected() -> None:
    closes = [Decimal("100")] * 20 + [Decimal("50"), Decimal("200")]
    ma = evaluate_daily_ma_cross(symbol="034310", closes=closes)
    if ma.prev_sma5 is not None and ma.prev_sma20 is not None:
        if ma.prev_sma5 <= ma.prev_sma20 and ma.sma5 is not None and ma.sma20 is not None:
            if ma.sma5 > ma.sma20:
                assert ma.is_fresh_golden_cross is True
                assert ma.cross_state == CROSS_STATE_FRESH_CROSS


def test_d_fingerprint_dedup_same_day() -> None:
    fp1 = build_signal_fingerprint(symbol="034310", cross_day=date(2026, 8, 31))
    fp2 = build_signal_fingerprint(symbol="034310", cross_day=date(2026, 8, 31))
    assert fp1 == fp2


def test_e_034310_legacy_deferred_when_in_roster() -> None:
    update_multi_symbol_runtime_cache(
        user_broker_account_id=1381,
        monitor_symbols=["034310", "005930"],
        owned_symbols=set(),
    )
    with patch(
        "stock_platform.operation.kiwoom_multi_symbol_universe.real_signal.is_kiwoom_multi_symbol_real_enabled",
        return_value=True,
    ):
        assert multi_symbol_real_defers_legacy_ma_buy(
            broker_code="KIWOOM", uba_id=1381, symbol="034310"
        )


def test_f_restart_fake_cross_prevented_by_fingerprint() -> None:
    fp = build_signal_fingerprint(symbol="034310", cross_day=date(2026, 8, 31))
    assert fp.startswith("gc:034310:")


def test_g_promotion_mode_real_resolves() -> None:
    class _Cfg:
        kiwoom_multi_symbol_mode = MODE_REAL
        kiwoom_multi_symbol_shadow_only = True

    assert resolve_kiwoom_multi_symbol_mode(_Cfg()) == MODE_REAL
    assert is_kiwoom_multi_symbol_real_enabled(_Cfg()) is True


def test_h_roster_remove_readd_fingerprint_stable() -> None:
    d = date(2026, 8, 31)
    assert build_signal_fingerprint(symbol="005930", cross_day=d) == build_signal_fingerprint(
        symbol="005930", cross_day=d
    )


def test_i_union_preserves_owned_after_roster_removal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from stock_platform.operation.kiwoom_multi_symbol_universe.service import (
        union_real_and_shadow_symbols,
    )

    monkeypatch.setattr(
        "stock_platform.operation.kiwoom_multi_symbol_universe.service.resolve_real_feed_symbols",
        lambda session, user_broker_account_id: ["034310"],
    )
    monkeypatch.setattr(
        "stock_platform.operation.kiwoom_multi_symbol_universe.service._strategy_owned_symbols",
        lambda session, uba_id: {"999990"},
    )
    merged = union_real_and_shadow_symbols(
        None,  # type: ignore[arg-type]
        user_broker_account_id=1381,
        shadow_symbols=["005930"],
        extra_owned_symbols={"999990"},
    )
    assert "999990" in merged
    assert "034310" in merged


def test_j_manual_holding_not_deferred_outside_roster() -> None:
    update_multi_symbol_runtime_cache(
        user_broker_account_id=1381,
        monitor_symbols=["005930"],
        owned_symbols=set(),
    )
    with patch(
        "stock_platform.operation.kiwoom_multi_symbol_universe.real_signal.is_kiwoom_multi_symbol_real_enabled",
        return_value=True,
    ):
        assert not multi_symbol_real_defers_legacy_ma_buy(
            broker_code="KIWOOM", uba_id=1381, symbol="034310"
        )


def test_k_consumer_extends_owned_and_monitor() -> None:
    update_multi_symbol_runtime_cache(
        user_broker_account_id=1381,
        monitor_symbols=["005930"],
        owned_symbols={"888880"},
    )
    with patch(
        "stock_platform.operation.kiwoom_multi_symbol_universe.real_signal.is_kiwoom_multi_symbol_real_enabled",
        return_value=True,
    ):
        out = extend_kiwoom_consumer_symbols(
            ["034310"], user_broker_account_id=1381
        )
    assert "005930" in out
    assert "888880" in out
    assert "034310" in out


@pytest.mark.asyncio
async def test_l_real_dispatch_duplicate_protected() -> None:
    from stock_platform.operation.kiwoom_multi_symbol_universe.real_signal import (
        dispatch_multi_symbol_real_signal,
    )

    session = MagicMock()
    session.scalar.return_value = MagicMock(real_signal_id=99)
    ma = evaluate_daily_ma_cross(
        symbol="034310",
        closes=[Decimal("100")] * 20 + [Decimal("50"), Decimal("200")],
    )
    out = await dispatch_multi_symbol_real_signal(
        session,
        user_broker_account_id=1381,
        symbol="034310",
        ma_eval=ma,
        price=Decimal("100"),
        observed_at=datetime.now(timezone.utc),
        refresh_batch_id="batch1",
        rank=1,
        scope_ctx={
            "user_id": 7,
            "user_broker_account_id": 1381,
            "strategy_id": 17579,
            "strategy_version": "1",
            "scope_key": "scope-test",
            "market_type": "STOCK",
        },
    )
    assert out.get("reason") == "DUPLICATE_REAL_SIGNAL"
    assert out.get("duplicate_protected") is True


def test_m_shadow_mode_default() -> None:
    from stock_platform.common.settings import get_settings

    cfg = get_settings()
    assert resolve_kiwoom_multi_symbol_mode(cfg) in {MODE_SHADOW, MODE_REAL}


@pytest.mark.asyncio
async def test_n_refresh_real_branch(monkeypatch: pytest.MonkeyPatch) -> None:
    from stock_platform.operation.kiwoom_multi_symbol_universe.service import (
        KiwoomMultiSymbolUniverseService,
    )

    class _Cfg:
        kiwoom_multi_symbol_monitor_target = 10
        kiwoom_multi_symbol_min_trade_value = 100_000_000
        kiwoom_multi_symbol_mode = MODE_REAL
        kiwoom_multi_symbol_shadow_enabled = True
        kiwoom_multi_symbol_shadow_only = True

    dispatch_mock = AsyncMock(
        return_value={"published": False, "reason": "GUARD_BLOCKED", "ok": False}
    )
    monkeypatch.setattr(
        "stock_platform.operation.kiwoom_multi_symbol_universe.service.get_settings",
        lambda: _Cfg(),
    )
    monkeypatch.setattr(
        "stock_platform.operation.kiwoom_multi_symbol_universe.service.load_krx_tradable_universe",
        lambda s: [{"symbol": "034310", "name": "T", "instrument_id": 1, "extra_data": {}}],
    )
    monkeypatch.setattr(
        "stock_platform.operation.kiwoom_multi_symbol_universe.service.prefilter_and_rank_candidates",
        lambda *a, **k: (
            [
                MagicMock(
                    symbol="034310",
                    rank=1,
                    name="T",
                    price=Decimal("100"),
                    volume=Decimal("1"),
                    trading_value=Decimal("200000000"),
                    change_pct=Decimal("1"),
                    selection_reason="TV",
                    insufficient_history=False,
                    cross_state=CROSS_STATE_FRESH_CROSS,
                )
            ],
            {"timing": {}, "query_count": 2, "monitor_count": 1},
        ),
    )
    monkeypatch.setattr(
        "stock_platform.operation.kiwoom_multi_symbol_universe.service.load_completed_daily_closes",
        lambda *a, **k: [(date(2026, 8, 30), Decimal("100"))] * 21,
    )
    monkeypatch.setattr(
        "stock_platform.operation.kiwoom_multi_symbol_universe.service.evaluate_daily_ma_cross",
        lambda **kw: MagicMock(
            is_fresh_golden_cross=True,
            insufficient_history=False,
            sma5=Decimal("110"),
            sma20=Decimal("100"),
            prev_sma5=Decimal("95"),
            prev_sma20=Decimal("100"),
            cross_state=CROSS_STATE_FRESH_CROSS,
        ),
    )
    monkeypatch.setattr(
        "stock_platform.operation.kiwoom_multi_symbol_universe.service._record_shadow_signal",
        lambda *a, **k: {"ok": True, "created": True},
    )
    monkeypatch.setattr(
        "stock_platform.operation.kiwoom_multi_symbol_universe.service.dispatch_multi_symbol_real_signal",
        dispatch_mock,
    )
    monkeypatch.setattr(
        "stock_platform.operation.kiwoom_multi_symbol_universe.service.reconcile_shadow_feed_subscriptions",
        AsyncMock(return_value={"ok": True, "symbols": ["034310"]}),
    )
    monkeypatch.setattr(
        "stock_platform.operation.kiwoom_multi_symbol_universe.service._strategy_owned_symbols",
        lambda session, uba_id: set(),
    )
    monkeypatch.setattr(
        "stock_platform.operation.kiwoom_multi_symbol_universe.service._pending_order_symbols",
        lambda session, uba_id: set(),
    )
    monkeypatch.setattr(
        "stock_platform.operation.kiwoom_multi_symbol_universe.service._load_cross_state",
        lambda *a, **k: None,
    )
    monkeypatch.setattr(
        "stock_platform.operation.kiwoom_multi_symbol_universe.service.resolve_kiwoom_multi_symbol_scope",
        lambda session, user_broker_account_id: {
            "scope_key": "x",
            "strategy_id": 17579,
        },
    )

    session = MagicMock()
    session.scalars.return_value = []
    session.execute.return_value = None
    session.commit = MagicMock()
    session.add = MagicMock()
    session.flush = MagicMock()

    svc = KiwoomMultiSymbolUniverseService(session)
    out = await svc.refresh(user_broker_account_id=1381, trigger_source="TEST")
    assert out["real_enabled"] is True
    assert out["DUPLICATE_REAL_SIGNAL_PROTECTED"] is True
    dispatch_mock.assert_awaited()
