from __future__ import annotations

import secrets

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from stock_platform.api.deps_admin import require_admin
from stock_platform.realtime.execution_scope import (
    SUPPORTED_LIVE_BROKERS,
)
from stock_platform.realtime.runtime import (
    realtime_execution_runner,
    realtime_execution_runner_manager,
)


router = APIRouter(
    prefix="/api/v1/realtime-execution",
    tags=["Realtime Execution"],
    dependencies=[Depends(require_admin)],
)

LIVE_START_CONFIRMATION = "START LIVE EXECUTION"
MULTI_SCOPE_STOP_REQUIRES_UBA = "MULTI_SCOPE_STOP_REQUIRES_UBA"


class StartRealtimeExecutionBody(BaseModel):
    mode: str | None = Field(default=None, max_length=16)
    user_broker_account_id: int | None = Field(default=None, ge=1)
    confirmation_text: str | None = Field(default=None, max_length=80)


def _parse_start_body(raw: object) -> StartRealtimeExecutionBody:
    if raw is None:
        return StartRealtimeExecutionBody()
    if not isinstance(raw, dict):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="start body must be a JSON object",
        )
    try:
        return StartRealtimeExecutionBody.model_validate(raw)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


def _resolve_live_uba_broker(user_broker_account_id: int) -> str:
    """UBA 존재 + 지원 broker만 허용. UPBIT 전용 강제 없음."""

    from stock_platform.database.session import get_session_factory
    from stock_platform.trading.account_models import UserBrokerAccount

    session = get_session_factory()()
    try:
        uba = session.get(UserBrokerAccount, int(user_broker_account_id))
        if uba is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="LIVE_UBA_NOT_FOUND",
            )
        broker = str(getattr(uba, "broker_code", "") or "").upper()
        if broker not in SUPPORTED_LIVE_BROKERS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="LIVE_UBA_BROKER_NOT_SUPPORTED",
            )
        return broker
    finally:
        session.close()


async def _start_live_for_uba(uba_id: int) -> dict:
    """해당 UBA Runner만 START. 다른 RUNNING Runner는 유지."""

    broker = _resolve_live_uba_broker(uba_id)
    existing = realtime_execution_runner_manager.get(uba_id, broker)
    if existing is not None:
        current = existing.status()
        same_live = (
            bool(current.get("running"))
            and str(current.get("mode") or "").upper() == "LIVE"
            and int(current.get("user_broker_account_id") or 0) == uba_id
        )
        if same_live:
            return {"already_running": True, **current}

    from stock_platform.realtime.live_runtime_control import (
        apply_realtime_live_execution_config,
    )

    applied = apply_realtime_live_execution_config(
        user_broker_account_id=uba_id,
        unlock_token=secrets.token_urlsafe(24),
    )
    if not applied.get("applied"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(applied.get("reason") or "LIVE_CONFIG_BLOCKED"),
        )
    started = await realtime_execution_runner_manager.start_scope(
        uba_id,
        str(applied.get("broker_code") or broker),
    )
    return {
        "started": True,
        "config": {
            "applied": True,
            "mode": applied.get("mode"),
            "user_broker_account_id": applied.get(
                "user_broker_account_id"
            ),
            "broker_code": applied.get("broker_code") or broker,
            "paper_account_id": applied.get("paper_account_id"),
        },
        **started,
    }


@router.post("/{user_broker_account_id}/start")
async def start_realtime_execution_for_uba(
    user_broker_account_id: int,
    request: Request,
):
    raw: object = None
    try:
        content_type = str(request.headers.get("content-type") or "")
        content_length = str(request.headers.get("content-length") or "0")
        if content_length not in {"", "0"} and "json" in content_type.lower():
            raw = await request.json()
    except Exception:
        raw = None
    body = _parse_start_body(raw)
    mode = str(body.mode or "LIVE").strip().upper() or "LIVE"
    if mode != "LIVE":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="SCOPED_START_LIVE_ONLY",
        )
    confirm = str(body.confirmation_text or "").strip().upper()
    if LIVE_START_CONFIRMATION not in confirm:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "confirmation_text must include "
                f"'{LIVE_START_CONFIRMATION}'"
            ),
        )
    try:
        return await _start_live_for_uba(int(user_broker_account_id))
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.post("/{user_broker_account_id}/stop")
async def stop_realtime_execution_for_uba(user_broker_account_id: int):
    broker = _resolve_live_uba_broker(int(user_broker_account_id))
    return await realtime_execution_runner_manager.stop_scope(
        int(user_broker_account_id),
        broker,
    )


@router.get("/{user_broker_account_id}/status")
def get_realtime_execution_status_for_uba(user_broker_account_id: int):
    broker = _resolve_live_uba_broker(int(user_broker_account_id))
    runner = realtime_execution_runner_manager.get(
        int(user_broker_account_id),
        broker,
    )
    if runner is None:
        return {
            "running": False,
            "uba": int(user_broker_account_id),
            "broker": broker,
            "user_broker_account_id": int(user_broker_account_id),
            "broker_code": broker,
        }
    status_body = runner.status()
    return {
        "uba": int(user_broker_account_id),
        "broker": broker,
        **status_body,
    }


@router.post("/start")
async def start_realtime_execution(request: Request):
    raw: object = None
    try:
        content_type = str(request.headers.get("content-type") or "")
        content_length = str(request.headers.get("content-length") or "0")
        if content_length not in {"", "0"} and "json" in content_type.lower():
            raw = await request.json()
    except Exception:
        raw = None
    body = _parse_start_body(raw)
    mode = str(body.mode or "").strip().upper() or None

    try:
        if mode == "LIVE":
            confirm = str(body.confirmation_text or "").strip().upper()
            if LIVE_START_CONFIRMATION not in confirm:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        "confirmation_text must include "
                        f"'{LIVE_START_CONFIRMATION}'"
                    ),
                )
            uba_id = int(body.user_broker_account_id or 0)
            if uba_id <= 0:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="LIVE_UBA_REQUIRED",
                )
            return await _start_live_for_uba(uba_id)

        return await realtime_execution_runner.start()
    except HTTPException:
        raise
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.post("/stop")
async def stop_realtime_execution():
    live_running = realtime_execution_runner_manager.running_live_runners()
    if len(live_running) > 1:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=MULTI_SCOPE_STOP_REQUIRES_UBA,
        )
    await realtime_execution_runner.stop()
    return {"stopped": True}


@router.get("/status")
def get_realtime_execution_status():
    return realtime_execution_runner.status()


@router.get("/history")
def get_realtime_execution_history():
    return realtime_execution_runner.history()
