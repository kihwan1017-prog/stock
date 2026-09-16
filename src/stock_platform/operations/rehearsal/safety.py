"""리허설 안전 게이트 — 실거래 경로 Fail Closed."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from stock_platform.common.settings import get_settings


@dataclass(frozen=True, slots=True)
class SafetyGateResult:
    allowed: bool
    code: str
    message: str
    detail: dict[str, Any]


def assert_rehearsal_safe(*, telegram_mode: str = "dry-run") -> SafetyGateResult:
    """
    실거래 주문이 가능한 설정이면 리허설 중단(Fail Closed).
    Mock/Paper 경로만 허용한다.
    """

    settings = get_settings()
    detail = {
        "global_live_order_enabled": settings.global_live_order_enabled,
        "kiwoom_live_order_enabled": settings.kiwoom_live_order_enabled,
        "upbit_live_order_enabled": settings.upbit_live_order_enabled,
        "kiwoom_use_mock": settings.kiwoom_use_mock,
        "upbit_use_mock": settings.upbit_use_mock,
        "telegram_mode": telegram_mode,
    }

    if telegram_mode == "live":
        return SafetyGateResult(
            allowed=False,
            code="TELEGRAM_LIVE_FORBIDDEN",
            message="Operation rehearsal refuses --telegram=live",
            detail=detail,
        )

    # 실거래 주문 가능 조합 차단
    if settings.global_live_order_enabled and (
        settings.kiwoom_live_order_enabled or settings.upbit_live_order_enabled
    ):
        # mock 없이 live on 이면 실주문 위험
        kiwoom_live_real = (
            settings.kiwoom_live_order_enabled and not settings.kiwoom_use_mock
        )
        upbit_live_real = (
            settings.upbit_live_order_enabled and not settings.upbit_use_mock
        )
        if kiwoom_live_real or upbit_live_real:
            return SafetyGateResult(
                allowed=False,
                code="LIVE_ORDER_ENABLED",
                message=(
                    "Refuse rehearsal while real live orders are enabled. "
                    "Set GLOBAL_LIVE_ORDER_ENABLED=false or enable mocks."
                ),
                detail=detail,
            )

    return SafetyGateResult(
        allowed=True,
        code="SAFE",
        message="Rehearsal safety gate passed",
        detail=detail,
    )
