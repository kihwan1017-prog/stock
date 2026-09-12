"""공통 pytest fixture.

기본 실행(`pytest`)은 external/live 테스트를 제외한다.
PostgreSQL이 필요한 테스트는 `@pytest.mark.integration`을 붙인다.

STEP3: 테스트 런타임에서 Live 주문 플래그가 머신 env 파일에
오염되지 않도록 안전 기본값을 강제한다.
"""

from __future__ import annotations

import os

import pytest


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        "unit: 단위 테스트 (외부 의존 없음)",
    )
    config.addinivalue_line(
        "markers",
        "integration: PostgreSQL 등 로컬 리소스 필요",
    )
    config.addinivalue_line(
        "markers",
        "external: 외부 HTTP/API 호출",
    )
    config.addinivalue_line(
        "markers",
        "live: 실전 계좌/주문",
    )

    # 설정 로더가 테스트 모드임을 인식
    os.environ.setdefault("STOCK_PLATFORM_TESTING", "1")

    # env 파일보다 프로세스 환경변수가 우선이므로 Live 게이트 오염 차단.
    # 개별 테스트가 monkeypatch 로 true 를 넣으면 그 값이 이긴다.
    os.environ["KIWOOM_LIVE_ORDER_ENABLED"] = "false"
    os.environ["UPBIT_LIVE_ORDER_ENABLED"] = "false"
    os.environ["GLOBAL_LIVE_ORDER_ENABLED"] = "false"
    os.environ.setdefault("KIWOOM_USE_MOCK", "true")
    os.environ.setdefault("UPBIT_USE_MOCK", "true")
    os.environ.setdefault("PAPER_TRADING_ENABLED", "true")
    # 테스트 중 실제 Telegram/Slack/Discord 발송 방지
    os.environ["TELEGRAM_ENABLED"] = "false"
    os.environ["TELEGRAM_OPS_ENABLED"] = "false"
    os.environ["SLACK_ENABLED"] = "false"
    os.environ["DISCORD_ENABLED"] = "false"


def pytest_collection_modifyitems(
    config: pytest.Config, items: list[pytest.Item]
) -> None:
    """integration 테스트는 전용 TEST DB가 있을 때만 실행한다.

    STOCK_PLATFORM_TEST_DATABASE_URL 이 없거나 production DATABASE_URL 과
    같으면 PostgreSQL integration 을 skip 한다. production TradingOrder/
    Outbox 오염을 막기 위한 fail-closed 이다.
    """

    test_url = (os.environ.get("STOCK_PLATFORM_TEST_DATABASE_URL") or "").strip()
    prod_url = (os.environ.get("DATABASE_URL") or "").strip()
    env_file = (os.environ.get("STOCK_PLATFORM_ENV_FILE") or "").strip()
    allow = test_url and (not prod_url or test_url != prod_url)
    if allow:
        os.environ["DATABASE_URL"] = test_url
        return

    skip_marker = pytest.mark.skip(
        reason=(
            "STOCK_PLATFORM_TEST_DATABASE_URL required and must differ "
            "from production DATABASE_URL (test isolation)"
        )
    )
    for item in items:
        if item.get_closest_marker("integration"):
            item.add_marker(skip_marker)
    # env 파일이 production 을 가리켜도 unit 테스트는 Settings 캐시만 쓴다.
    _ = env_file

@pytest.fixture(autouse=True)
def _clear_settings_cache_between_tests() -> None:
    """테스트 간 Settings / DB engine 캐시 누수 방지."""

    from stock_platform.common.settings import clear_settings_cache

    clear_settings_cache()
    yield
    clear_settings_cache()
    try:
        from stock_platform.database.session import (
            get_engine,
            get_session_factory,
        )

        get_engine.cache_clear()
        get_session_factory.cache_clear()
    except Exception:
        pass
    try:
        from stock_platform.notification.runtime import (
            reset_notification_runtime,
        )

        reset_notification_runtime()
    except Exception:
        pass
