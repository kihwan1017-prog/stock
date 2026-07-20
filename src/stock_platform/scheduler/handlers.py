from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from stock_platform.ai.ollama_client import OllamaClient
from stock_platform.ai.orchestration_service import (
    CandidateAnalysisOrchestrator,
)
from stock_platform.brokers.upbit.client import (
    UpbitQuotationClient,
)
from stock_platform.collectors.upbit.batch_daily_sync_service import (
    UpbitKrwDailyBatchSyncService,
)
from stock_platform.collectors.upbit.daily_collector import (
    UpbitDailyCollector,
)
from stock_platform.collectors.upbit.instrument_sync_service import (
    UpbitInstrumentSyncService,
)
from stock_platform.collectors.upbit.sync_service import (
    UpbitDailySyncService,
)
from stock_platform.common.settings import get_settings
from stock_platform.markets.repository import (
    InstrumentRepository,
    PriceDailyRepository,
)
from stock_platform.markets.service import (
    InstrumentService,
    PriceDailyService,
)
from stock_platform.risk.allocation_service import (
    CandidatePositionPlanService,
)
from stock_platform.screener.run_service import (
    CandidateRunService,
)


class SchedulerHandlers:
    """기존 서비스들을 스케줄러 작업 단위로 감싼다."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def run_candidate_screening(
        self,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        settings = get_settings()
        # Admin 수동 실행 시 payload 비어 있으면 스케줄러 기본값 사용
        as_of_raw = payload.get("as_of_date") or date.today().isoformat()
        # 수동 실행(빈 payload): minimum_score 미지정 시 0
        # (KRX 종목 1개·저점수여도 후보가 생기도록 — 스케줄러는 값을 명시 전달)
        if "minimum_score" in payload:
            minimum_score = Decimal(str(payload["minimum_score"]))
        else:
            minimum_score = Decimal("0")
        service = CandidateRunService(self._session)

        run = service.execute_and_save(
            exchange_code=str(
                payload.get(
                    "exchange_code",
                    settings.scheduler_exchange_code,
                )
            ).upper(),
            as_of_date=date.fromisoformat(str(as_of_raw)),
            limit=int(
                payload.get(
                    "limit",
                    settings.scheduler_candidate_limit,
                )
            ),
            minimum_score=minimum_score,
            require_all_rules=bool(
                payload.get(
                    "require_all_rules",
                    False,
                )
            ),
            run_type=str(
                payload.get("run_type", "DAILY")
            ).upper(),
        )

        return {
            "run_id": run.run_id,
            "exchange_code": run.exchange_code,
            "as_of_date": run.as_of_date.isoformat(),
            "selected_count": run.selected_count,
            "status_code": run.status_code,
        }

    async def run_ai_orchestration(
        self,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        settings = get_settings()

        async with OllamaClient(
            settings=settings
        ) as client:
            service = CandidateAnalysisOrchestrator(
                session=self._session,
                ollama_client=client,
                model_name=settings.ollama_model,
            )

            result = await service.execute(
                exchange_code=str(
                    payload.get(
                        "exchange_code",
                        settings.scheduler_exchange_code,
                    )
                ).upper(),
                limit=int(
                    payload.get(
                        "limit",
                        settings.scheduler_ai_limit,
                    )
                ),
                news_limit=int(
                    payload.get("news_limit", 20)
                ),
                disclosure_limit=int(
                    payload.get(
                        "disclosure_limit",
                        20,
                    )
                ),
                lookback_days=int(
                    payload.get("lookback_days", 90)
                ),
                # 수동 빈 payload: 낮은 기준 (스케줄러는 settings 값 명시)
                minimum_ai_score=float(
                    payload.get(
                        "minimum_ai_score",
                        0,
                    )
                ),
                minimum_confidence=float(
                    payload.get(
                        "minimum_confidence",
                        0,
                    )
                ),
            )

        run = result["analysis_run"]
        ranking = result["ranking"]

        return {
            "analysis_run_id": run.analysis_run_id,
            "source_candidate_run_id": (
                ranking.source_run_id
            ),
            "selected_count": len(
                ranking.candidates
            ),
            "model": ranking.model,
        }

    def run_position_planning(
        self,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        settings = get_settings()
        service = CandidatePositionPlanService(
            self._session
        )

        result = service.create_plans(
            exchange_code=str(
                payload.get(
                    "exchange_code",
                    settings.scheduler_exchange_code,
                )
            ).upper(),
            policy_id=int(
                payload.get(
                    "policy_id",
                    settings.scheduler_policy_id,
                )
            ),
            portfolio_value=Decimal(
                str(
                    payload.get(
                        "portfolio_value",
                        settings.scheduler_portfolio_value,
                    )
                )
            ),
            available_cash=Decimal(
                str(
                    payload.get(
                        "available_cash",
                        settings.scheduler_available_cash,
                    )
                )
            ),
            current_position_count=int(
                payload.get(
                    "current_position_count",
                    0,
                )
            ),
            limit=int(
                payload.get(
                    "limit",
                    settings.scheduler_position_limit,
                )
            ),
            minimum_ai_score=Decimal(
                str(
                    payload.get(
                        "minimum_ai_score",
                        settings.scheduler_minimum_ai_score,
                    )
                )
            ),
            minimum_confidence=Decimal(
                str(
                    payload.get(
                        "minimum_confidence",
                        settings.scheduler_minimum_confidence,
                    )
                )
            ),
            allowed_actions={
                str(value).upper()
                for value in payload.get(
                    "allowed_actions",
                    ["WATCH", "REVIEW"],
                )
            },
        )

        return {
            "analysis_run_id": result.analysis_run_id,
            "planned_count": result.planned_count,
            "approved_count": result.approved_count,
            "rejected_count": result.rejected_count,
            "remaining_cash": str(
                result.remaining_cash
            ),
        }

    async def run_upbit_krw_daily_sync(
        self,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """업비트 KRW 전체 일봉 동기화 스케줄 작업."""

        instrument_service = InstrumentService(
            InstrumentRepository(self._session)
        )
        price_service = PriceDailyService(
            PriceDailyRepository(self._session),
            instrument_service=instrument_service,
        )

        start_date = (
            date.fromisoformat(str(payload["start_date"]))
            if payload.get("start_date")
            else None
        )
        end_date = (
            date.fromisoformat(str(payload["end_date"]))
            if payload.get("end_date")
            else None
        )
        market_limit = payload.get("market_limit")

        async with UpbitQuotationClient() as client:
            result = await UpbitKrwDailyBatchSyncService(
                instrument_sync=UpbitInstrumentSyncService(
                    client=client,
                    instrument_service=instrument_service,
                ),
                daily_sync=UpbitDailySyncService(
                    collector=UpbitDailyCollector(client),
                    price_service=price_service,
                    instrument_service=instrument_service,
                ),
                instrument_service=instrument_service,
            ).sync(
                start_date=start_date,
                end_date=end_date,
                lookback_years=int(
                    payload.get("lookback_years", 3)
                ),
                resume=bool(payload.get("resume", True)),
                market_limit=(
                    int(market_limit)
                    if market_limit is not None
                    else None
                ),
                max_retries=int(payload.get("max_retries", 2)),
                sync_instruments=bool(
                    payload.get("sync_instruments", True)
                ),
            )

        return result.to_dict()

    def run_indicator_daily_batch(
        self,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        """일봉 지표 batch 계산·저장."""

        from stock_platform.indicators.pipeline_service import (
            IndicatorPipelineService,
        )
        from stock_platform.indicators.repository import (
            IndicatorDailyRepository,
        )

        instrument_service = InstrumentService(
            InstrumentRepository(self._session)
        )
        pipeline = IndicatorPipelineService(
            price_service=PriceDailyService(
                PriceDailyRepository(self._session),
                instrument_service=instrument_service,
            ),
            indicator_repository=IndicatorDailyRepository(
                self._session
            ),
            instrument_service=instrument_service,
        )

        symbol_limit = payload.get("symbol_limit")
        today = date.today()
        # 수동 실행 기본: 최근 1년
        start_raw = payload.get("start_date") or (
            today.replace(year=today.year - 1)
        ).isoformat()
        end_raw = payload.get("end_date") or today.isoformat()
        result = pipeline.compute_batch(
            start_date=date.fromisoformat(str(start_raw)),
            end_date=date.fromisoformat(str(end_raw)),
            exchange_code=(
                str(payload["exchange_code"]).upper()
                if payload.get("exchange_code")
                else None
            ),
            symbol_limit=(
                int(symbol_limit)
                if symbol_limit is not None
                else None
            ),
        )
        return result.to_dict()

