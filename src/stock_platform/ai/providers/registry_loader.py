"""STEP 11-3 — DB/ENV Source of Truth 로더 + Registry Reload."""

from __future__ import annotations

from typing import Any

import structlog
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from stock_platform.ai.providers.config import (
    AIProviderConfig,
    load_provider_configs_from_settings,
)
from stock_platform.ai.providers.manager import AIManager, get_ai_manager, reset_ai_manager
from stock_platform.ai.providers.registry import (
    AIProviderRegistry,
    build_default_registry,
)

logger = structlog.get_logger(__name__)


def db_has_provider_configurations(session: Session) -> bool:
    try:
        from stock_platform.ai.providers.management_entities import (
            AIProviderConfigurationEntity,
        )

        count = session.scalar(
            select(func.count()).select_from(AIProviderConfigurationEntity)
        )
        return int(count or 0) > 0
    except Exception as exc:  # noqa: BLE001
        logger.warning("ai_provider_db_probe_failed", error=type(exc).__name__)
        return False


def load_runtime_configs(
    session: Session | None,
) -> tuple[list[AIProviderConfig], str]:
    """DB 우선, 실패/없음 시 env bootstrap. 반환: (configs, source)."""

    if session is None:
        return load_provider_configs_from_settings(), "ENV"

    try:
        if not db_has_provider_configurations(session):
            return load_provider_configs_from_settings(), "ENV_BOOTSTRAP"

        from stock_platform.ai.providers.management_service import (
            AIProviderManagementService,
        )

        configs = AIProviderManagementService(session).to_runtime_configs()
        if not any(c.provider_id == "mock" for c in configs):
            env_configs = load_provider_configs_from_settings()
            mock = next(
                (c for c in env_configs if c.provider_id == "mock"), None
            )
            if mock:
                configs.append(mock)
        return configs, "DB"
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "ai_provider_db_load_failed_fail_closed",
            error=type(exc).__name__,
        )
        env_configs = load_provider_configs_from_settings()
        mock_only = [c for c in env_configs if c.provider_id == "mock"]
        for config in mock_only:
            config.enabled = True
            config.is_default = True
        return mock_only, "FAIL_CLOSED_MOCK"


def build_registry_from_session(
    session: Session | None,
) -> tuple[AIProviderRegistry, str]:
    configs, source = load_runtime_configs(session)
    return build_default_registry(configs), source


def bootstrap_ai_manager_from_db(session: Session | None = None) -> str:
    """Startup용 — DB SoT 로드. 실패 시 Fail Closed Mock."""

    owns_session = session is None
    if owns_session:
        from stock_platform.database.session import get_session_factory

        session = get_session_factory()()
    assert session is not None
    try:
        registry, source = build_registry_from_session(session)
        manager = AIManager(registry=registry)
        manager.config_source = source
        reset_ai_manager(manager)
        if source == "DB":
            from stock_platform.ai.providers.management_entities import (
                AIProviderConfigurationEntity,
            )
            from stock_platform.ai.providers.management_service import (
                AIProviderManagementService,
            )

            versions = {
                row.provider_code: int(row.config_version)
                for row in session.scalars(select(AIProviderConfigurationEntity))
            }
            # startup 시 history 폭주 방지
            AIProviderManagementService(session).mark_reloaded(
                success=True,
                loaded_versions=versions,
                actor="STARTUP",
                write_history=False,
            )
        logger.info("ai_provider_manager_bootstrapped", source=source)
        return source
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "ai_provider_bootstrap_failed_mock_only",
            error=type(exc).__name__,
        )
        env_configs = load_provider_configs_from_settings()
        mock_only = [c for c in env_configs if c.provider_id == "mock"]
        for config in mock_only:
            config.enabled = True
            config.is_default = True
        manager = AIManager(registry=build_default_registry(mock_only))
        manager.config_source = "FAIL_CLOSED_MOCK"
        reset_ai_manager(manager)
        return "FAIL_CLOSED_MOCK"
    finally:
        if owns_session:
            session.close()


def reload_ai_manager_from_db(
    session: Session,
    *,
    actor: str = "SYSTEM",
) -> dict[str, Any]:
    """DB commit 이후 호출 — 실패 시 기존 Manager 유지."""

    from stock_platform.ai.providers.management_entities import (
        AIProviderConfigurationEntity,
    )
    from stock_platform.ai.providers.management_service import (
        AIProviderManagementService,
    )

    old = get_ai_manager()
    try:
        registry, source = build_registry_from_session(session)
        new_manager = AIManager(registry=registry)
        new_manager.config_source = source
        for pid, metrics in old._metrics.items():
            new_manager._metrics[pid] = metrics
        for pid, circuit in old._circuits.items():
            if registry.get(pid) is not None:
                new_manager._circuits[pid] = circuit

        # atomic swap — 실패 시 여기까지 도달하지 않음
        reset_ai_manager(new_manager)

        versions = {
            row.provider_code: int(row.config_version)
            for row in session.scalars(select(AIProviderConfigurationEntity))
        }
        AIProviderManagementService(session).mark_reloaded(
            success=True,
            loaded_versions=versions,
            actor=actor,
            write_history=True,
        )
        return {
            "ok": True,
            "source": source,
            "provider_count": len(registry.list_ids()),
            "loaded_versions": versions,
        }
    except Exception as exc:  # noqa: BLE001
        logger.exception("ai_provider_registry_reload_failed")
        try:
            AIProviderManagementService(session).mark_reloaded(
                success=False,
                loaded_versions={},
                actor=actor,
            )
        except Exception:  # noqa: BLE001
            session.rollback()
        return {
            "ok": False,
            "error": type(exc).__name__,
            "kept_existing_manager": True,
        }
