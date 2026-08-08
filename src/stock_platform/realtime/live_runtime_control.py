"""LIVE Runtime 제어 — Fail Closed (Feature Flag 기본 OFF).

Paper/MOCK 경로를 변경하지 않고, LIVE 모드 전환·시세·주문 WS·
Scheduler 연동만 담당한다.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import structlog

from stock_platform.common.settings import get_settings
from stock_platform.realtime.execution_models import (
    RealtimeExecutionConfig,
    RealtimeExecutionMode,
)
from stock_platform.realtime.runtime import (
    realtime_execution_runner,
    realtime_safety_guard,
)
from stock_platform.realtime.safety_models import RealtimeOrderSafetyConfig


logger = structlog.get_logger(__name__)


def live_order_flags_ready(settings: Any | None = None) -> bool:
    s = settings or get_settings()
    return bool(
        getattr(s, "kiwoom_live_order_enabled", False)
        or getattr(s, "upbit_live_order_enabled", False)
    )


def live_auto_start_allowed(*, allow_live: bool) -> dict[str, Any]:
    """Scheduler/API가 LIVE auto-start를 허용해도 되는지 판정."""

    settings = get_settings()
    master = bool(
        getattr(settings, "realtime_execution_auto_start_enabled", False)
    )
    live_on = bool(
        getattr(settings, "realtime_live_auto_start_enabled", False)
    )
    unlock = str(
        getattr(settings, "realtime_live_unlock_token", "") or ""
    ).strip()
    uba = int(
        getattr(settings, "realtime_live_user_broker_account_id", 0) or 0
    )
    if not allow_live:
        return {"allowed": False, "reason": "ALLOW_LIVE_FALSE"}
    if not master:
        return {"allowed": False, "reason": "MASTER_FLAG_OFF"}
    if not live_on:
        return {"allowed": False, "reason": "LIVE_AUTO_START_OFF"}
    if not live_order_flags_ready(settings):
        return {"allowed": False, "reason": "LIVE_ORDER_FLAG_OFF"}
    if not unlock:
        return {"allowed": False, "reason": "LIVE_UNLOCK_TOKEN_MISSING"}
    if uba <= 0:
        return {"allowed": False, "reason": "LIVE_UBA_MISSING"}
    if bool(getattr(settings, "kiwoom_use_mock", False)) and bool(
        getattr(settings, "kiwoom_live_order_enabled", False)
    ):
        return {"allowed": False, "reason": "KIWOOM_MOCK_LIVE_CONFLICT"}
    return {"allowed": True, "reason": None, "uba_id": uba}


def apply_realtime_live_execution_config(
    *,
    user_broker_account_id: int | None = None,
    paper_account_id: int | None = None,
    order_amount: Decimal | None = None,
) -> dict[str, Any]:
    """Runner/Safety를 LIVE 모드로 전환 (Flag·Unlock·UBA 필수)."""

    settings = get_settings()
    gate = live_auto_start_allowed(allow_live=True)
    if not gate.get("allowed"):
        # 명시 호출에서도 order flag/unlock 없으면 거부
        uba = int(
            user_broker_account_id
            or getattr(settings, "realtime_live_user_broker_account_id", 0)
            or 0
        )
        unlock = str(
            getattr(settings, "realtime_live_unlock_token", "") or ""
        ).strip()
        if not live_order_flags_ready(settings):
            return {"applied": False, "reason": "LIVE_ORDER_FLAG_OFF"}
        if not unlock:
            return {"applied": False, "reason": "LIVE_UNLOCK_TOKEN_MISSING"}
        if uba <= 0:
            return {"applied": False, "reason": "LIVE_UBA_MISSING"}
        if bool(getattr(settings, "kiwoom_use_mock", False)) and bool(
            getattr(settings, "kiwoom_live_order_enabled", False)
        ):
            return {"applied": False, "reason": "KIWOOM_MOCK_LIVE_CONFLICT"}
    else:
        uba = int(user_broker_account_id or gate["uba_id"])
        unlock = str(
            getattr(settings, "realtime_live_unlock_token", "") or ""
        ).strip()

    paper_id = int(
        paper_account_id
        or getattr(settings, "realtime_paper_account_id", 0)
        or 0
    )
    if paper_id <= 0:
        return {"applied": False, "reason": "PAPER_ACCOUNT_MISSING"}

    current = realtime_execution_runner._config
    amount = order_amount if order_amount is not None else current.order_amount
    realtime_execution_runner._config = RealtimeExecutionConfig(
        mode=RealtimeExecutionMode.LIVE,
        account_id=paper_id,
        order_amount=amount,
        auto_fill=False,  # LIVE는 브로커 체결만
        allow_buy=current.allow_buy,
        allow_sell=current.allow_sell,
        user_id=current.user_id,
        user_broker_account_id=int(uba),
    )

    sc = realtime_safety_guard._config
    realtime_safety_guard._config = RealtimeOrderSafetyConfig(
        max_order_amount=sc.max_order_amount,
        max_daily_loss=sc.max_daily_loss,
        max_open_positions=sc.max_open_positions,
        duplicate_order_window_seconds=sc.duplicate_order_window_seconds,
        symbol_cooldown_seconds=sc.symbol_cooldown_seconds,
        max_orders_per_minute=sc.max_orders_per_minute,
        trading_start_time=sc.trading_start_time,
        trading_end_time=sc.trading_end_time,
        enforce_market_hours_for_krx=sc.enforce_market_hours_for_krx,
        live_trading_enabled=True,
        live_unlock_token=unlock,
    )
    logger.info(
        "realtime_live_execution_config_applied",
        uba_id=uba,
        paper_account_id=paper_id,
    )
    return {
        "applied": True,
        "reason": None,
        "mode": "LIVE",
        "user_broker_account_id": uba,
        "paper_account_id": paper_id,
    }


def revert_realtime_execution_to_paper() -> dict[str, Any]:
    """MARKET_CLOSE / Stop 시 PAPER 모드로 복귀 (Fail Closed)."""

    settings = get_settings()
    paper_id = int(getattr(settings, "realtime_paper_account_id", 1) or 1)
    current = realtime_execution_runner._config
    realtime_execution_runner._config = RealtimeExecutionConfig(
        mode=RealtimeExecutionMode.PAPER,
        account_id=paper_id,
        order_amount=current.order_amount,
        auto_fill=True,
        allow_buy=current.allow_buy,
        allow_sell=current.allow_sell,
        user_id=current.user_id,
        user_broker_account_id=None,
    )
    sc = realtime_safety_guard._config
    realtime_safety_guard._config = RealtimeOrderSafetyConfig(
        max_order_amount=sc.max_order_amount,
        max_daily_loss=sc.max_daily_loss,
        max_open_positions=sc.max_open_positions,
        duplicate_order_window_seconds=sc.duplicate_order_window_seconds,
        symbol_cooldown_seconds=sc.symbol_cooldown_seconds,
        max_orders_per_minute=sc.max_orders_per_minute,
        trading_start_time=sc.trading_start_time,
        trading_end_time=sc.trading_end_time,
        enforce_market_hours_for_krx=sc.enforce_market_hours_for_krx,
        live_trading_enabled=False,
        live_unlock_token="",
    )
    return {"mode": "PAPER", "paper_account_id": paper_id}


async def maybe_start_live_market_feeds(
    *,
    symbols: list[str] | None = None,
) -> dict[str, Any]:
    """Upbit WS / Kiwoom Order WS 기동 (Flag ON일 때만)."""

    settings = get_settings()
    result: dict[str, Any] = {
        "upbit_quotes": None,
        "kiwoom_order_ws": None,
    }
    syms = [s.upper() for s in (symbols or []) if s and str(s).strip()]

    if bool(getattr(settings, "upbit_live_order_enabled", False)) and syms:
        try:
            from stock_platform.realtime.manager import realtime_manager

            status = realtime_manager.status()
            upbit_running = False
            clients = status.get("clients") or status.get("tasks") or {}
            if isinstance(clients, dict) and "UPBIT" in clients:
                upbit_running = True
            # status 형태 호환
            if not upbit_running:
                tasks = getattr(realtime_manager, "_tasks", {})
                upbit_running = "UPBIT" in tasks
            if not upbit_running:
                result["upbit_quotes"] = await realtime_manager.start_upbit(
                    symbols=syms
                )
            else:
                result["upbit_quotes"] = {"already_running": True}
        except Exception as exc:  # noqa: BLE001
            result["upbit_quotes"] = {"error": type(exc).__name__}

    if bool(getattr(settings, "kiwoom_live_order_enabled", False)):
        try:
            from stock_platform.broker.kiwoom.ws_manager import (
                kiwoom_order_websocket_manager,
            )

            ws_status = kiwoom_order_websocket_manager.status()
            if not ws_status.get("running"):
                result["kiwoom_order_ws"] = (
                    await kiwoom_order_websocket_manager.start()
                )
            else:
                result["kiwoom_order_ws"] = {"already_running": True}
        except Exception as exc:  # noqa: BLE001
            result["kiwoom_order_ws"] = {"error": type(exc).__name__}

    return result


async def stop_live_market_feeds(
    *,
    keep_upbit: bool = False,
) -> dict[str, Any]:
    """LIVE/시세 WS 정지. keep_upbit=True면 Upbit 공개시세는 유지."""

    result: dict[str, Any] = {"keep_upbit": keep_upbit}
    try:
        from stock_platform.broker.kiwoom.ws_manager import (
            kiwoom_order_websocket_manager,
        )

        await kiwoom_order_websocket_manager.stop()
        result["kiwoom_order_ws"] = "stopped"
    except Exception as exc:  # noqa: BLE001
        result["kiwoom_order_ws"] = type(exc).__name__

    try:
        from stock_platform.realtime.manager import realtime_manager

        if keep_upbit:
            stopped: list[str] = []
            for client_id in list(
                getattr(realtime_manager, "_tasks", {}) or {}
            ):
                if str(client_id).upper() == "UPBIT":
                    continue
                await realtime_manager.stop(str(client_id))
                stopped.append(str(client_id))
            result["market_data"] = {
                "stopped": stopped,
                "kept": ["UPBIT"]
                if "UPBIT"
                in (getattr(realtime_manager, "_tasks", {}) or {})
                else [],
            }
        else:
            await realtime_manager.stop_all()
            result["market_data"] = "stopped"
    except Exception as exc:  # noqa: BLE001
        result["market_data"] = type(exc).__name__
    return result


def should_keep_upbit_on_krx_close(
    settings: Any | None = None,
) -> bool:
    """KRX MARKET_CLOSE에서도 UPBIT 시세/런타임 유지 여부.

    Shadow auto-start 또는 명시적 24/7 keep 플래그. 기본 OFF(Fail Closed).
    """

    cfg = settings if settings is not None else get_settings()
    if bool(getattr(cfg, "realtime_upbit_shadow_auto_start_enabled", False)):
        return True
    return bool(
        getattr(cfg, "realtime_upbit_24x7_keep_on_krx_close", False)
    )


def upbit_market_hours_policy() -> dict[str, Any]:
    """UPBIT는 KRX 세션 Timeline에 묶지 않음."""

    return {
        "broker": "UPBIT",
        "applies_krx_session": False,
        "policy": "24/7_SUBJECT_TO_RECOVERY_KILL_ARM",
        "keep_on_krx_close": should_keep_upbit_on_krx_close(),
        "krx_policy": "SESSION_TIMELINE_UNCHANGED",
    }


async def restart_live_runtime() -> dict[str, Any]:
    """LIVE Runner Stop → Config 재적용 → Start (idempotent)."""

    from stock_platform.realtime.runtime import realtime_strategy_runner

    await realtime_execution_runner.stop()
    await realtime_strategy_runner.stop()
    applied = apply_realtime_live_execution_config()
    if not applied.get("applied"):
        return {"restarted": False, "config": applied}
    exec_s = await realtime_execution_runner.start()
    strat_s = await realtime_strategy_runner.start()
    feeds = await maybe_start_live_market_feeds()
    return {
        "restarted": True,
        "config": applied,
        "execution": exec_s,
        "strategy": strat_s,
        "feeds": feeds,
    }
