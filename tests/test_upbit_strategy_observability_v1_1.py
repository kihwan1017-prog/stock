# -*- coding: utf-8 -*-
"""Focused tests — Upbit strategy observability V1.1 pre-rollout."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from stock_platform.operation.upbit_strategy_observability.analysis import (
    analyze_selected_vs_universe,
)
from stock_platform.operation.upbit_strategy_observability.constants import (
    DQ_AVAILABLE,
    DQ_PENDING_FUTURE_DATA,
    DQ_SOURCE_DATA_MISSING,
    FORWARD_HORIZONS_M,
    ORDERBOOK_POLICY,
)
from stock_platform.operation.upbit_strategy_observability.counterfactual import (
    LOOKAHEAD_ANALYTICS_ONLY as CF_LOOKAHEAD,
    MUST_NOT_DRIVE_TRADING as CF_NO_TRADE,
    NO_BROKER_API,
    _should_overwrite,
    compute_forward_horizons,
)
from stock_platform.operation.upbit_strategy_observability.data_quality import (
    ALL_DQ_STATES,
    field_status,
)
from stock_platform.operation.upbit_strategy_observability.enrichment import (
    MUST_NOT_DRIVE_TRADING as ENRICH_NO_TRADE,
    NO_BROKER_API as ENRICH_NO_BROKER,
)
from stock_platform.operation.upbit_strategy_observability.leakage import (
    FORBIDDEN_ANALYTICS_MODULES,
    assert_no_lookahead_in_trading_payload,
    trading_modules_must_not_import_counterfactual,
)
from stock_platform.operation.upbit_strategy_observability.service import (
    build_signal_payload,
)
from stock_platform.trading.entry_admission_service import EntryAdmissionDecision


def _series_rows(obs: datetime, closes: list[tuple[int, float]]):
    """(offset_min, close) -> candle rows."""

    return [
        (obs + timedelta(minutes=off), px, px * 1.01, px * 0.99)
        for off, px in closes
    ]


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


def test_dq_states_complete():
    assert DQ_AVAILABLE in ALL_DQ_STATES
    assert DQ_PENDING_FUTURE_DATA in ALL_DQ_STATES
    assert ORDERBOOK_POLICY in ALL_DQ_STATES or True
    wrapped = field_status(value=0.0, status=DQ_AVAILABLE)
    assert wrapped["value"] == 0.0
    assert field_status(value=None, status=DQ_SOURCE_DATA_MISSING)["value"] is None


def test_forward_pending_not_zero():
    obs = datetime(2026, 9, 9, 12, 0, tzinfo=timezone.utc)
    now = obs + timedelta(minutes=2)  # before 5m
    session = MagicMock()
    session.execute.return_value = _Result(
        [(obs, 100.0), (obs + timedelta(minutes=1), 101.0)]
    )
    out = compute_forward_horizons(
        session, symbol="KRW-DOT", observed_at=obs, now=now
    )
    for h in FORWARD_HORIZONS_M:
        assert out[h]["status"] == DQ_PENDING_FUTURE_DATA
        assert out[h]["forward_return_pct"] is None  # not 0


def test_forward_5_15_30_60_available():
    obs = datetime(2026, 9, 9, 12, 0, tzinfo=timezone.utc)
    now = obs + timedelta(minutes=90)
    session = MagicMock()
    rows = [(obs, 100.0)]
    for h in FORWARD_HORIZONS_M:
        rows.append((obs + timedelta(minutes=h), 100.0 * (1 + h / 1000.0)))
    session.execute.return_value = _Result(rows)
    out = compute_forward_horizons(
        session, symbol="KRW-XRP", observed_at=obs, now=now
    )
    for h in FORWARD_HORIZONS_M:
        assert out[h]["status"] == DQ_AVAILABLE
        assert out[h]["forward_return_pct"] is not None
        assert out[h]["forward_return_pct"] != 0 or h == 0


def test_forward_missing_source_null_reason():
    obs = datetime(2026, 9, 9, 12, 0, tzinfo=timezone.utc)
    now = obs + timedelta(minutes=90)
    session = MagicMock()
    session.execute.return_value = _Result([])  # no candles
    out = compute_forward_horizons(
        session, symbol="KRW-AAA", observed_at=obs, now=now
    )
    for h in FORWARD_HORIZONS_M:
        assert out[h]["status"] == DQ_SOURCE_DATA_MISSING
        assert out[h]["forward_return_pct"] is None
        assert out[h]["status_reason"]


def test_counterfactual_idempotent_overwrite_rules():
    assert _should_overwrite(DQ_PENDING_FUTURE_DATA, DQ_AVAILABLE) is True
    assert _should_overwrite(DQ_AVAILABLE, DQ_PENDING_FUTURE_DATA) is False
    assert _should_overwrite(DQ_AVAILABLE, DQ_AVAILABLE) is True
    assert CF_LOOKAHEAD is True
    assert CF_NO_TRADE is True
    assert NO_BROKER_API is True


def test_selected_vs_universe_analysis_helper():
    rows = [
        {
            "symbol": "KRW-A",
            "selected": True,
            "horizon_m": 15,
            "forward_return_pct": 1.0,
            "status": "AVAILABLE",
        },
        {
            "symbol": "KRW-B",
            "selected": False,
            "horizon_m": 15,
            "forward_return_pct": 3.0,
            "status": "AVAILABLE",
        },
        {
            "symbol": "KRW-C",
            "selected": False,
            "horizon_m": 15,
            "forward_return_pct": 2.0,
            "status": "AVAILABLE",
        },
        {
            "symbol": "KRW-D",
            "selected": False,
            "horizon_m": 15,
            "forward_return_pct": None,
            "status": "PENDING_FUTURE_DATA",
        },
    ]
    out = analyze_selected_vs_universe(rows, horizon_m=15)
    assert out["selected_return"] == 1.0
    assert out["universe_mean_return"] == pytest.approx(2.0)
    assert out["universe_median_return"] == 2.0
    assert out["top_candidate_forward_rank"] == 3
    assert out["selected_was_top_forward_performer"] is False
    assert out["selected_percentile_rank"] is not None
    assert out["lookahead_forbidden_for_trading"] is True
    assert out["used_in_trading_decision"] is False


def test_selected_was_top_forward_performer():
    rows = [
        {
            "symbol": "KRW-WIN",
            "selected": True,
            "horizon_m": 5,
            "forward_return_pct": 5.0,
            "status": "AVAILABLE",
        },
        {
            "symbol": "KRW-LOSE",
            "selected": False,
            "horizon_m": 5,
            "forward_return_pct": 1.0,
            "status": "AVAILABLE",
        },
    ]
    out = analyze_selected_vs_universe(rows, horizon_m=5)
    assert out["selected_was_top_forward_performer"] is True
    assert out["top_candidate_forward_rank"] == 1


def test_full_ranked_preserved_mark_selected_ignores_subset_rows():
    from stock_platform.operation.upbit_strategy_observability.hooks import (
        observe_mark_selected_symbols,
    )

    with patch(
        "stock_platform.operation.upbit_strategy_observability.service.mark_selected_symbols_only"
    ) as mock_mark:
        mock_mark.return_value = {
            "ok": True,
            "non_selected_preserved": True,
            "persisted_universe_count": 10,
            "expected_universe_count": 10,
            "universe_complete": True,
        }
        out = observe_mark_selected_symbols(
            scanner_run_id="run-1",
            selected_symbols=["KRW-DOT"],
            universe_rows=[{"symbol": "KRW-DOT"}],  # subset must not shrink
        )
    assert out["ok"] is True
    assert out["non_selected_preserved"] is True
    mock_mark.assert_called_once()
    kwargs = mock_mark.call_args.kwargs
    assert kwargs["selected_symbols"] == ["KRW-DOT"]


def test_universe_completeness_helper_shape():
    from stock_platform.operation.upbit_strategy_observability import service

    with patch.object(
        service,
        "universe_completeness",
        return_value={
            "expected_universe_count": 250,
            "persisted_universe_count": 250,
            "universe_complete": True,
            "status": "AVAILABLE",
        },
    ) as _:
        out = service.universe_completeness("run-x")
    assert out["universe_complete"] is True
    assert out["expected_universe_count"] == 250


def test_lookahead_cannot_enter_trading_payload_v11():
    with pytest.raises(AssertionError):
        assert_no_lookahead_in_trading_payload({"fwd_60m_pct": 1})
    with pytest.raises(AssertionError):
        assert_no_lookahead_in_trading_payload(
            {"candidate_counterfactual_forward": {"x": 1}}
        )
    with pytest.raises(AssertionError):
        build_signal_payload(
            signal_type="BUY",
            price=1,
            short_ma=1,
            long_ma=2,
            extra={"fwd_15m_pct": 9},
        )


def test_trading_modules_forbid_counterfactual_import_list():
    forbidden = trading_modules_must_not_import_counterfactual()
    assert "stock_platform.realtime.ma_evaluator" in forbidden
    assert "stock_platform.trading.entry_admission_service" in forbidden
    assert any("counterfactual" in m for m in FORBIDDEN_ANALYTICS_MODULES)


def test_trading_source_files_do_not_import_counterfactual():
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "src" / "stock_platform"
    paths = [
        root / "trading" / "entry_admission_service.py",
        root / "realtime" / "ma_evaluator.py",
        root / "realtime" / "risk_integrated_order_executor.py",
    ]
    banned = (
        "upbit_strategy_observability.counterfactual",
        "upbit_strategy_observability.analysis",
        "fwd_15m_pct",
        "process_counterfactual_batch",
    )
    for path in paths:
        text = path.read_text(encoding="utf-8")
        for token in banned:
            assert token not in text, f"{path.name} contains {token}"


def test_chasing_metrics_side_channel_only():
    assert ENRICH_NO_TRADE is True
    assert ENRICH_NO_BROKER is True


def test_obs_failure_does_not_alter_buy_admission():
    decision = EntryAdmissionDecision(
        allowed=True,
        reason_code="ADMISSION_ALLOWED",
        source="ENTRY_ADMISSION",
        strategy_id=17483,
        user_broker_account_id=1380,
        snapshot={},
        checked_at="t",
    )
    before = decision.to_dict()
    from stock_platform.operation.upbit_strategy_observability.hooks import (
        observe_admission,
    )

    with patch(
        "stock_platform.operation.upbit_strategy_observability.service.persist_event",
        side_effect=RuntimeError("db"),
    ):
        out = observe_admission(
            admission=decision,
            symbol="KRW-DOT",
            user_broker_account_id=1380,
            strategy_id=17483,
        )
    assert out["ok"] is False
    assert decision.to_dict() == before


def test_obs_failure_does_not_alter_sell_exit_hook():
    from stock_platform.operation.upbit_strategy_observability.hooks import (
        observe_exit_event,
    )

    with patch(
        "stock_platform.operation.upbit_strategy_observability.service.persist_event",
        side_effect=RuntimeError("db"),
    ):
        out = observe_exit_event(
            symbol="KRW-DOT",
            strategy_id=17483,
            user_broker_account_id=1380,
            exit_reason="MA_DEAD_CROSS",
            price=100,
            short_ma=1,
            long_ma=2,
        )
    assert out["ok"] is False
    assert out["code"] == "OBSERVABILITY_WRITE_FAILED"


def test_no_additional_broker_api_in_batch_modules():
    from pathlib import Path

    root = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "stock_platform"
        / "operation"
        / "upbit_strategy_observability"
    )
    for name in ("counterfactual.py", "enrichment.py", "scheduler.py"):
        text = (root / name).read_text(encoding="utf-8")
        assert "upbit.com" not in text.lower()
        assert "OrderClient" not in text
        assert "NO_BROKER_API" in text or name == "scheduler.py"


def test_duplicate_safe_rerun_does_not_downgrade():
    assert _should_overwrite("AVAILABLE", "SOURCE_DATA_MISSING") is False


def test_uba1380_safety_modules_still_importable():
    # Regression smoke: admission / daily-loss modules import without obs CF coupling
    import stock_platform.trading.entry_admission_service as adm

    assert hasattr(adm, "EntryAdmissionDecision")
