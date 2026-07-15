from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy.orm import Session

from stock_platform.strategy_deployment.performance_collector import (
    PaperDeploymentPerformanceCollector,
)
from stock_platform.strategy_deployment.performance_monitor_models import (
    DeploymentPerformancePolicy,
    DeploymentPerformanceSnapshot,
    DeploymentPerformanceStatus,
)
from stock_platform.strategy_deployment.performance_monitor_repository import (
    DeploymentPerformanceRepository,
)
from stock_platform.strategy_deployment.service import (
    PaperStrategyDeploymentService,
)


ZERO = Decimal("0")


class DeploymentPerformanceMonitorService:
    def __init__(
        self,
        *,
        session: Session,
        policy: DeploymentPerformancePolicy | None = None,
    ) -> None:
        self._session = session
        self._policy = (
            policy or DeploymentPerformancePolicy()
        )
        self._collector = (
            PaperDeploymentPerformanceCollector(session)
        )
        self._repository = (
            DeploymentPerformanceRepository(session)
        )

    def check(
        self,
        *,
        deployment_id: int,
        actor: str = "SYSTEM_PERFORMANCE_MONITOR",
    ) -> DeploymentPerformanceSnapshot:
        data = self._collector.collect(
            deployment_id=deployment_id
        )
        deployment = data["deployment"]
        metric = data["metric"]

        if metric is None:
            snapshot = DeploymentPerformanceSnapshot(
                deployment_id=deployment_id,
                strategy_code=deployment.strategy_code,
                total_trade_count=0,
                total_return_rate=ZERO,
                maximum_drawdown_rate=ZERO,
                win_rate=ZERO,
                profit_factor=None,
                consecutive_losses=0,
                status=(
                    DeploymentPerformanceStatus
                    .NOT_ENOUGH_DATA
                ),
                checks=[
                    {
                        "check_code": "PAPER_METRIC",
                        "passed": False,
                        "message": (
                            "Completed PAPER performance "
                            "metric not found"
                        ),
                        "detail": {},
                    }
                ],
                checked_at=datetime.now(timezone.utc),
            )
            self._repository.save(snapshot)
            return snapshot

        total_trade_count = int(
            metric.total_trade_count
        )
        total_return_rate = Decimal(
            metric.total_return_rate
        )
        maximum_drawdown_rate = Decimal(
            metric.maximum_drawdown_rate
        )
        win_rate = Decimal(metric.win_rate)
        profit_factor = (
            Decimal(metric.profit_factor)
            if metric.profit_factor is not None
            else None
        )
        consecutive_losses = int(
            data["consecutive_losses"]
        )

        checks = [
            self._check(
                "TRADE_COUNT",
                total_trade_count
                >= self._policy.minimum_trade_count,
                "Minimum trade count",
                {
                    "actual": total_trade_count,
                    "minimum": (
                        self._policy.minimum_trade_count
                    ),
                },
            ),
            self._check(
                "TOTAL_RETURN",
                total_return_rate
                >= self._policy.minimum_total_return_rate,
                "Minimum total return",
                {
                    "actual": str(total_return_rate),
                    "minimum": str(
                        self._policy
                        .minimum_total_return_rate
                    ),
                },
            ),
            self._check(
                "MAXIMUM_DRAWDOWN",
                maximum_drawdown_rate
                <= self._policy.maximum_drawdown_rate,
                "Maximum drawdown limit",
                {
                    "actual": str(
                        maximum_drawdown_rate
                    ),
                    "maximum": str(
                        self._policy
                        .maximum_drawdown_rate
                    ),
                },
            ),
            self._check(
                "WIN_RATE",
                win_rate
                >= self._policy.minimum_win_rate,
                "Minimum win rate",
                {
                    "actual": str(win_rate),
                    "minimum": str(
                        self._policy.minimum_win_rate
                    ),
                },
            ),
            self._check(
                "PROFIT_FACTOR",
                (
                    profit_factor is not None
                    and profit_factor
                    >= self._policy
                    .minimum_profit_factor
                ),
                "Minimum profit factor",
                {
                    "actual": (
                        str(profit_factor)
                        if profit_factor is not None
                        else None
                    ),
                    "minimum": str(
                        self._policy
                        .minimum_profit_factor
                    ),
                },
            ),
            self._check(
                "CONSECUTIVE_LOSSES",
                consecutive_losses
                <= self._policy
                .maximum_consecutive_losses,
                "Maximum consecutive losses",
                {
                    "actual": consecutive_losses,
                    "maximum": (
                        self._policy
                        .maximum_consecutive_losses
                    ),
                },
            ),
        ]

        if total_trade_count < (
            self._policy.minimum_trade_count
        ):
            status = (
                DeploymentPerformanceStatus
                .NOT_ENOUGH_DATA
            )
        elif all(item["passed"] for item in checks):
            status = DeploymentPerformanceStatus.HEALTHY
        else:
            critical_failed = any(
                not item["passed"]
                for item in checks
                if item["check_code"]
                in {
                    "TOTAL_RETURN",
                    "MAXIMUM_DRAWDOWN",
                    "CONSECUTIVE_LOSSES",
                }
            )
            status = (
                DeploymentPerformanceStatus.STOP_REQUIRED
                if critical_failed
                else DeploymentPerformanceStatus.WARNING
            )

        if (
            status
            == DeploymentPerformanceStatus.STOP_REQUIRED
            and self._policy.auto_stop_enabled
            and deployment.status_code == "ACTIVE"
        ):
            PaperStrategyDeploymentService(
                self._session
            ).stop(
                deployment_id=deployment_id,
                actor=actor,
                reason=(
                    "Paper strategy automatically stopped "
                    "because performance policy failed"
                ),
            )
            status = DeploymentPerformanceStatus.STOPPED

        snapshot = DeploymentPerformanceSnapshot(
            deployment_id=deployment_id,
            strategy_code=deployment.strategy_code,
            total_trade_count=total_trade_count,
            total_return_rate=total_return_rate,
            maximum_drawdown_rate=(
                maximum_drawdown_rate
            ),
            win_rate=win_rate,
            profit_factor=profit_factor,
            consecutive_losses=consecutive_losses,
            status=status,
            checks=checks,
            checked_at=datetime.now(timezone.utc),
        )
        self._repository.save(snapshot)
        return snapshot

    @staticmethod
    def _check(
        code: str,
        passed: bool,
        message: str,
        detail: dict,
    ) -> dict:
        return {
            "check_code": code,
            "passed": passed,
            "message": message,
            "detail": detail,
        }
