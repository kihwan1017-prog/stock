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

    # Kill Switch — 자동 기동 Fail Closed
    try:
        from stock_platform.realtime.integrated_runtime_lifecycle import (
            _kill_switch_blocks,
        )

        blocked, kill_reason = _kill_switch_blocks()
        if blocked:
            result["skipped_reason"] = kill_reason
            return result
    except Exception as exc:  # noqa: BLE001
        result["skipped_reason"] = f"KILL_GATE_ERROR:{type(exc).__name__}"
        return result

    mode = realtime_execution_runner._config.mode
    if mode == RealtimeExecutionMode.LIVE or (
        live_on and allow_live and mode != RealtimeExecutionMode.MOCK
    ):
        from stock_platform.realtime.live_runtime_control import (
            apply_realtime_live_execution_config,
            live_auto_start_allowed,
        )

        gate = live_auto_start_allowed(allow_live=allow_live)
        if not gate.get("allowed"):
            # LIVE 불가 시 Paper/MOCK 폴백 가능하면 계속
            if mock_on:
                from stock_platform.realtime.integrated_runtime_lifecycle import (
                    apply_realtime_mock_execution_config,
                )

                applied_mock = apply_realtime_mock_execution_config()
                if not applied_mock.get("applied"):
                    result["skipped_reason"] = (
                        f"LIVE_BLOCKED:{gate.get('reason')};"
                        f"MOCK_BLOCKED:{applied_mock.get('reason')}"
                    )
                    return result
                result["mock_config"] = applied_mock
                mode = RealtimeExecutionMode.MOCK
            elif paper_on:
                result["live_blocked"] = gate.get("reason")
                mode = RealtimeExecutionMode.PAPER
            else:
                result["skipped_reason"] = (
                    f"LIVE_AUTO_START_BLOCKED:{gate.get('reason')}"
                )
                logger.info(
                    "realtime_auto_start_blocked_live",
                    source=source,
                    reason=gate.get("reason"),
                )
                return result
        else:
            applied = apply_realtime_live_execution_config()
            if not applied.get("applied"):
                result["skipped_reason"] = (
                    f"LIVE_CONFIG_BLOCKED:{applied.get('reason')}"
                )
                return result
            result["live_config"] = applied
            mode = RealtimeExecutionMode.LIVE
    elif mock_on or mode == RealtimeExecutionMode.MOCK:
        if not mock_on:
            result["skipped_reason"] = "MOCK_AUTO_START_OFF"
            return result
        if live_on or bool(
            getattr(settings, "kiwoom_live_order_enabled", False)
        ):
            result["skipped_reason"] = "MOCK_BLOCKED_BY_LIVE_FLAG"
            return result
        from stock_platform.realtime.integrated_runtime_lifecycle import (
            apply_realtime_mock_execution_config,
        )

        applied_mock = apply_realtime_mock_execution_config()
        if not applied_mock.get("applied"):
            result["skipped_reason"] = (
                f"MOCK_CONFIG_BLOCKED:{applied_mock.get('reason')}"
            )
            return result
        result["mock_config"] = applied_mock
        mode = RealtimeExecutionMode.MOCK
    else:
        if not paper_on:
            result["skipped_reason"] = "PAPER_AUTO_START_OFF"
            return result
        mode = RealtimeExecutionMode.PAPER
        # 모드가 MOCK/LIVE로 남아 있으면 Paper로 복귀
        if realtime_execution_runner._config.mode != RealtimeExecutionMode.PAPER:
            from stock_platform.realtime.live_runtime_control import (
                revert_realtime_execution_to_paper,
            )

            revert_realtime_execution_to_paper()
            mode = RealtimeExecutionMode.PAPER

    try:
        if mode != RealtimeExecutionMode.LIVE:
            apply_realtime_paper_account_from_settings()
        exec_status = await realtime_execution_runner.start()
        strat_status = await realtime_strategy_runner.start()
        result["started_execution"] = True
        result["started_strategy"] = True
        result["execution"] = exec_status
        result["strategy"] = strat_status
        if mode == RealtimeExecutionMode.LIVE:
            from stock_platform.realtime.live_runtime_control import (
                maybe_start_live_market_feeds,
            )

            result["live_feeds"] = await maybe_start_live_market_feeds()
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
