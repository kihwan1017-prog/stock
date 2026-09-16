"""PROD DB에 pytest mutation이 닿기 전에 FAIL FAST.

production runtime에서는 import 되지 않는다. conftest 전용.
ALLOW_PROD_TEST 같은 우회 스위치는 두지 않는다.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

_TRUTHY = frozenset({"1", "true", "yes", "on"})
_PROD_APP_ENVS = frozenset({"prod", "production", "staging"})
_KNOWN_PROD_DB_NAMES = frozenset({"stock_platform"})
_KNOWN_PROD_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})

REFUSE_MESSAGE = (
    "REFUSING_TO_RUN_TESTS_AGAINST_PRODUCTION_DATABASE: "
    "pytest resolved the MiniPC/runtime production database. "
    "Set STOCK_PLATFORM_TEST_DATABASE_URL to an isolated DB that differs "
    "from production, or STOCK_PLATFORM_DISABLE_ENV_FILE=true without "
    "a production env file. Broad `pytest` against stock_platform is forbidden."
)


class ProductionDatabaseTestBlocked(RuntimeError):
    """세션 시작 전 production DB 차단."""


@dataclass(frozen=True)
class ProdTestGuardDecision:
    action: str  # ALLOW | BLOCK
    reason: str
    signals: tuple[str, ...]


def _flag(name: str) -> bool:
    return (os.environ.get(name) or "").strip().lower() in _TRUTHY


def _norm(value: str | None) -> str:
    return (value or "").strip().lower()


def evaluate_prod_test_guard(
    *,
    app_env: str | None,
    db_name: str | None,
    db_host: str | None,
    test_database_url: str | None,
    resolved_database_url: str | None,
    env_file_disabled: bool = False,
    settings_available: bool = True,
) -> ProdTestGuardDecision:
    """순수 판정 — DB 연결 없음.

    BLOCK 조건(복수 신호):
    - settings가 해석됨
    - APP_ENV 가 production-like
    - DB name 이 알려진 PROD 이름
    - TEST_DATABASE_URL 이 없거나 resolved URL 과 동일
    ALLOW 조건:
    - settings 없음/미구성
    - env file disable + settings 없음
    - explicit isolated TEST_DATABASE_URL 이 resolved 와 다름
    - app_env 가 local/dev 이고 db_name 이 알려진 PROD 가 아님
    """

    signals: list[str] = []
    test_url = (test_database_url or "").strip()
    resolved = (resolved_database_url or "").strip()
    env = _norm(app_env)
    name = _norm(db_name)
    host = _norm(db_host)

    if test_url and resolved and test_url != resolved:
        return ProdTestGuardDecision(
            "ALLOW",
            "isolated_test_database_url",
            ("test_url_differs_from_resolved",),
        )
    if test_url and not resolved:
        return ProdTestGuardDecision(
            "ALLOW",
            "explicit_test_database_url",
            ("test_url_present",),
        )

    if not settings_available:
        return ProdTestGuardDecision(
            "ALLOW",
            "settings_unavailable_isolated",
            ("settings_unavailable",),
        )

    if env_file_disabled and not env and not name:
        return ProdTestGuardDecision(
            "ALLOW",
            "env_file_disabled_no_prod_signals",
            ("env_file_disabled",),
        )

    prod_env = env in _PROD_APP_ENVS
    known_prod_name = name in _KNOWN_PROD_DB_NAMES
    local_prod_host = host in _KNOWN_PROD_HOSTS or host == ""
    if prod_env:
        signals.append(f"app_env={env}")
    if known_prod_name:
        signals.append(f"db_name={name}")
    if host:
        signals.append(f"db_host={host}")
    if not test_url:
        signals.append("test_database_url_absent")
    elif test_url == resolved:
        signals.append("test_database_url_equals_resolved")

    # 이름만 test 가 아니라고 BLOCK 하지 않는다. prod env + known name 필수.
    if prod_env and known_prod_name and (not test_url or test_url == resolved):
        if local_prod_host or host:
            return ProdTestGuardDecision(
                "BLOCK",
                "production_database_resolved",
                tuple(signals),
            )

    return ProdTestGuardDecision(
        "ALLOW",
        "not_production_like",
        tuple(signals) or ("no_prod_signals",),
    )


def refuse_if_blocked(decision: ProdTestGuardDecision) -> None:
    if decision.action == "BLOCK":
        raise ProductionDatabaseTestBlocked(
            f"{REFUSE_MESSAGE} reason={decision.reason} signals={list(decision.signals)}"
        )


def inspect_runtime_for_guard() -> ProdTestGuardDecision:
    """현재 프로세스 설정만 읽는다. DB에 쓰지 않는다."""

    test_url = (os.environ.get("STOCK_PLATFORM_TEST_DATABASE_URL") or "").strip()
    resolved_url = (os.environ.get("DATABASE_URL") or "").strip()
    env_disabled = _flag("STOCK_PLATFORM_DISABLE_ENV_FILE")

    app_env = os.environ.get("APP_ENV") or os.environ.get("STOCK_PLATFORM_APP_ENV")
    db_name = os.environ.get("DB_NAME")
    db_host = os.environ.get("DB_HOST")

    settings_available = bool(app_env or db_name)
    # env 파일 disable 이면 Settings/레거시 PROD 경로를 읽지 않는다.
    if not env_disabled:
        try:
            from stock_platform.common.settings import get_settings

            settings = get_settings()
            settings_available = True
            app_env = settings.app_env
            db_name = str(settings.db_name)
            db_host = str(settings.db_host)
            if not resolved_url:
                resolved_url = settings.database_url
        except Exception:
            settings_available = bool(app_env or db_name)

    return evaluate_prod_test_guard(
        app_env=app_env,
        db_name=db_name,
        db_host=db_host,
        test_database_url=test_url,
        resolved_database_url=resolved_url,
        env_file_disabled=env_disabled,
        settings_available=settings_available,
    )


def guard_pytest_session() -> None:
    """pytest_sessionstart 훅. production-like면 즉시 중단."""

    refuse_if_blocked(inspect_runtime_for_guard())
