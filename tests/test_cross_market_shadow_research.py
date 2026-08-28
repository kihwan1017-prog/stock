"""Cross-market shadow research pipeline tests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from stock_platform.operation.kiwoom_opportunity_shadow.entry_signal_shadow.constants import (
    HORIZON_PENDING,
    KIWOOM_24H_SEMANTICS,
)
from stock_platform.operation.kiwoom_opportunity_shadow.entry_signal_shadow.hooks import (
    maybe_enroll_kiwoom_golden_cross_shadow,
)
from stock_platform.operation.kiwoom_opportunity_shadow.entry_signal_shadow.replay import (
    future_prices_kiwoom,
)
from stock_platform.operation.kiwoom_opportunity_shadow.entry_signal_shadow.service import (
    enroll_golden_cross_observation,
)
from stock_platform.operation.upbit_opportunity_shadow.entry_signal_shadow.constants import (
    HORIZON_MATURED,
    HORIZON_MISSING_DATA,
    OUTCOME_WINDOWS_MIN,
    STATUS_COMPLETED,
    STATUS_PENDING,
)
from stock_platform.operation.upbit_opportunity_shadow.entry_signal_shadow.replay import (
    _future_prices,
)
from stock_platform.operation.upbit_opportunity_shadow.entry_signal_shadow.service import (
    mature_pending_outcomes,
)


def test_4h_premature_maturation_blocked() -> None:
    """4h horizon — as_of < T0+240m 이면 PENDING 유지."""

    obs = datetime(2026, 8, 28, 10, 0, tzinfo=timezone.utc)
    as_of = obs + timedelta(minutes=61)
    session = MagicMock()
    session.scalar.return_value = Decimal("100")
    session.execute.return_value.mappings.return_value.first.return_value = {
        "close_price": Decimal("101"),
        "high_price": Decimal("102"),
        "low_price": Decimal("99"),
        "candle_at": obs + timedelta(minutes=5),
    }
    session.execute.return_value.mappings.return_value.all.return_value = []

    out = _future_prices(
        session, symbol="KRW-BTC", observed_at=obs, as_of=as_of
    )
    assert out["ok"] is True
    assert out["horizons"]["future_240m"]["status"] == HORIZON_PENDING
    assert out["futures"]["future_240m"] is None
    assert out["all_horizons_resolved"] is False


def test_24h_premature_maturation_blocked() -> None:
    obs = datetime(2026, 8, 28, 10, 0, tzinfo=timezone.utc)
    as_of = obs + timedelta(hours=12)
    session = MagicMock()
    session.scalar.return_value = Decimal("100")
    session.execute.return_value.mappings.return_value.first.return_value = {
        "close_price": Decimal("101"),
        "high_price": Decimal("102"),
        "low_price": Decimal("99"),
        "candle_at": obs + timedelta(minutes=5),
    }
    session.execute.return_value.mappings.return_value.all.return_value = []

    out = _future_prices(
        session, symbol="KRW-BTC", observed_at=obs, as_of=as_of
    )
    assert out["horizons"]["future_1440m"]["status"] == HORIZON_PENDING


def test_missing_data_not_treated_as_zero_return() -> None:
    obs = datetime(2026, 8, 20, 10, 0, tzinfo=timezone.utc)
    as_of = obs + timedelta(minutes=65)
    session = MagicMock()
    session.scalar.return_value = Decimal("100")
    session.execute.return_value.mappings.return_value.first.return_value = None
    session.execute.return_value.mappings.return_value.all.return_value = []

    out = _future_prices(
        session, symbol="KRW-BTC", observed_at=obs, as_of=as_of
    )
    assert out["horizons"]["future_5m"]["status"] == HORIZON_MISSING_DATA
    assert out["futures"]["future_5m"] is None


def test_mature_pending_partial_not_completed() -> None:
    old = datetime.now(timezone.utc) - timedelta(minutes=90)
    row = MagicMock()
    row.symbol = "KRW-TEST"
    row.observed_at = old
    row.outcome_status = STATUS_PENDING
    row.outcome_json = {}

    session = MagicMock()
    session.scalars.return_value = [row]

    with patch(
        "stock_platform.operation.upbit_opportunity_shadow.entry_signal_shadow.service._future_prices",
        return_value={
            "ok": True,
            "entry_reference_price": Decimal("100"),
            "futures": {
                "future_5m": 0.1,
                "future_15m": 0.2,
                "future_30m": 0.3,
                "future_60m": 0.4,
                "future_240m": None,
                "future_1440m": None,
            },
            "horizons": {
                "future_5m": {"status": HORIZON_MATURED},
                "future_240m": {"status": HORIZON_PENDING},
            },
            "all_horizons_resolved": False,
            "mfe_pct": 0.5,
            "mae_pct": -0.1,
            "net_return_15m_pct": 0.1,
            "fee_assumption": "test",
            "slippage_assumption": "SLIPPAGE_NOT_MODELED",
            "as_of": datetime.now(timezone.utc).isoformat(),
        },
    ):
        out = mature_pending_outcomes(session, commit=False)

    assert out["partial"] == 1
    assert row.outcome_status == STATUS_PENDING


def test_kiwoom_golden_cross_episode_dedupe() -> None:
    session = MagicMock()
    session.scalar.return_value = 99
    result = enroll_golden_cross_observation(
        session,
        uba_id=1381,
        symbol="034310",
        short_ma=Decimal("101"),
        long_ma=Decimal("100"),
        prev_short=Decimal("99"),
        prev_long=Decimal("100"),
        commit=False,
    )
    assert result["created"] == 0
    assert result["skipped_duplicate"] == 1
    assert result["real_order_mutation"] == 0


def test_kiwoom_hook_skips_non_kiwoom() -> None:
    out = maybe_enroll_kiwoom_golden_cross_shadow(
        broker_code="UPBIT",
        uba_id=1380,
        symbol="KRW-BTC",
        short_ma=Decimal("101"),
        long_ma=Decimal("100"),
        prev_short=Decimal("99"),
        prev_long=Decimal("100"),
    )
    assert out["ok"] is False
    assert out["reason"] == "NOT_KIWOOM"


def test_kiwoom_hook_skips_non_transition() -> None:
    out = maybe_enroll_kiwoom_golden_cross_shadow(
        broker_code="KIWOOM",
        uba_id=1381,
        symbol="034310",
        short_ma=Decimal("101"),
        long_ma=Decimal("100"),
        prev_short=Decimal("102"),
        prev_long=Decimal("100"),
    )
    assert out["reason"] == "NOT_GOLDEN_CROSS_TRANSITION"


def test_kiwoom_24h_semantics_constant() -> None:
    assert "24H" in KIWOOM_24H_SEMANTICS


def test_outcome_windows_include_4h_24h() -> None:
    assert 240 in OUTCOME_WINDOWS_MIN
    assert 1440 in OUTCOME_WINDOWS_MIN


def test_research_failure_does_not_block_trading_scheduler_pattern() -> None:
    from stock_platform.operation.kiwoom_opportunity_shadow.entry_signal_shadow.scheduler import (
        run_kiwoom_entry_signal_shadow_outcome_tick,
    )

    settings = MagicMock()
    settings.kiwoom_entry_signal_shadow_enabled = True
    with patch(
        "stock_platform.operation.kiwoom_opportunity_shadow.entry_signal_shadow.scheduler.get_session_factory",
        side_effect=RuntimeError("db down"),
    ):
        out = run_kiwoom_entry_signal_shadow_outcome_tick(settings)
    assert out["ok"] is False
    assert out["orders_created"] == 0
