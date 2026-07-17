from __future__ import annotations

from sqlalchemy.orm import Session

from stock_platform.scheduler.handlers import (
    SchedulerHandlers,
)
from stock_platform.scheduler.registry import JobRegistry
from stock_platform.scheduler.report_job import (
    DailyReportJob,
)


def build_job_registry(
    session: Session,
) -> JobRegistry:
    handlers = SchedulerHandlers(session)
    report_job = DailyReportJob(session)
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

    registry.register(
        name="daily_operations_report",
        group="OPERATION",
        description=(
            "일일 파이프라인, 작업 실패, 후보, 포지션, "
            "손익을 요약해 저장합니다."
        ),
        handler=report_job.execute,
    )

    registry.register(
        name="upbit_krw_daily_sync",
        group="MARKET",
        description=(
            "업비트 KRW 마켓 종목·일봉을 동기화합니다. "
            "기본 lookback은 3년이며 resume을 지원합니다."
        ),
        handler=handlers.run_upbit_krw_daily_sync,
    )

    registry.register(
        name="indicator_daily_batch",
        group="MARKET",
        description=(
            "활성 종목의 일봉 지표(MA/EMA/RSI/52주 등)를 "
            "계산해 market.indicator_daily에 저장합니다."
        ),
        handler=handlers.run_indicator_daily_batch,
    )

    return registry
