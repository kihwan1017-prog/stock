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
def test_validate_trading_cross_kiwoom_option_d_accepted() -> None:
    """Kiwoom catalog LIVE + shared MOCK 은 Option D 에서 저장 허용."""

    service = AppSettingService(
        MagicMock(), settings=MagicMock()
    )
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


@pytest.mark.unit
def test_role_model_catalog_keys_present() -> None:
    """역할 모델이 AI 설정 카탈로그에 등록되어 저장 경로를 재사용한다."""

    for key in (
        "analysis_llm_model",
        "trading_llm_model",
        "teacher_llm_model",
        "ollama_model",
    ):
        assert key in DEFINITION_BY_KEY
        assert DEFINITION_BY_KEY[key].category == "ai"


@pytest.mark.unit
def test_role_model_fallback_semantics_match_settings() -> None:
    """코드 SoT: ANALYSIS/TRADING은 하드코딩 기본, Teacher는 ollama_model."""

    class _S:
        analysis_llm_model = ""
        trading_llm_model = ""
        teacher_llm_model = ""
        ollama_model = "qwen3.5:4b"

        @property
        def resolved_analysis_llm_model(self) -> str:
            return (self.analysis_llm_model or "").strip() or "qwen3:1.7b"

        @property
        def resolved_trading_llm_model(self) -> str:
            return (self.trading_llm_model or "").strip() or "qwen3.5:2b"

    s = _S()
    assert s.resolved_analysis_llm_model == "qwen3:1.7b"
    assert s.resolved_trading_llm_model == "qwen3.5:2b"
    assert (s.teacher_llm_model or "").strip() or s.ollama_model == "qwen3.5:4b"


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
