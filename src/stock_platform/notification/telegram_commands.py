"""Telegram Bot 운영 명령 핸들러 (STEP 10-4)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import structlog
from sqlalchemy.orm import Session

from stock_platform.notification.events import (
    NotificationEventType,
)
from stock_platform.notification.history import (
    NotificationSettings,
)
from stock_platform.notification.publisher import (
    notification_publisher,
)
from stock_platform.notification.telegram_approval_service import (
    ACTION_EXECUTORS,
    TelegramApprovalService,
)
from stock_platform.notification.telegram_status import (
    TelegramOpsStatusService,
)


logger = structlog.get_logger(__name__)

# 승인 없이 실행 금지
DANGEROUS_COMMANDS: dict[str, str] = {
    "/kill": "kill_switch_activate",
    "/resume": "kill_switch_deactivate",
    "/pause_scheduler": "scheduler_pause",
    "/start_scheduler": "scheduler_start",
}

READ_ONLY_COMMANDS = frozenset(
    {
        "/start",
        "/help",
        "/status",
        "/system",
        "/runtime",
        "/scheduler",
        "/broker",
        "/account",
        "/balance",
        "/positions",
        "/orders",
        "/audit",
        "/recovery",
        "/health",
        "/version",
        "/ping",
        "/providers",
        "/provider_health",
        "/provider",
        "/provider_config",
        "/ai_prompts",
        "/ai_policies",
        "/ai_schemas",
        "/ai_executions",
        "/ai_costs",
        "/ai_news",
        "/ai_disclosures",
        "/ai_charts",
        "/ai_markets",
        "/ai_reviews",
        "/ai_benchmarks",
        "/ai_candidate_assessments",
        "/ai_consensus",
        "/ai_candidate_queue",
        "/ai_candidate_promotions",
        "/ai_candidate_lifecycle",
    }
)

KNOWN_COMMANDS = READ_ONLY_COMMANDS | set(DANGEROUS_COMMANDS.keys()) | {
    "/confirm",
}


@dataclass(frozen=True, slots=True)
class TelegramCommandResult:
    ok: bool
    reply_text: str
    command: str
    authorized: bool
    detail: dict[str, Any]


class TelegramCommandHandler:
    """슬래시 명령을 처리한다. TelegramSender 직접 호출 없음."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._status = TelegramOpsStatusService(session)
        self._approval = TelegramApprovalService()

    async def handle(
        self,
        *,
        chat_id: str,
        text: str,
        username: str | None = None,
    ) -> TelegramCommandResult:
        command, args = parse_telegram_input(text)
        actor = f"TELEGRAM:{chat_id}"
        if username:
            actor = f"TELEGRAM:{username}:{chat_id}"

        self._audit(
            event_type="TELEGRAM_RECEIVE",
            actor=actor,
            detail={"chat_id": chat_id, "text": text[:200]},
        )

        if command is None:
            result = TelegramCommandResult(
                ok=False,
                reply_text="알 수 없는 명령입니다. /help",
                command="",
                authorized=True,
                detail={},
            )
            self._audit_command(actor, result)
            return result

        if not self._is_allowed_chat(chat_id):
            result = TelegramCommandResult(
                ok=False,
                reply_text="권한이 없습니다.",
                command=command,
                authorized=False,
                detail={"chat_id": chat_id},
            )
            self._audit(
                event_type="TELEGRAM_PERMISSION_DENIED",
                actor=actor,
                detail={
                    "command": command,
                    "chat_id": chat_id,
                },
            )
            self._audit_command(actor, result)
            return result

        try:
            if command == "__confirm_yes__":
                reply = await self._handle_confirmation(
                    chat_id=chat_id,
                    actor=actor,
                )
                command_label = "/confirm_yes"
            elif command == "/confirm":
                if not args:
                    reply = "Token 필요: /confirm &lt;token&gt;"
                else:
                    reply = await self._handle_confirmation(
                        chat_id=chat_id,
                        actor=actor,
                        token=args[0],
                    )
                command_label = "/confirm"
            elif command in DANGEROUS_COMMANDS:
                reply = await self._request_approval(
                    chat_id=chat_id,
                    actor=actor,
                    command=command,
                    args=args,
                )
                command_label = command
            elif command == "/provider":
                name = args[0] if args else ""
                reply = self._status.build_provider_detail_text(name)
                command_label = command
            elif command == "/provider_config":
                name = args[0] if args else ""
                reply = self._status.build_provider_config_text(name)
                command_label = command
            else:
                reply = await self._dispatch_command(
                    command=command,
                    actor=actor,
                )
                command_label = command

            result = TelegramCommandResult(
                ok=True,
                reply_text=reply,
                command=command_label,
                authorized=True,
                detail={},
            )
        except Exception as exc:
            logger.exception(
                "telegram_command_failed",
                command=command,
                error=str(exc),
            )
            result = TelegramCommandResult(
                ok=False,
                reply_text=f"명령 실패: {exc}",
                command=command,
                authorized=True,
                detail={"error": str(exc)},
            )

        self._audit_command(actor, result)
        return result

    async def _dispatch_command(
        self,
        *,
        command: str,
        actor: str,
    ) -> str:
        if command == "/start":
            return self._status.build_start_text()
        if command == "/help":
            return self._status.build_help_text()
        if command == "/status":
            return await self._status.build_status_text()
        if command == "/system":
            return self._status.build_system_text()
        if command == "/runtime":
            return self._status.build_runtime_text()
        if command == "/scheduler":
            return self._status.build_scheduler_text()
        if command == "/broker":
            return self._status.build_broker_text()
        if command == "/account":
            return self._status.build_account_text()
        if command == "/balance":
            return self._status.build_balance_text()
        if command == "/health":
            return await self._status.build_health_text()
        if command == "/orders":
            return self._status.build_orders_text()
        if command == "/positions":
            return self._status.build_positions_text()
        if command == "/audit":
            return self._status.build_audit_text()
        if command == "/recovery":
            return self._status.build_recovery_text()
        if command == "/version":
            return self._status.build_version_text()
        if command == "/ping":
            return self._status.build_ping_text()
        if command == "/providers":
            return self._status.build_providers_text()
        if command == "/provider_health":
            return await self._status.build_provider_health_text()
        if command == "/ai_prompts":
            return self._status.build_ai_prompt_meta_text("prompts")
        if command == "/ai_policies":
            return self._status.build_ai_prompt_meta_text("policies")
        if command == "/ai_schemas":
            return self._status.build_ai_prompt_meta_text("schemas")
        if command == "/ai_executions":
            return self._status.build_ai_executions_text()
        if command == "/ai_costs":
            return self._status.build_ai_costs_text()
        if command == "/ai_news":
            return self._status.build_ai_news_text()
        if command == "/ai_disclosures":
            return self._status.build_ai_disclosures_text()
        if command == "/ai_charts":
            return self._status.build_ai_charts_text()
        if command == "/ai_markets":
            return self._status.build_ai_markets_text()
        if command == "/ai_reviews":
            return self._status.build_ai_reviews_text()
        if command == "/ai_benchmarks":
            return self._status.build_ai_benchmarks_text()
        if command == "/ai_candidate_assessments":
            return self._status.build_ai_candidate_assessments_text()
        if command == "/ai_consensus":
            return self._status.build_ai_consensus_text()
        if command == "/ai_candidate_queue":
            return self._status.build_ai_candidate_queue_text()
        if command == "/ai_candidate_promotions":
            return self._status.build_ai_candidate_promotions_text()
        if command == "/ai_candidate_lifecycle":
            return self._status.build_ai_candidate_lifecycle_text()
        return "지원하지 않는 명령입니다. /help"

    async def _request_approval(
        self,
        *,
        chat_id: str,
        actor: str,
        command: str,
        args: list[str],
    ) -> str:
        action = DANGEROUS_COMMANDS[command]
        params: dict[str, Any] = {}
        if action == "scheduler_start":
            if not args:
                return "UBA ID 필요: /start_scheduler &lt;uba_id&gt;"
            try:
                params["user_broker_account_id"] = int(args[0])
            except ValueError:
                return "UBA ID는 숫자여야 합니다."

        pending = self._approval.request(
            chat_id=chat_id,
            actor=actor,
            action=action,
            params=params,
        )
        self._audit(
            event_type="TELEGRAM_APPROVAL_REQUESTED",
            actor=actor,
            detail={
                "action": action,
                "token": pending.token,
                "params": params,
            },
        )
        return self._approval.format_request_message(pending)

    async def _handle_confirmation(
        self,
        *,
        chat_id: str,
        actor: str,
        token: str | None = None,
    ) -> str:
        if token:
            pending = self._approval.confirm(
                chat_id=chat_id,
                token=token,
            )
        else:
            pending = self._approval.confirm_yes(chat_id=chat_id)

        if pending is None:
            return "승인 대기 없음, Token 불일치, 또는 만료되었습니다."

        executor = ACTION_EXECUTORS.get(pending.action)
        if executor is None:
            return f"지원하지 않는 작업: {pending.action}"

        self._audit(
            event_type="TELEGRAM_APPROVAL_CONFIRMED",
            actor=actor,
            detail={
                "action": pending.action,
                "token": pending.token,
                "params": pending.params,
            },
        )

        reply = await executor(self._session, pending)

        self._audit(
            event_type="TELEGRAM_ACTION_EXECUTED",
            actor=actor,
            detail={
                "action": pending.action,
                "token": pending.token,
            },
        )

        if pending.action in {
            "kill_switch_activate",
            "kill_switch_deactivate",
        }:
            title = (
                "Kill Switch Activated"
                if pending.action == "kill_switch_activate"
                else "Kill Switch Deactivated"
            )
            await notification_publisher.publish_async(
                event_type=NotificationEventType.KILL_SWITCH,
                title=title,
                message=f"Telegram approved by {actor}",
                detail={"action": pending.action},
            )
        elif pending.action == "scheduler_pause":
            await notification_publisher.publish_async(
                event_type=NotificationEventType.SCHEDULER_PAUSED,
                title="Scheduler Paused",
                message=f"Telegram approved by {actor}",
                detail={"action": pending.action},
            )
        elif pending.action == "scheduler_start":
            await notification_publisher.publish_async(
                event_type=NotificationEventType.SCHEDULER_STARTED,
                title="Scheduler Started",
                message=f"Telegram approved by {actor}",
                detail={"action": pending.action},
            )

        return reply

    @staticmethod
    def _is_allowed_chat(chat_id: str) -> bool:
        settings = NotificationSettings.from_env()
        allowed = set(settings.allowed_chat_ids)
        if not allowed:
            # chat_id 미설정 시 운영 명령 거부 (안전)
            return False
        return str(chat_id).strip() in allowed

    def _audit_command(
        self,
        actor: str,
        result: TelegramCommandResult,
    ) -> None:
        self._audit(
            event_type="TELEGRAM_COMMAND",
            actor=actor,
            detail={
                "command": result.command,
                "ok": result.ok,
                "authorized": result.authorized,
                **result.detail,
            },
        )

    def _audit(
        self,
        *,
        event_type: str,
        actor: str,
        detail: dict[str, Any],
    ) -> None:
        try:
            from stock_platform.api.deps_admin import (
                AuditLogService,
            )

            AuditLogService(self._session).record(
                event_type=event_type,
                actor=actor,
                detail=detail,
            )
            self._session.commit()
        except Exception as exc:
            self._session.rollback()
            logger.warning(
                "telegram_audit_failed",
                error=str(exc),
            )


def parse_telegram_input(text: str) -> tuple[str | None, list[str]]:
    """명령·인자·YES 확인 파싱."""

    raw = (text or "").strip()
    if not raw:
        return None, []
    upper = raw.upper()
    if upper in {"YES", "Y", "CONFIRM"}:
        return "__confirm_yes__", []

    parts = raw.split()
    head = parts[0]
    if head.lower().startswith("/confirm"):
        command = head.split("@", 1)[0].lower()
        return command, parts[1:]

    if not head.startswith("/"):
        return None, []

    command = head.split("@", 1)[0].lower()
    if command not in KNOWN_COMMANDS:
        return None, []
    return command, parts[1:]


def _extract_command(text: str) -> str | None:
    """하위 호환 — 슬래시 명령만 반환."""

    command, _ = parse_telegram_input(text)
    if command in {None, "__confirm_yes__"}:
        return None
    return command
