from __future__ import annotations

from sqlalchemy.orm import Session

from stock_platform.scheduler.handlers import (
    SchedulerHandlers,
)
from stock_platform.scheduler.portfolio_snapshot_job import (
    PortfolioEquitySnapshotJob,
)
from stock_platform.scheduler.registry import JobRegistry
from stock_platform.scheduler.report_job import (
    DailyReportJob,
)
from stock_platform.scheduler.watchlist_news_sync_job import (
    WatchlistNewsSyncJob,
)
from stock_platform.scheduler.watchlist_disclosure_sync_job import (
    WatchlistDisclosureSyncJob,
)


def build_job_registry(
    session: Session,
) -> JobRegistry:
    handlers = SchedulerHandlers(session)
    report_job = DailyReportJob(session)
    equity_job = PortfolioEquitySnapshotJob(session)
    news_job = WatchlistNewsSyncJob(session)
    disclosure_job = WatchlistDisclosureSyncJob(session)
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
        name="portfolio_equity_snapshot",
        group="PORTFOLIO",
        description=(
            "장후 회원별 Paper 계좌 일별 자산 스냅샷을 저장합니다. "
            "PAPER/LIVE mode_code를 지원합니다."
        ),
        handler=equity_job.execute,
    )

    registry.register(
        name="watchlist_news_sync",
        group="NEWS",
        description=(
            "활성 관심종목(news_enabled) distinct 심볼만 Naver 뉴스를 수집합니다. "
            "공용 저장·사용자 중복 저장 없음."
        ),
        handler=news_job.execute,
    )

    registry.register(
        name="watchlist_disclosure_sync",
        group="DISCLOSURE",
        description=(
            "활성 관심종목(disclosure_enabled) KRX 심볼만 DART 공시를 수집합니다. "
            "공용 저장·사용자 중복 수집 없음."
        ),
        handler=disclosure_job.execute,
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
