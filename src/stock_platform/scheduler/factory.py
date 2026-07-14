from __future__ import annotations

from sqlalchemy.orm import Session

from stock_platform.scheduler.handlers import (
    SchedulerHandlers,
)
from stock_platform.scheduler.registry import JobRegistry


def build_job_registry(
    session: Session,
) -> JobRegistry:
    handlers = SchedulerHandlers(session)
    registry = JobRegistry()

    registry.register(
        name="candidate_screening",
        group="STRATEGY",
        description=(
            "규칙 기반 후보선정 결과를 계산하고 저장합니다."
        ),
        handler=handlers.run_candidate_screening,
    )

    registry.register(
        name="ai_orchestration",
        group="AI",
        description=(
            "뉴스·공시 컨텍스트를 결합해 AI 후보분석을 "
            "실행하고 저장합니다."
        ),
        handler=handlers.run_ai_orchestration,
    )

    registry.register(
        name="position_planning",
        group="RISK",
        description=(
            "최신 AI 후보에 위험관리 정책을 적용해 "
            "포지션 계획을 생성합니다."
        ),
        handler=handlers.run_position_planning,
    )

    return registry
