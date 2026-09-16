"""PROD TEST GUARD unit — DB 연결/mutation 없음."""

from __future__ import annotations

import pytest

from tests.prod_test_guard import (
    ProductionDatabaseTestBlocked,
    evaluate_prod_test_guard,
    refuse_if_blocked,
)


def test_production_like_config_is_blocked() -> None:
    decision = evaluate_prod_test_guard(
        app_env="production",
        db_name="stock_platform",
        db_host="localhost",
        test_database_url=None,
        resolved_database_url="postgresql+psycopg://stock_app@localhost:5432/stock_platform",
        settings_available=True,
    )
    assert decision.action == "BLOCK"
    assert decision.reason == "production_database_resolved"
    assert "app_env=production" in decision.signals
    assert "db_name=stock_platform" in decision.signals
    with pytest.raises(ProductionDatabaseTestBlocked, match="REFUSING_TO_RUN_TESTS_AGAINST_PRODUCTION_DATABASE"):
        refuse_if_blocked(decision)


def test_isolated_test_url_is_allowed() -> None:
    decision = evaluate_prod_test_guard(
        app_env="production",
        db_name="stock_platform",
        db_host="localhost",
        test_database_url="postgresql+psycopg://stock_app@localhost:5432/stock_platform_pytest",
        resolved_database_url="postgresql+psycopg://stock_app@localhost:5432/stock_platform",
        settings_available=True,
    )
    assert decision.action == "ALLOW"
    assert decision.reason == "isolated_test_database_url"


def test_local_non_prod_name_is_allowed() -> None:
    decision = evaluate_prod_test_guard(
        app_env="local",
        db_name="stock_platform_dev",
        db_host="localhost",
        test_database_url=None,
        resolved_database_url=None,
        settings_available=True,
    )
    assert decision.action == "ALLOW"
    assert decision.reason == "not_production_like"


def test_missing_settings_is_allowed() -> None:
    decision = evaluate_prod_test_guard(
        app_env=None,
        db_name=None,
        db_host=None,
        test_database_url=None,
        resolved_database_url=None,
        env_file_disabled=True,
        settings_available=False,
    )
    assert decision.action == "ALLOW"
    assert decision.reason == "settings_unavailable_isolated"


def test_db_name_without_prod_env_is_not_enough_to_block() -> None:
    """이름에 test가 없다는 이유만으로 BLOCK 하지 않는다."""

    decision = evaluate_prod_test_guard(
        app_env="local",
        db_name="stock_platform",
        db_host="localhost",
        test_database_url=None,
        resolved_database_url=None,
        settings_available=True,
    )
    assert decision.action == "ALLOW"
