"""RealtimeExecutionRunner 안전 자동 기동 (Feature Flag, 기본 OFF)."""

from __future__ import annotations

from typing import Any

import structlog

from stock_platform.common.settings import get_settings
from stock_platform.realtime.execution_models import RealtimeExecutionMode
from stock_platform.realtime.runtime import (
    apply_realtime_paper_account_from_settings,
    realtime_execution_runner,
    realtime_strategy_runner,
)


logger = structlog.get_logger(__name__)


async def maybe_auto_start_runners(
    *,
    source: str,
    allow_live: bool = False,
) -> dict[str, Any]:
    """
    Feature Flag가 켜진 경우에만 Runner를 기동한다.

    - realtime_execution_auto_start_enabled 가 False 면 아무 것도 하지 않음
    - Paper: realtime_paper_auto_start_enabled
    - MOCK: realtime_kiwoom_mock_auto_start_enabled (LIVE HTTP 금지)
    - LIVE: realtime_live_auto_start_enabled AND allow_live
    """

    settings = get_settings()
    master = bool(
        getattr(settings, "realtime_execution_auto_start_enabled", False)
    )
    paper_on = bool(
        getattr(settings, "realtime_paper_auto_start_enabled", False)
    )
    mock_on = bool(
        getattr(settings, "realtime_kiwoom_mock_auto_start_enabled", False)
    )
    live_on = bool(
        getattr(settings, "realtime_live_auto_start_enabled", False)
    )

    result: dict[str, Any] = {
        "source": source,
        "master_enabled": master,
        "paper_enabled": paper_on,
        "mock_enabled": mock_on,
        "live_enabled": live_on,
        "started_execution": False,
        "started_strategy": False,
        "skipped_reason": None,
    }

    if not master:
        result["skipped_reason"] = "MASTER_FLAG_OFF"
        return result

    mode = realtime_execution_runner._config.mode
    if mode == RealtimeExecutionMode.LIVE:
        if not live_on or not allow_live:
            result["skipped_reason"] = "LIVE_AUTO_START_BLOCKED"
            logger.info("realtime_auto_start_blocked_live", source=source)
            return result
    elif mode == RealtimeExecutionMode.MOCK:
        if not mock_on:
            result["skipped_reason"] = "MOCK_AUTO_START_OFF"
            return result
        # LIVE 충돌 방지
        if live_on or bool(
            getattr(settings, "kiwoom_live_order_enabled", False)
        ):
            result["skipped_reason"] = "MOCK_BLOCKED_BY_LIVE_FLAG"
            return result
    else:
        if not paper_on:
            result["skipped_reason"] = "PAPER_AUTO_START_OFF"
            return result

    try:
        apply_realtime_paper_account_from_settings()
        exec_status = await realtime_execution_runner.start()
        strat_status = await realtime_strategy_runner.start()
        result["started_execution"] = True
        result["started_strategy"] = True
        result["execution"] = exec_status
        result["strategy"] = strat_status
        logger.info(
            "realtime_auto_start_ok",
            source=source,
            mode=str(mode),
        )
    except Exception as exc:  # noqa: BLE001
        result["skipped_reason"] = f"START_FAILED:{type(exc).__name__}"
        logger.warning(
            "realtime_auto_start_failed",
            source=source,
            error=str(exc),
        )

    return result
