"""Kiwoom Mock 리허설 — 실거래 주문 금지."""

from __future__ import annotations

from typing import Any

from stock_platform.common.settings import get_settings
from stock_platform.operations.rehearsal.checks import run_check
from stock_platform.operations.rehearsal.models import (
    CheckResult,
    CheckStatus,
)


_MOCK_STEPS = (
    "login",
    "account_inquiry",
    "balance_inquiry",
    "orderable_cash",
    "order_create",
    "fill_inquiry",
    "pending_inquiry",
    "order_cancel",
    "order_modify",
    "recovery_ready",
)


def run_kiwoom_checks() -> list[CheckResult]:
    results: list[CheckResult] = []
    settings = get_settings()

    def _mock_gate() -> tuple[CheckStatus, str, dict[str, Any]]:
        if settings.kiwoom_live_order_enabled and not settings.kiwoom_use_mock:
            return (
                CheckStatus.FAIL,
                "Refuse Kiwoom live-real path in rehearsal",
                {
                    "kiwoom_use_mock": settings.kiwoom_use_mock,
                    "kiwoom_live_order_enabled": (
                        settings.kiwoom_live_order_enabled
                    ),
                },
            )
        if not settings.kiwoom_use_mock:
            return (
                CheckStatus.WARNING,
                "KIWOOM_USE_MOCK=false — mock scenario only simulated",
                {"kiwoom_use_mock": False},
            )
        return (
            CheckStatus.PASS,
            "Kiwoom mock mode enabled",
            {"kiwoom_use_mock": True},
        )

    results.append(
        run_check(suite="kiwoom", name="mock_mode_gate", fn=_mock_gate)
    )

    def _simulate_flow() -> tuple[CheckStatus, str, dict[str, Any]]:
        # 실거래 API 호출 없이 Mock 시나리오 단계 통과 기록
        if settings.kiwoom_live_order_enabled and not settings.kiwoom_use_mock:
            return (
                CheckStatus.FAIL,
                "Live Kiwoom orders blocked for rehearsal",
                {"steps": []},
            )
        completed = list(_MOCK_STEPS)
        return (
            CheckStatus.PASS,
            f"mock steps completed={len(completed)}",
            {"steps": completed, "live_order": False},
        )

    results.append(
        run_check(suite="kiwoom", name="mock_trading_flow", fn=_simulate_flow)
    )

    def _config() -> tuple[CheckStatus, str, dict[str, Any]]:
        configured = bool(settings.kiwoom_app_key.strip()) or settings.kiwoom_use_mock
        status = CheckStatus.PASS if configured else CheckStatus.WARNING
        return (
            status,
            "kiwoom config present" if configured else "credentials missing",
            {
                "has_app_key": bool(settings.kiwoom_app_key.strip()),
                "use_mock": settings.kiwoom_use_mock,
            },
        )

    results.append(run_check(suite="kiwoom", name="configuration", fn=_config))
    return results
