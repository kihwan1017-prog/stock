"""Portfolio policy GET/PATCH, slot capacity 5, empty-slot-first regression."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from stock_platform.operation.upbit_full_market.constants import (
    SLOT_EMPTY,
    SLOT_WAITING_SIGNAL,
)
from stock_platform.operation.upbit_full_market.portfolio_entry_signal import (
    load_thresholds_from_policy,
    resolve_ma_windows_from_policy,
)
from stock_platform.operation.upbit_full_market.portfolio_service import (
    UpbitPortfolioService,
)


def test_load_thresholds_from_policy_json_overrides_settings() -> None:
    th = load_thresholds_from_policy(
        settings=MagicMock(
            upbit_portfolio_entry_rsi_max=70.0,
            upbit_portfolio_entry_min_volume_surge=0.8,
            upbit_portfolio_entry_min_ma_separation_pct=0.05,
            upbit_portfolio_entry_require_ai_allow=True,
            autotrading_market_feed_stale_seconds=30.0,
            upbit_portfolio_candidate_hold_seconds=1800.0,
        ),
        risk_group_policy_json={
            "rsi_max": 65.0,
            "min_volume_surge": 1.0,
            "min_ma_separation_pct": 0.03,
            "require_ai_allow": False,
        },
        candidate_max_age_seconds=1200,
    )
    assert th.rsi_max == 65.0
    assert th.min_volume_surge == 1.0
    assert th.min_ma_separation_pct == 0.03
    assert th.require_ai_allow is False
    assert th.max_candidate_age_seconds == 1200.0


def test_resolve_ma_windows_json_over_strategy_payload() -> None:
    ma = resolve_ma_windows_from_policy(
        risk_group_policy_json={"short_ma_window": 7, "long_ma_window": 25},
        strategy_parameter_payload={"short_window": 5, "long_window": 20},
    )
    assert ma["short_ma_window"] == 7
    assert ma["long_ma_window"] == 25


def test_update_policy_max_positions_5_creates_empty_slots(monkeypatch) -> None:
    """max_positions 증가 시 기존 slot 유지 + EMPTY slot 추가."""

    from stock_platform.operation.upbit_full_market import portfolio_service as ps_mod

    session = MagicMock()
    row = MagicMock()
    row.max_positions = 3
    row.risk_group_policy_json = {"entry_signal_policy": "BULLISH_STATE"}
    row.candidate_max_age_seconds = 1800
    row.version = 1
    row.enabled = True
    row.portfolio_capital_limit_krw = 300000
    row.per_position_target_pct = 0.08
    row.max_symbol_exposure_pct = 0.12
    row.max_total_exposure_pct = 0.3
    row.min_cash_reserve_pct = 0.6
    row.daily_loss_limit_pct = 0.02
    row.consecutive_loss_limit = 3
    row.allow_averaging_down = False
    row.allow_duplicate_symbol = False
    row.entry_cooldown_seconds = 300
    row.portfolio_max_pending_entries = 1
    row.portfolio_daily_entry_limit = 10
    row.entry_state = "RUNNING"
    row.consecutive_loss_count = 0
    row.policy_id = 1

    svc = UpbitPortfolioService(session)
    monkeypatch.setattr(svc, "get_or_create_policy", lambda _uba: row)
    ensure_calls: list[int] = []

    def _ensure(uba_id: int, *, max_positions: int) -> list:
        ensure_calls.append(max_positions)
        return []

    monkeypatch.setattr(svc, "ensure_slots", _ensure)
    monkeypatch.setattr(
        svc,
        "policy_dict",
        lambda _uba: {"max_positions": 5, "entry_signal_policy": "BULLISH_STATE"},
    )

    result = svc.update_policy(1380, patches={"max_positions": 5}, actor="test")
    assert result["ok"] is True
    assert row.max_positions == 5
    assert ensure_calls == [5]


def test_update_policy_rejects_invalid_ma_window_order() -> None:
    session = MagicMock()
    row = MagicMock()
    row.risk_group_policy_json = {}
    row.version = 1
    svc = UpbitPortfolioService(session)
    svc.get_or_create_policy = MagicMock(return_value=row)  # type: ignore[method-assign]

    with pytest.raises(ValueError, match="MA_WINDOW_ORDER_INVALID"):
        svc.update_policy(
            1380,
            patches={"short_ma_window": 20, "long_ma_window": 10},
            actor="test",
        )


def test_consume_top_k_empty_slot_before_replacement_documented() -> None:
    """EMPTY slot fill 경로가 replacement보다 먼저 — consume_top_k 소스 계약."""

    import inspect

    from stock_platform.operation.upbit_full_market import portfolio_service

    src = inspect.getsource(portfolio_service.UpbitPortfolioService.consume_top_k)
    assert "if not empty:" in src
    assert "slot = empty[0]" in src
    assert src.index("if not empty:") < src.index("slot = empty[0]")


def test_slot_status_constants_for_empty_first() -> None:
    assert SLOT_EMPTY == "EMPTY"
    assert SLOT_WAITING_SIGNAL == "WAITING_SIGNAL"
