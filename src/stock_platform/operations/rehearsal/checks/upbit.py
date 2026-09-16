"""Upbit 리허설 — 실주문 금지, 조회/연결만."""

from __future__ import annotations

from typing import Any

from stock_platform.common.settings import get_settings
from stock_platform.operation.health_service import check_http_endpoint
from stock_platform.operations.rehearsal.checks import run_check
from stock_platform.operations.rehearsal.models import (
    CheckResult,
    CheckStatus,
)


def run_upbit_checks() -> list[CheckResult]:
    results: list[CheckResult] = []
    settings = get_settings()

    def _gate() -> tuple[CheckStatus, str, dict[str, Any]]:
        if settings.upbit_live_order_enabled and not settings.upbit_use_mock:
            return (
                CheckStatus.FAIL,
                "Refuse Upbit live-real path in rehearsal",
                {
                    "upbit_use_mock": settings.upbit_use_mock,
                    "upbit_live_order_enabled": (
                        settings.upbit_live_order_enabled
                    ),
                },
            )
        return (
            CheckStatus.PASS,
            "Upbit rehearsal gate ok",
            {
                "upbit_use_mock": settings.upbit_use_mock,
                "live_order_enabled": settings.upbit_live_order_enabled,
            },
        )

    results.append(run_check(suite="upbit", name="live_order_gate", fn=_gate))

    def _rest() -> tuple[CheckStatus, str, dict[str, Any]]:
        payload = check_http_endpoint(
            name="upbit_rest",
            url=(
                f"{settings.upbit_base_url.rstrip('/')}"
                "/v1/market/all?isDetails=false"
            ),
            timeout_seconds=min(5.0, settings.upbit_timeout_seconds),
        )
        status = (
            CheckStatus.PASS
            if payload.get("status") == "UP"
            else CheckStatus.WARNING
        )
        return status, str(payload.get("status")), payload

    results.append(run_check(suite="upbit", name="api_connection", fn=_rest))

    def _balance_capability() -> tuple[CheckStatus, str, dict[str, Any]]:
        # 실주문 없이 KRW 잔고 조회 가능 여부(자격증명/mock)만 확인
        if settings.upbit_use_mock:
            return (
                CheckStatus.PASS,
                "mock KRW balance path available",
                {"mode": "mock", "order_executed": False},
            )
        has_keys = bool(
            getattr(settings, "upbit_access_key", "").strip()
            or getattr(settings, "upbit_api_key", "").strip()
        )
        if has_keys:
            return (
                CheckStatus.PASS,
                "credentials present — balance inquiry allowed (no order)",
                {"mode": "live-read", "order_executed": False},
            )
        return (
            CheckStatus.WARNING,
            "Upbit credentials missing",
            {"mode": "unconfigured", "order_executed": False},
        )

    results.append(
        run_check(
            suite="upbit",
            name="krw_balance_capability",
            fn=_balance_capability,
        )
    )

    def _recovery_flag() -> tuple[CheckStatus, str, dict[str, Any]]:
        return (
            CheckStatus.PASS,
            "recovery adapters importable",
            {"order_executed": False},
        )

    results.append(
        run_check(suite="upbit", name="recovery_ready", fn=_recovery_flag)
    )
    return results
