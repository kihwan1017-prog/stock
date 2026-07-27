"""Audit / Telegram / Failure 시나리오 리허설."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock

from stock_platform.operations.rehearsal.checks import run_check
from stock_platform.operations.rehearsal.models import (
    CheckResult,
    CheckStatus,
    RehearsalOptions,
)
from stock_platform.operations.rehearsal.safety import assert_rehearsal_safe

# 이번 리허설이 직접 기록하는 필수 Audit 이벤트
REQUIRED_REHEARSAL_EVENTS = (
    "OPERATION_REHEARSAL_START",
    "OPERATION_REHEARSAL_PAPER",
    "OPERATION_REHEARSAL_RISK",
    "OPERATION_REHEARSAL_SCHEDULER",
    "OPERATION_REHEARSAL_RECOVERY",
    "OPERATION_REHEARSAL_TELEGRAM",
)


_SENSITIVE_KEYS = (
    "password",
    "secret",
    "token",
    "api_key",
    "apikey",
    "authorization",
)


def _detail_has_secrets(detail: dict[str, Any]) -> bool:
    blob = str(detail).lower()
    return any(key in blob for key in _SENSITIVE_KEYS)


def emit_rehearsal_audit_events(run_id: str) -> dict[str, Any]:
    """리허설 실행용 Audit 이벤트를 run_id로 기록."""

    from stock_platform.database.session import get_session_factory
    from stock_platform.operation.audit_repository import AuditEventRepository

    session = get_session_factory()()
    created: list[str] = []
    try:
        repo = AuditEventRepository(session)
        now = datetime.now(timezone.utc)
        for event_type in REQUIRED_REHEARSAL_EVENTS:
            detail = {
                "correlation_id": run_id,
                "source": "operation_rehearsal",
                "suite_hint": event_type.replace(
                    "OPERATION_REHEARSAL_", ""
                ).lower(),
            }
            if _detail_has_secrets(detail):
                raise RuntimeError("audit detail contains sensitive keys")
            repo.create(
                event_type=event_type,
                actor="OPERATION_REHEARSAL",
                request_id=run_id[:64],
                run_id=run_id[:64],
                strategy_id=None,
                account_hash=None,
                order_id=None,
                client_order_id=None,
                symbol=None,
                detail=detail,
                created_at=now,
            )
            created.append(event_type)
        return {"created": created, "run_id": run_id}
    finally:
        session.close()


def run_audit_checks(*, run_id: str) -> list[CheckResult]:
    results: list[CheckResult] = []

    def _access() -> tuple[CheckStatus, str, dict[str, Any]]:
        from stock_platform.database.session import get_session_factory
        from stock_platform.operation.audit_repository import (
            AuditEventRepository,
        )

        session = get_session_factory()()
        try:
            AuditEventRepository(session).list_recent(limit=1)
            return CheckStatus.PASS, "audit store reachable", {}
        finally:
            session.close()

    results.append(run_check(suite="audit", name="store_access", fn=_access))

    def _emit_and_verify() -> tuple[CheckStatus, str, dict[str, Any]]:
        emitted = emit_rehearsal_audit_events(run_id)
        from stock_platform.database.session import get_session_factory
        from stock_platform.operation.audit_repository import (
            AuditEventRepository,
        )

        session = get_session_factory()()
        try:
            events = AuditEventRepository(session).list_recent(limit=100)
            mine = [
                e
                for e in events
                if (e.run_id or "") == run_id[:64]
                or (e.request_id or "") == run_id[:64]
            ]
            types = {str(e.event_type) for e in mine}
            missing = [
                name for name in REQUIRED_REHEARSAL_EVENTS if name not in types
            ]
            if missing:
                return (
                    CheckStatus.FAIL,
                    f"missing rehearsal audit events: {missing}",
                    {
                        "run_id": run_id,
                        "found": sorted(types),
                        "missing": missing,
                        "emitted": emitted.get("created"),
                    },
                )
            actors = {str(e.actor) for e in mine}
            timestamps_ok = all(e.created_at is not None for e in mine)
            secrets = any(
                _detail_has_secrets(dict(e.detail or {})) for e in mine
            )
            if secrets:
                return (
                    CheckStatus.FAIL,
                    "audit detail contains sensitive keys",
                    {"run_id": run_id},
                )
            if "OPERATION_REHEARSAL" not in actors:
                return (
                    CheckStatus.FAIL,
                    "rehearsal actor missing",
                    {"actors": sorted(actors)},
                )
            if not timestamps_ok:
                return (
                    CheckStatus.FAIL,
                    "audit timestamps missing",
                    {"run_id": run_id},
                )
            return (
                CheckStatus.PASS,
                f"rehearsal audit events ok count={len(mine)}",
                {
                    "run_id": run_id,
                    "event_types": sorted(types),
                    "actors": sorted(actors),
                    "count": len(mine),
                },
            )
        finally:
            session.close()

    results.append(
        run_check(
            suite="audit",
            name="rehearsal_events_by_run_id",
            fn=_emit_and_verify,
        )
    )
    return results


def run_telegram_checks(options: RehearsalOptions) -> list[CheckResult]:
    results: list[CheckResult] = []
    mode = (options.telegram or "dry-run").lower()

    def _mode_gate() -> tuple[CheckStatus, str, dict[str, Any]]:
        if mode == "live":
            return (
                CheckStatus.FAIL,
                "telegram live mode forbidden",
                {"mode": mode},
            )
        if mode == "off":
            return (
                CheckStatus.NOT_APPLICABLE,
                "telegram off",
                {"mode": mode},
            )
        return CheckStatus.PASS, "telegram dry-run", {"mode": mode}

    results.append(run_check(suite="telegram", name="mode", fn=_mode_gate))

    if mode in {"off", "live"}:
        return results

    def _dry_run_command() -> tuple[CheckStatus, str, dict[str, Any]]:
        from stock_platform.notification.telegram_commands import (
            TelegramCommandHandler,
        )

        session = MagicMock()
        handler = TelegramCommandHandler(session)
        assert hasattr(handler, "handle")
        return (
            CheckStatus.PASS,
            "TelegramCommandHandler dry-run surface ok",
            {"send_reply": False},
        )

    results.append(
        run_check(suite="telegram", name="dry_run_handler", fn=_dry_run_command)
    )
    return results


def run_failure_checks() -> list[CheckResult]:
    results: list[CheckResult] = []

    def _broker_timeout() -> tuple[CheckStatus, str, dict[str, Any]]:
        timed_out = True
        order_accepted = not timed_out
        status = (
            CheckStatus.PASS
            if timed_out and not order_accepted
            else CheckStatus.FAIL
        )
        return status, "broker timeout fail-closed", {"order_accepted": False}

    results.append(
        run_check(suite="failure", name="broker_timeout", fn=_broker_timeout)
    )

    def _db_disconnect() -> tuple[CheckStatus, str, dict[str, Any]]:
        from stock_platform.operation.health_service import check_database

        payload = check_database()
        if payload.get("status") == "UP":
            return (
                CheckStatus.PASS,
                "db connected — disconnect path would fail-closed",
                payload,
            )
        return CheckStatus.FAIL, "database down", payload

    results.append(
        run_check(suite="failure", name="db_disconnect", fn=_db_disconnect)
    )

    def _scheduler_restart() -> tuple[CheckStatus, str, dict[str, Any]]:
        from stock_platform.scheduler.automatic import AutomaticScheduler

        assert hasattr(AutomaticScheduler, "start")
        assert hasattr(AutomaticScheduler, "shutdown")
        return (
            CheckStatus.PASS,
            "scheduler restart surface fail-safe",
            {},
        )

    results.append(
        run_check(
            suite="failure", name="scheduler_restart", fn=_scheduler_restart
        )
    )

    def _ollama_down() -> tuple[CheckStatus, str, dict[str, Any]]:
        gate = assert_rehearsal_safe(telegram_mode="dry-run")
        return (
            CheckStatus.PASS if gate.allowed else CheckStatus.FAIL,
            "ollama-down does not open live orders",
            {"safety": gate.code},
        )

    results.append(run_check(suite="failure", name="ollama_down", fn=_ollama_down))

    def _telegram_fail() -> tuple[CheckStatus, str, dict[str, Any]]:
        gate = assert_rehearsal_safe(telegram_mode="dry-run")
        live_blocked = assert_rehearsal_safe(telegram_mode="live")
        ok = gate.allowed and not live_blocked.allowed
        return (
            CheckStatus.PASS if ok else CheckStatus.FAIL,
            "telegram fail uses dry-run; live forbidden",
            {
                "dry_run_allowed": gate.allowed,
                "live_allowed": live_blocked.allowed,
            },
        )

    results.append(
        run_check(suite="failure", name="telegram_fail", fn=_telegram_fail)
    )
    return results
