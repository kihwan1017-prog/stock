from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from stock_platform.ai.ollama_client import OllamaClient
from stock_platform.ai.orchestration_service import (
    CandidateAnalysisOrchestrator,
)
from stock_platform.common.settings import get_settings
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
        service = CandidateRunService(self._session)

        run = service.execute_and_save(
            exchange_code=str(
                payload.get("exchange_code", "KRX")
            ).upper(),
            as_of_date=date.fromisoformat(
                str(payload["as_of_date"])
            ),
            limit=int(payload.get("limit", 30)),
            minimum_score=Decimal(
                str(payload.get("minimum_score", 0))
            ),
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
                        "KRX",
                    )
                ).upper(),
                limit=int(payload.get("limit", 10)),
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
        service = CandidatePositionPlanService(
            self._session
        )

        result = service.create_plans(
            exchange_code=str(
                payload.get("exchange_code", "KRX")
            ).upper(),
            policy_id=int(payload["policy_id"]),
            portfolio_value=Decimal(
                str(payload["portfolio_value"])
            ),
            available_cash=Decimal(
                str(payload["available_cash"])
            ),
            current_position_count=int(
                payload.get(
                    "current_position_count",
                    0,
                )
            ),
            limit=int(payload.get("limit", 5)),
            minimum_ai_score=Decimal(
                str(
                    payload.get(
                        "minimum_ai_score",
                        0,
                    )
                )
            ),
            minimum_confidence=Decimal(
                str(
                    payload.get(
                        "minimum_confidence",
                        0,
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
