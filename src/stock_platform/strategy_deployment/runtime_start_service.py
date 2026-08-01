"""명시적 Deployment Start (READY_* → ACTIVE).

Fail Closed:
- 자동 호출 없음 (관리자 API/서비스 명시 호출만)
- RealtimeExecutionRunner / Broker WS 자동 시작 없음
- Registry `running` 기본 False (로드 허용만 하려면 enabled=True)
- confirmation_text 필수
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.strategy_deployment.models import (
    StrategyDeploymentStatus,
)
from stock_platform.strategy_deployment.entities import (
    StrategyDeploymentEntity,
)
from stock_platform.strategy_deployment.definition_entities import (
    AccountStrategyLinkEntity,
)


class RuntimeStartError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


_STARTABLE = frozenset(
    {
        StrategyDeploymentStatus.READY_TO_START.value,
        StrategyDeploymentStatus.READY_TO_OPERATE.value,
    }
)

_CONFIRMATION_PHRASE = "START RUNTIME"


@dataclass(frozen=True, slots=True)
class RuntimeStartResult:
    strategy_deployment_id: int
    previous_status: str
    new_status: str
    links_activated: int
    registry_enabled: int
    runner_started: bool
    message: str


def promote_deployment_to_active(
    session: Session,
    *,
    strategy_deployment_id: int,
    actor: str,
    confirmation_text: str,
    enable_registry: bool = True,
    activate_account_links: bool = True,
    start_execution_runner: bool = False,
) -> RuntimeStartResult:
    """
    READY_TO_START / READY_TO_OPERATE → ACTIVE.

    start_execution_runner=True 여도 이 함수는 Runner를 직접 기동하지 않고
    False를 반환한다(별도 운영 승인 게이트). Fail Closed.
    """

    text = (confirmation_text or "").strip().upper()
    if _CONFIRMATION_PHRASE not in text:
        raise RuntimeStartError(
            "CONFIRMATION_REQUIRED",
            f"confirmation_text must include '{_CONFIRMATION_PHRASE}'",
        )

    deployment = session.get(
        StrategyDeploymentEntity, int(strategy_deployment_id)
    )
    if deployment is None:
        raise RuntimeStartError(
            "DEPLOYMENT_NOT_FOUND",
            f"deployment not found: {strategy_deployment_id}",
        )

    previous = str(deployment.status_code)
    if previous not in _STARTABLE:
        raise RuntimeStartError(
            "INVALID_STATUS",
            f"deployment status {previous} is not startable",
        )

    if previous == StrategyDeploymentStatus.ACTIVE.value:
        raise RuntimeStartError(
            "ALREADY_ACTIVE",
            "deployment is already ACTIVE",
        )

    now = datetime.now(timezone.utc)
    deployment.status_code = StrategyDeploymentStatus.ACTIVE.value
    deployment.activated_at = now
    deployment.error_message = None

    links_activated = 0
    arm_live = "ARM LIVE" in text
    if activate_account_links and getattr(deployment, "strategy_id", None):
        links = session.scalars(
            select(AccountStrategyLinkEntity).where(
                AccountStrategyLinkEntity.strategy_id
                == int(deployment.strategy_id),
                AccountStrategyLinkEntity.is_active.is_(False),
            )
        ).all()
        for link in links:
            # LIVE 모드는 ARM LIVE 확인 문구 없이 자동 활성화하지 않음
            if str(deployment.mode_code).upper() == "LIVE" and not arm_live:
                continue
            link.is_active = True
            links_activated += 1

    registry_enabled = 0
    if enable_registry and getattr(deployment, "strategy_id", None):
        try:
            from stock_platform.ai.strategy_draft_approval.runtime_registration_entities import (
                StrategyRuntimeRegistryEntity,
            )

            registries = session.scalars(
                select(StrategyRuntimeRegistryEntity).where(
                    StrategyRuntimeRegistryEntity.strategy_definition_id
                    == int(deployment.strategy_id),
                    StrategyRuntimeRegistryEntity.enabled.is_(False),
                )
            ).all()
            for row in registries:
                if str(row.execution_mode).upper() == "LIVE" and not arm_live:
                    continue
                row.enabled = True
                row.running = False
                registry_enabled += 1
        except Exception as exc:  # noqa: BLE001
            raise RuntimeStartError(
                "REGISTRY_UPDATE_FAILED",
                str(exc),
            ) from exc

    # 감사 히스토리 (가능 시)
    try:
        from stock_platform.strategy_deployment.repository import (
            StrategyDeploymentRepository,
        )

        StrategyDeploymentRepository(session).add_history(
            deployment_id=int(deployment.strategy_deployment_id),
            action_code="PROMOTE_TO_ACTIVE",
            actor=actor,
            message=(
                f"previous={previous}; links={links_activated}; "
                f"registry_enabled={registry_enabled}; "
                f"runner_started=False"
            ),
        )
    except Exception:  # noqa: BLE001
        pass

    session.commit()

    _ = start_execution_runner  # 명시적 False 유지 — Runner 자동기동 금지

    return RuntimeStartResult(
        strategy_deployment_id=int(deployment.strategy_deployment_id),
        previous_status=previous,
        new_status=StrategyDeploymentStatus.ACTIVE.value,
        links_activated=links_activated,
        registry_enabled=registry_enabled,
        runner_started=False,
        message="Deployment promoted to ACTIVE (runner not started)",
    )


def runtime_start_result_to_dict(result: RuntimeStartResult) -> dict[str, Any]:
    return {
        "strategy_deployment_id": result.strategy_deployment_id,
        "previous_status": result.previous_status,
        "new_status": result.new_status,
        "links_activated": result.links_activated,
        "registry_enabled": result.registry_enabled,
        "runner_started": result.runner_started,
        "message": result.message,
    }
