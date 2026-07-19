from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from stock_platform.operation.setting_catalog import (
    DEFINITION_BY_KEY,
    MASKED_VALUE,
    is_masked_input,
    parse_value,
)
from stock_platform.operation.setting_service import (
    AppSettingService,
    SettingError,
)


@pytest.mark.unit
def test_parse_and_mask_helpers() -> None:
    assert parse_value("true", "bool") is True
    assert parse_value("12.5", "float") == 12.5
    assert is_masked_input(MASKED_VALUE)
    assert is_masked_input("***")


@pytest.mark.unit
def test_secret_view_is_masked() -> None:
    repo = MagicMock()
    definition = DEFINITION_BY_KEY["kiwoom_app_key"]
    row = SimpleNamespace(
        setting_key="kiwoom_app_key",
        category="trading",
        value_text="SECRET-VALUE",
        value_type="string",
        is_secret=True,
        description=definition.description,
        updated_by="admin",
        updated_at=None,
        version=2,
    )
    service = AppSettingService(repo, settings=MagicMock())
    view = service._to_view(
        definition, row, include_secrets=False
    )
    assert view["value"] == MASKED_VALUE
    assert view["typed_value"] is None


@pytest.mark.unit
def test_validate_trading_cross_rule() -> None:
    service = AppSettingService(
        MagicMock(), settings=MagicMock()
    )
    with pytest.raises(SettingError, match="함께 사용"):
        service._validate_trading_cross(
            {
                "kiwoom_use_mock": "true",
                "kiwoom_live_order_enabled": "true",
            }
        )


@pytest.mark.unit
def test_ollama_url_validation() -> None:
    service = AppSettingService(
        MagicMock(), settings=MagicMock()
    )
    definition = DEFINITION_BY_KEY["ollama_base_url"]
    with pytest.raises(SettingError, match="http"):
        service._validate(definition, "ftp://bad")


def test_settings_routes_registered() -> None:
    from stock_platform.api.main import app
    from stock_platform.api.router import (
        collect_duplicate_operation_ids,
    )

    paths = set(app.openapi()["paths"].keys())
    assert "/api/v1/settings" in paths
    assert "/api/v1/settings/categories" in paths
    assert "/api/v1/settings/history" in paths
    assert "/api/v1/ollama/models" in paths
    assert "/api/v1/ollama/settings" in paths
    assert collect_duplicate_operation_ids(app.router) == []
