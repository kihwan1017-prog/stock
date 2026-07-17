"""공통 pytest fixture.

기본 실행(`pytest`)은 external/live 테스트를 제외한다.
PostgreSQL이 필요한 테스트는 `@pytest.mark.integration`을 붙인다.
"""

from __future__ import annotations

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
