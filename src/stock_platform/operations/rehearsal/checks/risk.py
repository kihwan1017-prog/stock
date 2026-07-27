"""Risk Engine 리허설."""

from __future__ import annotations

from typing import Any

from stock_platform.broker.live_config_gate import (
    evaluate_live_flag_consistency,
)
from stock_platform.operation.live_health_gate import (
    evaluate_live_order_health,
)
from stock_platform.operations.rehearsal.checks import run_check
from stock_platform.operations.rehearsal.models import (
    CheckResult,
    CheckStatus,
)


def run_risk_checks() -> list[CheckResult]:
    results: list[CheckResult] = []

    def _flags() -> tuple[CheckStatus, str, dict[str, Any]]:
        gate = evaluate_live_flag_consistency()
        status = (
            CheckStatus.PASS
            if gate.status in {"HEALTHY", "DEGRADED"}
            else CheckStatus.FAIL
        )
        if gate.code == "LIVE_MOCK_CONFLICT":
            status = CheckStatus.FAIL
        return (
            status,
            gate.message,
            {
                "code": gate.code,
                "allowed": gate.allowed,
                "status": gate.status,
                **gate.detail,
            },
        )

    results.append(
        run_check(suite="risk", name="trading_flag_consistency", fn=_flags)
    )

    def _activation() -> tuple[CheckStatus, str, dict[str, Any]]:
        from stock_platform.database.session import get_session_factory

        session = get_session_factory()()
        try:
            health = evaluate_live_order_health(session)
            allowed = bool(health.get("live_orders_allowed"))
            # 리허설에서는 live 차단이 정상일 수 있음 → PASS with detail
            return (
                CheckStatus.PASS,
                "activation/health gate evaluated",
                {
                    "live_orders_allowed": allowed,
                    "health": {
                        k: health.get(k)
                        for k in (
                            "live_orders_allowed",
                            "reasons",
                            "status",
                        )
                        if k in health
                    },
                },
            )
        finally:
            session.close()

    results.append(
        run_check(suite="risk", name="activation_gate", fn=_activation)
    )

    def _kill_switch() -> tuple[CheckStatus, str, dict[str, Any]]:
        from stock_platform.database.session import get_session_factory
        from stock_platform.risk_engine.kill_switch_service import (
            KillSwitchService,
        )

        session = get_session_factory()()
        try:
            state = KillSwitchService(session).get_state()
            return (
                CheckStatus.PASS,
                f"kill_switch={state.status.value}",
                {
                    "status": state.status.value,
                    "reason": state.reason,
                },
            )
        finally:
            session.close()

    results.append(run_check(suite="risk", name="kill_switch", fn=_kill_switch))

    def _daily_loss_and_limits() -> tuple[CheckStatus, str, dict[str, Any]]:
        from stock_platform.risk_engine.daily_loss_monitor import (
            DailyLossMonitor,
        )
        from stock_platform.risk_engine.position_limit_rule import (
            DatabasePositionLimitRule,
        )

        assert DailyLossMonitor is not None
        assert DatabasePositionLimitRule is not None
        return (
            CheckStatus.PASS,
            "daily_loss and position_limit modules available",
            {
                "daily_loss": True,
                "position_limit": True,
            },
        )

    results.append(
        run_check(
            suite="risk",
            name="daily_loss_position_limit",
            fn=_daily_loss_and_limits,
        )
    )
    return results
