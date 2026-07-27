"""STEP 10-4 — Telegram 위험 작업 2단계 승인 (60초 TTL)."""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

# chat_id → pending approval (1건)
_PENDING: dict[str, "PendingTelegramApproval"] = {}
_USED_TOKENS: dict[str, float] = {}
DEFAULT_TTL_SECONDS = 60


@dataclass(slots=True)
class PendingTelegramApproval:
    action: str
    chat_id: str
    actor: str
    token: str
    created_at: float
    expires_at: float
    params: dict[str, Any] = field(default_factory=dict)

    @property
    def expired(self) -> bool:
        return time.monotonic() >= self.expires_at


class TelegramApprovalService:
    """위험 작업: 요청 → YES/confirm → 실행. 직접 실행 금지."""

    def __init__(self, *, ttl_seconds: int = DEFAULT_TTL_SECONDS) -> None:
        self._ttl = int(ttl_seconds)

    def request(
        self,
        *,
        chat_id: str,
        actor: str,
        action: str,
        params: dict[str, Any] | None = None,
    ) -> PendingTelegramApproval:
        token = secrets.token_hex(4)
        now = time.monotonic()
        pending = PendingTelegramApproval(
            action=action,
            chat_id=str(chat_id),
            actor=actor,
            token=token,
            created_at=now,
            expires_at=now + self._ttl,
            params=dict(params or {}),
        )
        _PENDING[str(chat_id)] = pending
        return pending

    def get_pending(self, chat_id: str) -> PendingTelegramApproval | None:
        pending = _PENDING.get(str(chat_id))
        if pending is None:
            return None
        if pending.expired:
            _PENDING.pop(str(chat_id), None)
            return None
        return pending

    def confirm(
        self,
        *,
        chat_id: str,
        token: str,
    ) -> PendingTelegramApproval | None:
        pending = self.get_pending(chat_id)
        if pending is None:
            return None
        if pending.token != token.strip().lower():
            return None
        replay_key = f"{chat_id}:{token}"
        if replay_key in _USED_TOKENS:
            return None
        _USED_TOKENS[replay_key] = time.monotonic()
        _PENDING.pop(str(chat_id), None)
        return pending

    def confirm_yes(self, *, chat_id: str) -> PendingTelegramApproval | None:
        pending = self.get_pending(chat_id)
        if pending is None:
            return None
        return self.confirm(chat_id=chat_id, token=pending.token)

    def format_request_message(self, pending: PendingTelegramApproval) -> str:
        return "\n".join(
            [
                "<b>⚠️ 승인 필요</b>",
                f"작업: <code>{pending.action}</code>",
                f"Token: <code>{pending.token}</code>",
                f"유효: {self._ttl}초",
                "",
                "실행하려면 아래 중 하나를 보내세요:",
                "• <code>YES</code>",
                f"• <code>/confirm {pending.token}</code>",
                "",
                "취소: 다른 명령 입력 또는 대기 만료",
            ]
        )


# 액션 실행기 — session 주입 후 호출
ActionExecutor = Callable[
    [Any, PendingTelegramApproval],
    Awaitable[str],
]


async def execute_kill_activate(
    session: Any, pending: PendingTelegramApproval
) -> str:
    from stock_platform.risk_engine.kill_switch_service import KillSwitchService

    state = KillSwitchService(session).activate(
        actor=pending.actor,
        reason="Telegram approved kill",
    )
    session.commit()
    return f"<b>🛑 Kill Switch ACTIVE</b>\nstatus={state.status.value}"


async def execute_kill_deactivate(
    session: Any, pending: PendingTelegramApproval
) -> str:
    from stock_platform.risk_engine.kill_switch_service import KillSwitchService

    state = KillSwitchService(session).deactivate(
        actor=pending.actor,
        reason="Telegram approved resume",
    )
    session.commit()
    return f"<b>✅ Kill Switch OFF</b>\nstatus={state.status.value}"


async def execute_scheduler_pause(
    session: Any, pending: PendingTelegramApproval
) -> str:
    from stock_platform.trading.trading_scheduler_control_service import (
        TradingSchedulerControlService,
    )

    corr = f"tg-{pending.token}"
    result = TradingSchedulerControlService(session).pause(
        actor=pending.actor,
        reason="Telegram approved pause",
        correlation_id=corr,
        require_correlation_id=True,
    )
    session.commit()
    return (
        f"<b>⏸ Scheduler PAUSED</b>\n"
        f"actual={result.get('actual_state')}"
    )


async def execute_scheduler_start(
    session: Any, pending: PendingTelegramApproval
) -> str:
    from stock_platform.trading.trading_scheduler_control_service import (
        TradingSchedulerControlError,
        TradingSchedulerControlService,
    )

    uba_id = int(pending.params.get("user_broker_account_id") or 0)
    if uba_id <= 0:
        return "UBA ID 필요: /start_scheduler &lt;uba_id&gt;"
    corr = f"tg-{pending.token}"
    svc = TradingSchedulerControlService(session)
    try:
        result = svc.start(
            actor=pending.actor,
            reason="Telegram approved start",
            correlation_id=corr,
            user_broker_account_id=uba_id,
            enforce_gates=True,
        )
        session.commit()
    except TradingSchedulerControlError as exc:
        session.rollback()
        return f"<b>Scheduler start blocked</b>\n{exc.code}: {exc.message}"
    return (
        f"<b>▶️ Scheduler RUNNING</b>\n"
        f"actual={result.get('actual_state')}"
    )


ACTION_EXECUTORS: dict[str, ActionExecutor] = {
    "kill_switch_activate": execute_kill_activate,
    "kill_switch_deactivate": execute_kill_deactivate,
    "scheduler_pause": execute_scheduler_pause,
    "scheduler_start": execute_scheduler_start,
}


def clear_telegram_approval_state_for_tests() -> None:
    _PENDING.clear()
    _USED_TOKENS.clear()
