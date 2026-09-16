"""기술지표 파라미터 Validation / Default fallback."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from stock_platform.indicators.parameter_service import (
    DEFAULT_PARAMETERS,
    IndicatorParameterService,
    IndicatorParameterValidationError,
    validate_parameter_payload,
)


@pytest.mark.unit
def test_validate_macd_fast_must_be_less_than_slow() -> None:
    with pytest.raises(IndicatorParameterValidationError):
        validate_parameter_payload(
            "MACD", {"fast": 26, "slow": 12, "signal": 9}
        )
    with pytest.raises(IndicatorParameterValidationError):
        validate_parameter_payload(
            "MACD", {"fast": 12, "slow": 12, "signal": 9}
        )
    assert validate_parameter_payload(
        "MACD", {"fast": 12, "slow": 26, "signal": 9}
    ) == {"fast": 12, "slow": 26, "signal": 9}


@pytest.mark.unit
def test_validate_periods_must_be_positive() -> None:
    with pytest.raises(IndicatorParameterValidationError):
        validate_parameter_payload("RSI", {"period": 0})
    with pytest.raises(IndicatorParameterValidationError):
        validate_parameter_payload("RSI", {"period": -1})
    with pytest.raises(IndicatorParameterValidationError):
        validate_parameter_payload("MA_SET", {"ma5": 5, "ma20": 20})


@pytest.mark.unit
def test_system_defaults_preserved() -> None:
    assert DEFAULT_PARAMETERS["RSI"]["period"] == 14
    assert DEFAULT_PARAMETERS["MACD"]["fast"] == 12
    svc = IndicatorParameterService(MagicMock())
    params = svc.resolve_engine_params()
    assert params.source == "SYSTEM_DEFAULT"
    assert params.rsi_period == 14
    assert params.macd_fast == 12


@pytest.mark.unit
def test_db_active_overrides_defaults() -> None:
    session = MagicMock()
    session.scalars.return_value = [
        SimpleNamespace(
            indicator_code="RSI",
            market_type="STOCK",
            timeframe="1D",
            parameter_payload={"period": 21},
            version=2,
            is_active=True,
        )
    ]
    params = IndicatorParameterService(session).resolve_engine_params(
        market_type="STOCK", timeframe="1D"
    )
    assert params.rsi_period == 21
    assert params.source.startswith("DB:")


@pytest.mark.unit
def test_invalid_active_config_fail_closed_to_default() -> None:
    session = MagicMock()
    session.scalars.return_value = [
        SimpleNamespace(
            indicator_code="MACD",
            market_type="STOCK",
            timeframe="1D",
            parameter_payload={"fast": 30, "slow": 10, "signal": 9},
            version=1,
            is_active=True,
        )
    ]
    params = IndicatorParameterService(session).resolve_engine_params()
    # invalid payload skipped → still system defaults for macd
    assert params.macd_fast == 12
    assert params.macd_slow == 26


@pytest.mark.unit
def test_restore_system_defaults_deactivates_active_rows() -> None:
    session = MagicMock()
    row = SimpleNamespace(is_active=True, updated_at=None)
    session.scalars.return_value = [row]
    count = IndicatorParameterService(session).restore_system_defaults()
    assert count == 1
    assert row.is_active is False
    session.flush.assert_called()


@pytest.mark.unit
def test_strategy_definition_snapshot_not_confused_with_indicator_params() -> None:
    """지표 파라미터는 전략 Definition 고정 Snapshot과 별개 도메인."""

    from stock_platform.indicators import parameter_entities as pe

    assert pe.IndicatorParameterConfigEntity.__tablename__ == (
        "indicator_parameter_config"
    )
    assert pe.IndicatorParameterConfigEntity.__table_args__["schema"] == (
        "market"
    )


@pytest.mark.unit
def test_indicator_engine_params_asdict_for_api() -> None:
    """slots=True dataclass 는 __dict__ 없음 — Admin list API 는 asdict 필요."""
    from dataclasses import asdict

    from stock_platform.indicators.parameter_service import IndicatorEngineParams

    params = IndicatorEngineParams()
    with pytest.raises(AttributeError):
        _ = params.__dict__
    payload = asdict(params)
    assert payload["rsi_period"] == 14
    assert payload["source"] == "SYSTEM_DEFAULT"
