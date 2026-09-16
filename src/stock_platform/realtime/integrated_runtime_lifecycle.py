"""Paper / MOCK / Upbit Shadow Runtime 통합 생명주기.

실주문 Flag는 건드리지 않는다. Shadow/Dry-run만 허용.
중복 start/stop 은 idempotent.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import structlog

from stock_platform.common.settings import get_settings
from stock_platform.database.session import get_session_factory
from stock_platform.realtime.execution_models import (
    RealtimeExecutionConfig,
    RealtimeExecutionMode,
)
from stock_platform.realtime.runtime import (
    apply_realtime_paper_account_from_settings,
    realtime_execution_runner,
    realtime_safety_guard,
    realtime_strategy_runner,
)
from stock_platform.realtime.safety_models import RealtimeOrderSafetyConfig


logger = structlog.get_logger(__name__)


def _kill_switch_blocks() -> tuple[bool, str | None]:
    try:
        from stock_platform.risk_engine.kill_switch_service import (
            KillSwitchService,
        )

        session = get_session_factory()()
        try:
            if KillSwitchService(session).is_active():
                return True, "KILL_SWITCH_ACTIVE"
        finally:
            session.close()
    except Exception as exc:  # noqa: BLE001
        return True, f"KILL_CHECK_FAILED:{type(exc).__name__}"
    return False, None


def apply_realtime_mock_execution_config(
    *,
    paper_account_id: int | None = None,
    user_broker_account_id: int | None = None,
) -> dict[str, Any]:
    """Kiwoom MOCK 실행 모드 적용 (LIVE HTTP 금지)."""

    settings = get_settings()
    if bool(getattr(settings, "kiwoom_live_order_enabled", False)):
        return {"applied": False, "reason": "KIWOOM_LIVE_FLAG_ON"}
    if bool(getattr(settings, "upbit_live_order_enabled", False)):
        return {"applied": False, "reason": "UPBIT_LIVE_FLAG_ON"}

    paper_id = int(
        paper_account_id
        or getattr(settings, "realtime_paper_account_id", 0)
        or 0
    )
    if paper_id <= 0:
        return {"applied": False, "reason": "PAPER_ACCOUNT_MISSING"}

    uba = user_broker_account_id
    if uba is None:
        uba = int(
            getattr(settings, "realtime_live_user_broker_account_id", 0) or 0
        ) or None

    current = realtime_execution_runner._config
    realtime_execution_runner._config = RealtimeExecutionConfig(
        mode=RealtimeExecutionMode.MOCK,
        account_id=paper_id,
        order_amount=current.order_amount,
        auto_fill=True,
        allow_buy=True,
        allow_sell=True,
        user_id=current.user_id,
        user_broker_account_id=int(uba) if uba else None,
    )
    return {
        "applied": True,
        "mode": "MOCK",
        "paper_account_id": paper_id,
        "user_broker_account_id": uba,
    }


def apply_upbit_shadow_execution_config(
    *,
    user_broker_account_id: int | None = None,
    paper_account_id: int | None = None,
) -> dict[str, Any]:
    """Upbit 24/7 Shadow/Dry-run 실행 모드 (실주문 Flag OFF 유지)."""

    settings = get_settings()
    shadow = bool(getattr(settings, "live_shadow_mode_enabled", False))
    dry = bool(getattr(settings, "live_order_dry_run_enabled", False))
    if not shadow and not dry:
        return {"applied": False, "reason": "SHADOW_OR_DRY_RUN_REQUIRED"}
    if bool(getattr(settings, "upbit_live_order_enabled", False)):
        return {"applied": False, "reason": "UPBIT_LIVE_ORDER_FLAG_ON"}
    if bool(getattr(settings, "kiwoom_live_order_enabled", False)):
        return {"applied": False, "reason": "KIWOOM_LIVE_ORDER_FLAG_ON"}

    uba = int(
        user_broker_account_id
        or getattr(settings, "realtime_live_user_broker_account_id", 0)
        or 0
    )
    if uba <= 0:
        return {"applied": False, "reason": "LIVE_UBA_MISSING"}

    paper_id = int(
        paper_account_id
        or getattr(settings, "realtime_paper_account_id", 0)
        or 0
    )
    if paper_id <= 0:
        return {"applied": False, "reason": "PAPER_ACCOUNT_MISSING"}

    unlock = str(
        getattr(settings, "realtime_live_unlock_token", "") or ""
    ).strip() or "UPBIT-SHADOW-OPS"

    current = realtime_execution_runner._config
    realtime_execution_runner._config = RealtimeExecutionConfig(
        mode=RealtimeExecutionMode.LIVE,
        account_id=paper_id,
        order_amount=current.order_amount or Decimal("100000"),
        auto_fill=False,
        allow_buy=True,
        allow_sell=True,
        user_id=current.user_id,
        user_broker_account_id=uba,
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
        enforce_market_hours_for_krx=False,
        live_trading_enabled=True,
        live_unlock_token=unlock,
    )
    return {
        "applied": True,
        "mode": "LIVE_SHADOW",
        "user_broker_account_id": uba,
        "paper_account_id": paper_id,
        "candidate_path": "DRY_RUN" if dry else "SHADOW",
    }


async def maybe_start_upbit_shadow_quotes(
    *,
    symbols: list[str] | None = None,
) -> dict[str, Any]:
    """Upbit 공개 WS 시세 기동 (idempotent, 실주문 없음)."""

    settings = get_settings()
    enabled = bool(
        getattr(settings, "realtime_upbit_shadow_auto_start_enabled", False)
    )
    if not enabled:
        return {"started": False, "reason": "UPBIT_SHADOW_AUTO_START_OFF"}

    syms = [
        s.upper()
        for s in (
            symbols
            or [
                str(
                    getattr(settings, "realtime_upbit_default_symbol", "")
                    or "KRW-BTC"
                )
            ]
        )
        if s and str(s).strip()
    ]
    if not syms:
        syms = ["KRW-BTC"]

    try:
        from stock_platform.realtime.manager import realtime_manager

        tasks = getattr(realtime_manager, "_tasks", {}) or {}
        if "UPBIT" in tasks:
            return {"started": False, "already_running": True, "symbols": syms}
        status = await realtime_manager.start_upbit(
            symbols=syms, channels=["ticker"]
        )
        return {"started": True, "status": status}
    except ValueError as exc:
        if "already running" in str(exc).lower():
            return {"started": False, "already_running": True}
        return {"started": False, "error": type(exc).__name__}
    except Exception as exc:  # noqa: BLE001
        return {"started": False, "error": type(exc).__name__}


async def on_market_open() -> dict[str, Any]:
    """MARKET_OPEN — Paper/MOCK Runner + Upbit 24/7 Shadow 시세."""

    from stock_platform.order.paper_unattended_runtime import (
        paper_fill_recovery_scheduler,
        paper_outbox_worker_runtime,
    )
    from stock_platform.realtime.execution_auto_start import (
        maybe_auto_start_runners,
    )
    from stock_platform.realtime.paper_price_feed import paper_price_feed

    result: dict[str, Any] = {"phase": "MARKET_OPEN"}

    blocked, reason = _kill_switch_blocks()
    if blocked:
        result["skipped_reason"] = reason
        result["started"] = False
        return result

    result["paper_worker"] = paper_outbox_worker_runtime.start()
    result["paper_recovery"] = paper_fill_recovery_scheduler.start()
    result["paper_feed"] = paper_price_feed.start()

    settings = get_settings()
    mock_on = bool(
        getattr(settings, "realtime_kiwoom_mock_auto_start_enabled", False)
    )
    paper_on = bool(
        getattr(settings, "realtime_paper_auto_start_enabled", False)
    )
    if mock_on:
        result["mock_config"] = apply_realtime_mock_execution_config()
    elif paper_on:
        apply_realtime_paper_account_from_settings()
        result["paper_account"] = True

    # LIVE Kiwoom는 Flag/Unlock 미충족 시 auto_start 내부에서 차단
    from stock_platform.realtime.live_runtime_control import (
        live_auto_start_allowed,
    )

    live_gate = live_auto_start_allowed(allow_live=True)
    result["live_gate"] = live_gate
    result["auto_start"] = await maybe_auto_start_runners(
        source="MARKET_OPEN",
        allow_live=bool(live_gate.get("allowed")),
    )

    # Upbit 24/7 Shadow quotes (KRX open과 독립)
    result["upbit_quotes"] = await maybe_start_upbit_shadow_quotes()
    if bool(
        getattr(settings, "realtime_upbit_shadow_auto_start_enabled", False)
    ):
        # Runner가 꺼져 있으면 Shadow Candidate 경로용으로 유지
        shadow_cfg = apply_upbit_shadow_execution_config()
        result["upbit_shadow_config"] = shadow_cfg
        if shadow_cfg.get("applied"):
            exec_s = await realtime_execution_runner.start()
            strat_s = await realtime_strategy_runner.start()
            result["upbit_runners"] = {
                "execution": exec_s,
                "strategy": strat_s,
            }

    result["started"] = True
    return result


async def on_market_close() -> dict[str, Any]:
    """MARKET_CLOSE — KRX Runner 정지, Upbit 24/7 유지(플래그 시)."""

    from stock_platform.realtime.paper_price_feed import paper_price_feed
    from stock_platform.realtime.live_runtime_control import (
        revert_realtime_execution_to_paper,
        should_keep_upbit_on_krx_close,
        stop_live_market_feeds,
    )

    settings = get_settings()
    keep_upbit = should_keep_upbit_on_krx_close(settings)

    result: dict[str, Any] = {
        "phase": "MARKET_CLOSE",
        "keep_upbit": keep_upbit,
        "upbit_24x7_policy": "KEEP_IF_FLAG_ELSE_STOP_WITH_KRX",
    }

    await paper_price_feed.shutdown()
    result["paper_feed"] = "stopped"

    # Kiwoom LIVE/MOCK 주문 WS·KRX 피드만 정지 (Upbit 유지 옵션)
    result["feeds"] = await stop_live_market_feeds(keep_upbit=keep_upbit)

    if keep_upbit:
        # LIVE UBA 자동매매 중이면 Runner/Config 보존 (Shadow로 강제 전환 금지)
        live_uba = int(
            getattr(settings, "realtime_live_user_broker_account_id", 0) or 0
        )
        mode = getattr(
            getattr(realtime_execution_runner, "_config", None),
            "mode",
            None,
        )
        if (
            live_uba > 0
            and mode == RealtimeExecutionMode.LIVE
        ):
            result["execution"] = await realtime_execution_runner.start()
            result["strategy"] = await realtime_strategy_runner.start()
            result["runners"] = "kept_live_uba"
            result["upbit_live_preserved"] = True
        else:
            # Upbit Shadow 경로 유지 — Runner 재확인
            shadow_cfg = apply_upbit_shadow_execution_config()
            result["upbit_shadow_config"] = shadow_cfg
            if shadow_cfg.get("applied"):
                result["execution"] = await realtime_execution_runner.start()
                result["strategy"] = await realtime_strategy_runner.start()
                result["upbit_quotes"] = await maybe_start_upbit_shadow_quotes()
            else:
                # Shadow 설정 불가 시 KRX와 함께 정지
                await realtime_execution_runner.stop()
                await realtime_strategy_runner.stop()
                revert_realtime_execution_to_paper()
                result["runners"] = "stopped_shadow_unavailable"
    else:
        await realtime_execution_runner.stop()
        await realtime_strategy_runner.stop()
        if (
            realtime_execution_runner._config.mode
            == RealtimeExecutionMode.LIVE
        ):
            revert_realtime_execution_to_paper()
        result["runners"] = "stopped"

    return result


async def ensure_upbit_runtime_after_startup() -> dict[str, Any]:
    """Startup 이후 Upbit 24/7 Shadow Runtime (Flag ON일 때만)."""

    settings = get_settings()
    if not bool(
        getattr(settings, "realtime_upbit_shadow_auto_start_enabled", False)
    ):
        return {"started": False, "reason": "UPBIT_SHADOW_AUTO_START_OFF"}

    blocked, reason = _kill_switch_blocks()
    if blocked:
        return {"started": False, "reason": reason}

    cfg = apply_upbit_shadow_execution_config()
    if not cfg.get("applied"):
        return {"started": False, "config": cfg}

    exec_s = await realtime_execution_runner.start()
    strat_s = await realtime_strategy_runner.start()
    quotes = await maybe_start_upbit_shadow_quotes()
    return {
        "started": True,
        "config": cfg,
        "execution": exec_s,
        "strategy": strat_s,
        "quotes": quotes,
    }


def lifecycle_monitoring_snapshot() -> dict[str, Any]:
    """Dashboard용 Runtime/Scheduler 최소 상태."""

    settings = get_settings()
    exec_st = realtime_execution_runner.status()
    strat_st = realtime_strategy_runner.status()

    upbit_ws: dict[str, Any] = {"running": False}
    try:
        from stock_platform.realtime.manager import realtime_manager

        clients = getattr(realtime_manager, "_clients", {}) or {}
        obj = clients.get("UPBIT")
        if obj is not None:
            upbit_ws = {"running": True, **obj.status()}
    except Exception as exc:  # noqa: BLE001
        upbit_ws = {"error": type(exc).__name__}

    scheduler: dict[str, Any] = {}
    try:
        from stock_platform.realtime.session_runtime import (
            realtime_trading_scheduler,
        )

        scheduler = {
            "running": bool(
                getattr(realtime_trading_scheduler, "_scheduler", None)
                and realtime_trading_scheduler._scheduler.running
            ),
        }
        # job ids if available
        try:
            jobs = realtime_trading_scheduler._scheduler.get_jobs()
            scheduler["job_ids"] = [j.id for j in jobs]
            scheduler["job_count"] = len(jobs)
        except Exception:  # noqa: BLE001
            pass
    except Exception as exc:  # noqa: BLE001
        scheduler = {"error": type(exc).__name__}

    return {
        "execution": exec_st,
        "strategy": strat_st,
        "flags": {
            "master": bool(
                getattr(
                    settings, "realtime_execution_auto_start_enabled", False
                )
            ),
            "paper": bool(
                getattr(settings, "realtime_paper_auto_start_enabled", False)
            ),
            "mock": bool(
                getattr(
                    settings, "realtime_kiwoom_mock_auto_start_enabled", False
                )
            ),
            "live": bool(
                getattr(settings, "realtime_live_auto_start_enabled", False)
            ),
            "upbit_shadow": bool(
                getattr(
                    settings, "realtime_upbit_shadow_auto_start_enabled", False
                )
            ),
            "shadow_mode": bool(
                getattr(settings, "live_shadow_mode_enabled", False)
            ),
            "dry_run_mode": bool(
                getattr(settings, "live_order_dry_run_enabled", False)
            ),
            "upbit_live_order": bool(
                getattr(settings, "upbit_live_order_enabled", False)
            ),
            "kiwoom_live_order": bool(
                getattr(settings, "kiwoom_live_order_enabled", False)
            ),
        },
        "upbit_ws": upbit_ws,
        "session_scheduler": scheduler,
        "mode": str(realtime_execution_runner._config.mode),
    }
