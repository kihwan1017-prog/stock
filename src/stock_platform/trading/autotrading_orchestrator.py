"""Canonical Autotrading START/STOP orchestrator (UBA-scoped).

기존 fail-closed 서비스만 재사용한다.
- UPBIT: unattended/gates + 24x7 Worker/Exit/Runtime + Execution Runner
- KIWOOM: preflight shell (주문·LIVE 자동 ON 금지)

AUTO LIVE/ARM 직접 토글 금지. LIVE/ARM은:
1) 이미 ON 이거나
2) reauthorize_unattended=True 로 기존 reauthorize 경로만 허용.
"""

from __future__ import annotations

import asyncio
import secrets
import threading
from dataclasses import dataclass, field
from typing import Any

import structlog
from sqlalchemy.orm import Session

from stock_platform.trading.account_models import UserBrokerAccount
from stock_platform.trading.autotrading_master_gate import (
    evaluate_uba_autotrading_ready,
)
from stock_platform.trading.live_unattended_authorization_service import (
    LiveUnattendedAuthorizationService,
    LiveUnattendedError,
)
from stock_platform.trading.upbit_24x7_control import (
    CONFIRM_START_EXIT_MONITOR,
    CONFIRM_START_RUNTIME,
    CONFIRM_START_WORKER,
    CONFIRM_STOP_RUNTIME,
    Upbit24x7ControlError,
    start_exit_monitor,
    start_live_outbox_worker,
    start_upbit_strategy_runtime,
    stop_upbit_strategy_runtime,
)
from stock_platform.trading.upbit_unattended_stack_restore import (
    evaluate_stack_restore_gates,
    restore_upbit_trading_stack,
)

logger = structlog.get_logger(__name__)

CONFIRM_ENABLE_24H = "ENABLE 24H UNATTENDED"

STATUS_READY = "READY"
STATUS_ALREADY_RUNNING = "ALREADY_RUNNING"
STATUS_BLOCKED = "BLOCKED"
STATUS_PARTIAL = "PARTIAL"
STATUS_STOPPED = "STOPPED"

STOP_ENTRY_ONLY = "ENTRY_ONLY"
STOP_FULL = "FULL"

_uba_locks: dict[int, asyncio.Lock] = {}
_uba_locks_guard = threading.Lock()


def _lock_for(uba_id: int) -> asyncio.Lock:
    with _uba_locks_guard:
        lock = _uba_locks.get(uba_id)
        if lock is None:
            lock = asyncio.Lock()
            _uba_locks[uba_id] = lock
        return lock


@dataclass
class StepResult:
    name: str
    status: str  # PASS | FAIL | SKIP | ALREADY
    detail: dict[str, Any] = field(default_factory=dict)
    message_ko: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "detail": self.detail,
            "message_ko": self.message_ko,
        }


def _result(
    *,
    status: str,
    uba_id: int,
    broker: str,
    steps: list[StepResult],
    failed_step: str | None = None,
    reason_code: str | None = None,
    operator_action: str | None = None,
    message_code: str | None = None,
    readiness: dict[str, Any] | None = None,
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "status": status,
        "uba_id": int(uba_id),
        "broker": broker,
        "steps": [s.as_dict() for s in steps],
        "failed_step": failed_step,
        "reason_code": reason_code,
        "operator_action": operator_action,
        "message_code": message_code,
        "readiness": (readiness or {}).get("status") if readiness else None,
        "readiness_detail": readiness,
    }
    if extra:
        payload.update(extra)
    return payload


class AutotradingOrchestrator:
    """Broker-aware UBA orchestrator."""

    def __init__(self, session: Session) -> None:
        self._session = session

    async def status(self, user_broker_account_id: int) -> dict[str, Any]:
        uba_id = int(user_broker_account_id)
        uba = self._session.get(UserBrokerAccount, uba_id)
        broker = (
            str(uba.broker_code or "").upper() if uba is not None else "UNKNOWN"
        )
        ready = evaluate_uba_autotrading_ready(
            self._session, user_broker_account_id=uba_id
        )
        from stock_platform.trading.uba_operational_summary import (
            build_uba_operational_summary,
        )

        ops = build_uba_operational_summary(
            self._session, user_broker_account_id=uba_id
        )
        return {
            "uba_id": uba_id,
            "broker": broker,
            "readiness": ready,
            "ops": ops,
            "orchestrator": {
                "start_path": f"/api/v1/admin/autotrading/uba/{uba_id}/start",
                "stop_path": f"/api/v1/admin/autotrading/uba/{uba_id}/stop",
            },
        }

    async def start(
        self,
        user_broker_account_id: int,
        *,
        actor: str,
        reauthorize_unattended: bool = False,
        strategy_id: int | None = None,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        uba_id = int(user_broker_account_id)
        lock = _lock_for(uba_id)
        if lock.locked():
            return _result(
                status=STATUS_BLOCKED,
                uba_id=uba_id,
                broker="UNKNOWN",
                steps=[
                    StepResult(
                        "single_flight",
                        "FAIL",
                        message_ko="동일 계좌 START가 이미 진행 중입니다.",
                    )
                ],
                failed_step="single_flight",
                reason_code="START_IN_PROGRESS",
                operator_action="WAIT_AND_RETRY",
                message_code="ORCH_START_IN_PROGRESS",
            )
        async with lock:
            return await self._start_locked(
                uba_id,
                actor=actor,
                reauthorize_unattended=reauthorize_unattended,
                strategy_id=strategy_id,
                correlation_id=correlation_id,
            )

    async def stop(
        self,
        user_broker_account_id: int,
        *,
        actor: str,
        mode: str = STOP_ENTRY_ONLY,
        strategy_id: int | None = None,
    ) -> dict[str, Any]:
        uba_id = int(user_broker_account_id)
        lock = _lock_for(uba_id)
        async with lock:
            return await self._stop_locked(
                uba_id,
                actor=actor,
                mode=str(mode or STOP_ENTRY_ONLY).upper(),
                strategy_id=strategy_id,
            )

    async def _start_locked(
        self,
        uba_id: int,
        *,
        actor: str,
        reauthorize_unattended: bool,
        strategy_id: int | None,
        correlation_id: str | None,
    ) -> dict[str, Any]:
        steps: list[StepResult] = []
        uba = self._session.get(UserBrokerAccount, uba_id)
        if uba is None:
            return _result(
                status=STATUS_BLOCKED,
                uba_id=uba_id,
                broker="UNKNOWN",
                steps=[StepResult("load_uba", "FAIL")],
                failed_step="load_uba",
                reason_code="UBA_NOT_FOUND",
            )
        broker = str(uba.broker_code or "").upper()
        steps.append(
            StepResult("load_uba", "PASS", {"broker": broker}, "계좌 로드")
        )

        if broker == "UPBIT":
            return await self._start_upbit(
                uba,
                steps=steps,
                actor=actor,
                reauthorize_unattended=reauthorize_unattended,
                strategy_id=strategy_id,
                correlation_id=correlation_id,
            )
        if broker == "KIWOOM":
            return await self._start_kiwoom(uba, steps=steps, actor=actor)
        return _result(
            status=STATUS_BLOCKED,
            uba_id=uba_id,
            broker=broker,
            steps=steps
            + [StepResult("broker", "FAIL", message_ko="지원하지 않는 브로커")],
            failed_step="broker",
            reason_code="UNSUPPORTED_BROKER",
        )

    async def _start_upbit(
        self,
        uba: UserBrokerAccount,
        *,
        steps: list[StepResult],
        actor: str,
        reauthorize_unattended: bool,
        strategy_id: int | None,
        correlation_id: str | None,
    ) -> dict[str, Any]:
        uba_id = int(uba.user_broker_account_id)
        unattended = LiveUnattendedAuthorizationService(self._session)
        unattended_status = unattended.status_dict(uba_id)
        steps.append(
            StepResult(
                "unattended_status",
                "PASS",
                {
                    "needs_reauthorize": bool(
                        unattended_status.get("needs_reauthorize")
                    ),
                    "status_code": unattended_status.get("status_code"),
                },
            )
        )

        # Idempotent: already ready
        ready_before = evaluate_uba_autotrading_ready(
            self._session, user_broker_account_id=uba_id
        )
        if (
            str(ready_before.get("status") or "") == "READY_FOR_AUTO_TRADING"
            and not bool(unattended_status.get("needs_reauthorize"))
        ):
            steps.append(
                StepResult(
                    "readiness",
                    "ALREADY",
                    message_ko="이미 자동매매 준비 완료",
                )
            )
            return _result(
                status=STATUS_ALREADY_RUNNING,
                uba_id=uba_id,
                broker="UPBIT",
                steps=steps,
                readiness=ready_before,
                message_code="ORCH_ALREADY_RUNNING",
            )

        needs_reauth = bool(unattended_status.get("needs_reauthorize"))
        if needs_reauth:
            if not reauthorize_unattended:
                steps.append(
                    StepResult(
                        "unattended_reauthorize",
                        "FAIL",
                        message_ko="24H 무인운영 재승인이 필요합니다.",
                    )
                )
                return _result(
                    status=STATUS_BLOCKED,
                    uba_id=uba_id,
                    broker="UPBIT",
                    steps=steps,
                    failed_step="unattended_reauthorize",
                    reason_code="UNATTENDED_NEEDS_REAUTHORIZE",
                    operator_action="SET_reauthorize_unattended_true",
                    message_code="ORCH_NEED_24H_REAUTH",
                    readiness=ready_before,
                )
            try:
                reauth = unattended.reauthorize(
                    uba_id,
                    actor=actor,
                    confirmation_text=CONFIRM_ENABLE_24H,
                    reason="canonical_orchestrator_start",
                    horizon_hours=24,
                    correlation_id=correlation_id
                    or f"orch-{secrets.token_hex(6)}",
                    source="ADMIN_ORCHESTRATOR",
                )
                self._session.commit()
                steps.append(
                    StepResult(
                        "unattended_reauthorize",
                        "PASS",
                        {"authorization_id": reauth.get("authorization_id")},
                        "24H 재승인",
                    )
                )
            except LiveUnattendedError as exc:
                self._session.rollback()
                steps.append(
                    StepResult(
                        "unattended_reauthorize",
                        "FAIL",
                        {"code": exc.code, "message": exc.message},
                    )
                )
                return _result(
                    status=STATUS_BLOCKED,
                    uba_id=uba_id,
                    broker="UPBIT",
                    steps=steps,
                    failed_step="unattended_reauthorize",
                    reason_code=exc.code,
                    operator_action="FIX_GATES_THEN_REAUTH",
                    message_code="ORCH_REAUTH_FAILED",
                )

        # Refresh uba after possible reauth
        self._session.refresh(uba)

        enable_gates = unattended.evaluate_enable_gates(uba_id)
        steps.append(
            StepResult(
                "safety_gates",
                "PASS" if enable_gates.get("ok") else "FAIL",
                {
                    "blockers": list(enable_gates.get("blockers") or []),
                    "checks": enable_gates.get("checks"),
                },
                "안전 점검",
            )
        )
        # Runtime/Worker not running is OK — we start them next
        ignored = {
            "RUNTIME_NOT_RUNNING",
            "OUTBOX_WORKER_NOT_RUNNING",
            "EXIT_MONITOR_NOT_RUNNING",
        }
        hard = [
            b
            for b in (enable_gates.get("blockers") or [])
            if b not in ignored
        ]
        if hard:
            return _result(
                status=STATUS_BLOCKED,
                uba_id=uba_id,
                broker="UPBIT",
                steps=steps,
                failed_step="safety_gates",
                reason_code=str(hard[0]),
                operator_action="RESOLVE_BLOCKER",
                message_code="ORCH_SAFETY_BLOCKED",
            )

        # Verify LIVE / ARM / Activation (no auto-toggle)
        live_on = bool(getattr(uba, "live_order_enabled", False))
        arm_on = bool(getattr(uba, "live_armed", False))
        steps.append(
            StepResult(
                "live",
                "PASS" if live_on else "FAIL",
                {"live_on": live_on},
                "LIVE",
            )
        )
        steps.append(
            StepResult(
                "arm",
                "PASS" if arm_on else "FAIL",
                {"arm_on": arm_on},
                "ARM",
            )
        )
        if not live_on or not arm_on:
            return _result(
                status=STATUS_BLOCKED,
                uba_id=uba_id,
                broker="UPBIT",
                steps=steps,
                failed_step="live" if not live_on else "arm",
                reason_code="LIVE_OFF" if not live_on else "ARM_OFF",
                operator_action="ENABLE_LIVE_ARM_ON_ACCOUNTS_OR_REAUTH",
                message_code="ORCH_LIVE_ARM_REQUIRED",
            )

        # Resolve strategy_id from portfolio if needed
        sid = strategy_id
        if sid is None:
            try:
                from stock_platform.operation.upbit_full_market.service import (
                    UpbitFullMarketAssignmentService,
                )

                st = UpbitFullMarketAssignmentService(self._session).status_dict(
                    uba_id
                )
                if st.get("strategy_id") is not None:
                    sid = int(st["strategy_id"])
            except Exception:  # noqa: BLE001
                sid = None
        if sid is None:
            steps.append(StepResult("strategy", "FAIL"))
            return _result(
                status=STATUS_BLOCKED,
                uba_id=uba_id,
                broker="UPBIT",
                steps=steps,
                failed_step="strategy",
                reason_code="STRATEGY_ID_REQUIRED",
                operator_action="PASS_strategy_id_OR_ENABLE_PORTFOLIO",
            )
        steps.append(StepResult("strategy", "PASS", {"strategy_id": sid}))

        # Prefer stack restore (idempotent Worker/Runtime/Exit/Runner)
        stack_gates = evaluate_stack_restore_gates(
            self._session, user_broker_account_id=uba_id
        )
        steps.append(
            StepResult(
                "stack_gates",
                "PASS" if stack_gates.get("ok") else "FAIL",
                {"blockers": stack_gates.get("blockers")},
            )
        )
        if not stack_gates.get("ok"):
            return _result(
                status=STATUS_BLOCKED,
                uba_id=uba_id,
                broker="UPBIT",
                steps=steps,
                failed_step="stack_gates",
                reason_code=str((stack_gates.get("blockers") or ["GATE"])[0]),
                operator_action="FIX_STACK_GATES",
            )

        try:
            restored = await restore_upbit_trading_stack(
                self._session,
                user_broker_account_id=uba_id,
                actor=f"ORCH:{actor}",
            )
        except Exception as exc:  # noqa: BLE001
            steps.append(
                StepResult(
                    "stack_restore",
                    "FAIL",
                    {"error": type(exc).__name__},
                )
            )
            return _result(
                status=STATUS_BLOCKED,
                uba_id=uba_id,
                broker="UPBIT",
                steps=steps,
                failed_step="stack_restore",
                reason_code="STACK_RESTORE_FAILED",
            )

        detail = restored.get("detail") or {}
        steps.append(
            StepResult(
                "worker",
                "PASS"
                if (detail.get("worker") or {}).get("started")
                or (detail.get("worker") or {}).get("reason")
                == "ALREADY_RUNNING"
                else "FAIL",
                detail.get("worker") or {},
                "Worker",
            )
        )
        steps.append(
            StepResult(
                "runtime",
                "PASS"
                if (detail.get("runtime") or {}).get("resumed")
                else "FAIL",
                detail.get("runtime") or {},
                "Runtime",
            )
        )
        # If restore could not resume (never started), try operator START RUNTIME
        rt = detail.get("runtime") or {}
        if not rt.get("resumed") and rt.get("reason") == "NO_PAUSED_RUNTIME":
            try:
                # ensure worker/exit first via confirm APIs
                start_live_outbox_worker(
                    confirmation_text=CONFIRM_START_WORKER
                )
                start_exit_monitor(
                    confirmation_text=CONFIRM_START_EXIT_MONITOR
                )
                started = await start_upbit_strategy_runtime(
                    self._session,
                    user_broker_account_id=uba_id,
                    strategy_id=int(sid),
                    actor=actor,
                    confirmation_text=CONFIRM_START_RUNTIME,
                )
                steps.append(
                    StepResult(
                        "runtime_start",
                        "PASS",
                        started,
                        "Runtime 기동",
                    )
                )
                try:
                    from stock_platform.operation.upbit_full_market.portfolio_entry_signal import (
                        ensure_portfolio_entry_evaluator_for_uba,
                    )

                    steps.append(
                        StepResult(
                            "entry_evaluator",
                            "PASS",
                            ensure_portfolio_entry_evaluator_for_uba(uba_id),
                            "매수 평가기",
                        )
                    )
                except Exception as ctx_exc:  # noqa: BLE001
                    steps.append(
                        StepResult(
                            "entry_evaluator",
                            "FAIL",
                            {"error": type(ctx_exc).__name__},
                        )
                    )
            except Upbit24x7ControlError as exc:
                steps.append(
                    StepResult(
                        "runtime_start",
                        "FAIL",
                        {"code": exc.code, "message": exc.message},
                    )
                )
                return _result(
                    status=STATUS_BLOCKED,
                    uba_id=uba_id,
                    broker="UPBIT",
                    steps=steps,
                    failed_step="runtime_start",
                    reason_code=exc.code,
                    operator_action="CHECK_RUNTIME_GATES",
                    extra={"stack_restore": restored},
                )

        steps.append(
            StepResult(
                "exit_monitor",
                "PASS",
                detail.get("exit") or {},
                "Exit Monitor",
            )
        )
        steps.append(
            StepResult(
                "execution_runner",
                "PASS"
                if (detail.get("execution_runner") or {}).get("started")
                else "FAIL",
                detail.get("execution_runner") or {},
                "Execution Runner",
            )
        )
        if detail.get("portfolio_entry_context") is not None:
            steps.append(
                StepResult(
                    "entry_evaluator",
                    "PASS"
                    if (detail.get("portfolio_entry_context") or {}).get("ok", True)
                    else "FAIL",
                    detail.get("portfolio_entry_context") or {},
                    "매수 평가기",
                )
            )

        ready = evaluate_uba_autotrading_ready(
            self._session, user_broker_account_id=uba_id
        )
        steps.append(
            StepResult(
                "readiness",
                "PASS"
                if ready.get("status") == "READY_FOR_AUTO_TRADING"
                else "FAIL",
                {"status": ready.get("status"), "blockers": ready.get("blockers")},
                "Readiness",
            )
        )
        if ready.get("status") != "READY_FOR_AUTO_TRADING":
            return _result(
                status=STATUS_PARTIAL,
                uba_id=uba_id,
                broker="UPBIT",
                steps=steps,
                failed_step="readiness",
                reason_code=str((ready.get("blockers") or ["NOT_READY"])[0]),
                operator_action="INSPECT_READINESS",
                readiness=ready,
                message_code="ORCH_PARTIAL_NOT_READY",
                extra={"stack_restore": restored},
            )

        logger.info(
            "autotrading_orchestrator_start_ready",
            uba_id=uba_id,
            actor=actor,
            strategy_id=sid,
        )
        return _result(
            status=STATUS_READY,
            uba_id=uba_id,
            broker="UPBIT",
            steps=steps,
            readiness=ready,
            message_code="ORCH_READY",
            extra={"stack_restore": restored, "strategy_id": sid},
        )

    async def _start_kiwoom(
        self,
        uba: UserBrokerAccount,
        *,
        steps: list[StepResult],
        actor: str,
    ) -> dict[str, Any]:
        """KIWOOM canonical preflight shell — 주문/LIVE 자동 ON 없음."""

        _ = actor
        uba_id = int(uba.user_broker_account_id)
        ready = evaluate_uba_autotrading_ready(
            self._session, user_broker_account_id=uba_id
        )
        steps.append(
            StepResult(
                "readiness",
                "PASS"
                if not ready.get("blockers")
                else "FAIL",
                {"status": ready.get("status"), "blockers": ready.get("blockers")},
            )
        )

        market: dict[str, Any] = {
            "available": False,
            "gap": "USE_USER_MARKET_CALENDAR_STATUS_API",
            "note": "KIWOOM preflight does not invent calendar SoT",
        }
        phase = ""
        is_td = None
        steps.append(
            StepResult(
                "krx_calendar",
                "PASS",
                market,
                "KRX 장 상태(조회 gap 허용)",
            )
        )

        # Order limit V2 READ-ONLY peek (설정 변경 금지)
        limit_info: dict[str, Any] = {"available": False}
        try:
            from stock_platform.risk_engine.resolved_policy import (
                ResolvedRiskPolicyResolver,
            )

            policy = ResolvedRiskPolicyResolver(self._session).resolve(
                user_id=None,
                user_broker_account_id=uba_id,
            )
            limit_info = {
                "available": True,
                "daily_submit_limit": getattr(
                    policy, "daily_submit_limit", None
                ),
                "daily_filled_entry_limit": getattr(
                    policy, "daily_filled_entry_limit", None
                ),
                "note": "read_only_no_mutation",
            }
        except Exception:  # noqa: BLE001
            limit_info = {"available": False, "gap": "ORDER_LIMIT_READ"}
        steps.append(StepResult("order_limit_v2", "PASS", limit_info))

        if is_td is False or "HOLIDAY" in phase.upper():
            return _result(
                status=STATUS_BLOCKED,
                uba_id=uba_id,
                broker="KIWOOM",
                steps=steps,
                failed_step="krx_calendar",
                reason_code="BLOCKED_MARKET_CLOSED",
                operator_action="WAIT_NEXT_TRADING_DAY",
                message_code="ORCH_KRX_CLOSED",
                readiness=ready,
            )

        if ready.get("status") == "READY_FOR_AUTO_TRADING":
            return _result(
                status=STATUS_READY,
                uba_id=uba_id,
                broker="KIWOOM",
                steps=steps,
                readiness=ready,
                message_code="ORCH_KIWOOM_READY",
            )

        # Shell: do not auto LIVE/ARM/Runtime
        return _result(
            status=STATUS_PARTIAL,
            uba_id=uba_id,
            broker="KIWOOM",
            steps=steps
            + [
                StepResult(
                    "operator_actions",
                    "SKIP",
                    message_ko="LIVE/ARM/Runtime은 계좌·Runtime 화면에서 기존 Gate로 기동하세요.",
                )
            ],
            failed_step="readiness",
            reason_code=str((ready.get("blockers") or ["NOT_READY"])[0]),
            operator_action="COMPLETE_KIWOOM_GATES_MANUALLY",
            message_code="ORCH_KIWOOM_PREFLIGHT",
            readiness=ready,
            extra={"market": market},
        )

    async def _stop_locked(
        self,
        uba_id: int,
        *,
        actor: str,
        mode: str,
        strategy_id: int | None,
    ) -> dict[str, Any]:
        steps: list[StepResult] = []
        uba = self._session.get(UserBrokerAccount, uba_id)
        if uba is None:
            return _result(
                status=STATUS_BLOCKED,
                uba_id=uba_id,
                broker="UNKNOWN",
                steps=[StepResult("load_uba", "FAIL")],
                failed_step="load_uba",
                reason_code="UBA_NOT_FOUND",
            )
        broker = str(uba.broker_code or "").upper()
        if broker != "UPBIT":
            return _result(
                status=STATUS_BLOCKED,
                uba_id=uba_id,
                broker=broker,
                steps=[
                    StepResult(
                        "broker",
                        "FAIL",
                        message_ko="ENTRY_ONLY/FULL STOP은 UPBIT canonical만",
                    )
                ],
                failed_step="broker",
                reason_code="STOP_UPBIT_ONLY",
            )

        sid = strategy_id
        if sid is None:
            try:
                from stock_platform.operation.upbit_full_market.service import (
                    UpbitFullMarketAssignmentService,
                )

                st = UpbitFullMarketAssignmentService(self._session).status_dict(
                    uba_id
                )
                if st.get("strategy_id") is not None:
                    sid = int(st["strategy_id"])
            except Exception:  # noqa: BLE001
                sid = None

        # ENTRY_ONLY: stop runtime (+ runner), keep Exit/Worker/LIVE/ARM
        if mode == STOP_ENTRY_ONLY:
            if sid is not None:
                try:
                    stopped = await stop_upbit_strategy_runtime(
                        self._session,
                        user_broker_account_id=uba_id,
                        strategy_id=int(sid),
                        confirmation_text=CONFIRM_STOP_RUNTIME,
                    )
                    steps.append(
                        StepResult(
                            "runtime_stop",
                            "PASS",
                            stopped,
                            "신규 진입 Runtime 중지",
                        )
                    )
                except Upbit24x7ControlError as exc:
                    steps.append(
                        StepResult(
                            "runtime_stop",
                            "FAIL",
                            {"code": exc.code, "message": exc.message},
                        )
                    )
                    return _result(
                        status=STATUS_BLOCKED,
                        uba_id=uba_id,
                        broker=broker,
                        steps=steps,
                        failed_step="runtime_stop",
                        reason_code=exc.code,
                    )
            else:
                steps.append(
                    StepResult(
                        "runtime_stop",
                        "SKIP",
                        message_ko="strategy_id 없음 — Runtime stop 생략",
                    )
                )

            try:
                from stock_platform.realtime.runtime import (
                    realtime_execution_runner_manager,
                )

                existing = realtime_execution_runner_manager.get(uba_id, "UPBIT")
                if existing is not None and bool(
                    (existing.status() or {}).get("running")
                ):
                    await realtime_execution_runner_manager.stop_scope(
                        uba_id, "UPBIT"
                    )
                    steps.append(
                        StepResult(
                            "execution_runner_stop",
                            "PASS",
                            message_ko="Execution Runner 중지",
                        )
                    )
                else:
                    steps.append(
                        StepResult(
                            "execution_runner_stop",
                            "ALREADY",
                            message_ko="Runner 이미 중지",
                        )
                    )
            except Exception as exc:  # noqa: BLE001
                steps.append(
                    StepResult(
                        "execution_runner_stop",
                        "FAIL",
                        {"error": type(exc).__name__},
                    )
                )

            steps.append(
                StepResult(
                    "protective_keep",
                    "PASS",
                    {
                        "exit_monitor": "KEEP",
                        "outbox_worker": "KEEP",
                        "live": "KEEP",
                        "arm": "KEEP",
                        "unattended": "KEEP",
                    },
                    "기존 포지션 보호(Exit)·LIVE/ARM 유지",
                )
            )
            logger.info(
                "autotrading_orchestrator_stop_entry_only",
                uba_id=uba_id,
                actor=actor,
            )
            return _result(
                status=STATUS_STOPPED,
                uba_id=uba_id,
                broker=broker,
                steps=steps,
                message_code="ORCH_STOP_ENTRY_ONLY",
                extra={"mode": STOP_ENTRY_ONLY},
            )

        # FULL — strong path; still no Kill Switch confusion
        if mode == STOP_FULL:
            # Check open AUTO slots
            open_positions = 0
            try:
                from stock_platform.operation.upbit_full_market.portfolio_service import (
                    UpbitPortfolioService,
                )

                slots = UpbitPortfolioService(self._session).list_slots(uba_id)
                open_positions = sum(
                    1
                    for s in slots
                    if str(s.get("status") or "").upper()
                    in {"OPEN", "EXIT_PENDING"}
                )
            except Exception:  # noqa: BLE001
                open_positions = -1
            steps.append(
                StepResult(
                    "open_auto_positions",
                    "PASS",
                    {"count": open_positions},
                )
            )
            if open_positions and open_positions > 0:
                return _result(
                    status=STATUS_BLOCKED,
                    uba_id=uba_id,
                    broker=broker,
                    steps=steps,
                    failed_step="open_auto_positions",
                    reason_code="OPEN_AUTO_POSITIONS_PRESENT",
                    operator_action="EXIT_OR_USE_ENTRY_ONLY",
                    message_code="ORCH_FULL_STOP_BLOCKED_OPEN",
                    extra={"mode": STOP_FULL},
                )

            # Runtime → Exit → Worker (confirm phrases); LIVE/ARM not auto-off here
            if sid is not None:
                try:
                    await stop_upbit_strategy_runtime(
                        self._session,
                        user_broker_account_id=uba_id,
                        strategy_id=int(sid),
                        confirmation_text=CONFIRM_STOP_RUNTIME,
                    )
                    steps.append(StepResult("runtime_stop", "PASS"))
                except Upbit24x7ControlError as exc:
                    steps.append(
                        StepResult(
                            "runtime_stop",
                            "FAIL",
                            {"code": exc.code},
                        )
                    )
                    return _result(
                        status=STATUS_BLOCKED,
                        uba_id=uba_id,
                        broker=broker,
                        steps=steps,
                        failed_step="runtime_stop",
                        reason_code=exc.code,
                    )

            from stock_platform.trading.upbit_24x7_control import (
                CONFIRM_STOP_EXIT_MONITOR,
                CONFIRM_STOP_WORKER,
                stop_exit_monitor,
                stop_live_outbox_worker,
            )

            try:
                await stop_exit_monitor(
                    confirmation_text=CONFIRM_STOP_EXIT_MONITOR
                )
                steps.append(StepResult("exit_stop", "PASS"))
            except Upbit24x7ControlError as exc:
                steps.append(
                    StepResult("exit_stop", "FAIL", {"code": exc.code})
                )
            try:
                stop_live_outbox_worker(
                    confirmation_text=CONFIRM_STOP_WORKER
                )
                steps.append(StepResult("worker_stop", "PASS"))
            except Upbit24x7ControlError as exc:
                steps.append(
                    StepResult("worker_stop", "FAIL", {"code": exc.code})
                )

            steps.append(
                StepResult(
                    "live_arm_note",
                    "SKIP",
                    message_ko="LIVE/ARM OFF는 계좌 화면에서 별도 수행 (Kill과 혼동 금지)",
                )
            )
            return _result(
                status=STATUS_STOPPED,
                uba_id=uba_id,
                broker=broker,
                steps=steps,
                message_code="ORCH_STOP_FULL_STACK",
                extra={"mode": STOP_FULL},
            )

        return _result(
            status=STATUS_BLOCKED,
            uba_id=uba_id,
            broker=broker,
            steps=steps,
            failed_step="mode",
            reason_code="INVALID_STOP_MODE",
            operator_action="USE_ENTRY_ONLY_OR_FULL",
        )
