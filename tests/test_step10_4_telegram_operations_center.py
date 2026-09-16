"""STEP 10-4 — Telegram Operations Center tests."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from stock_platform.notification.telegram_approval_service import (
    ACTION_EXECUTORS,
    TelegramApprovalService,
    clear_telegram_approval_state_for_tests,
)
from stock_platform.notification.telegram_commands import (
    DANGEROUS_COMMANDS,
    TelegramCommandHandler,
    parse_telegram_input,
)
from stock_platform.notification.telegram_operations_notifier import (
    format_dashboard_summary_html,
    notify_order_event,
)


@pytest.fixture(autouse=True)
def _clear_approval_state():
    clear_telegram_approval_state_for_tests()
    yield
    clear_telegram_approval_state_for_tests()


def test_parse_telegram_input_commands() -> None:
    assert parse_telegram_input("/status")[0] == "/status"
    assert parse_telegram_input("/status@MyBot")[0] == "/status"
    assert parse_telegram_input("YES")[0] == "__confirm_yes__"
    assert parse_telegram_input("/confirm abc")[0] == "/confirm"
    assert parse_telegram_input("/confirm abc")[1] == ["abc"]
    assert parse_telegram_input("/start_scheduler 58") == (
        "/start_scheduler",
        ["58"],
    )
    assert parse_telegram_input("hello") == (None, [])


def test_dangerous_commands_require_approval_map() -> None:
    assert "/kill" in DANGEROUS_COMMANDS
    assert "/resume" in DANGEROUS_COMMANDS
    assert "/status" not in DANGEROUS_COMMANDS


def test_format_dashboard_summary_html() -> None:
    text = format_dashboard_summary_html(
        {
            "system": {
                "api_status": "HEALTHY",
                "database": {"status": "CONNECTED"},
            },
            "runtime": {
                "recovery": {"actual_state": "RUNNING"},
                "scheduler": {"actual_state": "PAUSED"},
            },
            "safety": {
                "live": {"status": "OFF"},
                "arm": {"status": "OFF"},
            },
            "broker": {"UPBIT": {"health": "HEALTHY"}},
        }
    )
    assert "SYSTEM" in text
    assert "UPBIT" in text
    assert "LIVE OFF" in text


@pytest.mark.asyncio
async def test_kill_requires_two_step_approval() -> None:
    session = MagicMock()
    handler = TelegramCommandHandler(session)
    state = SimpleNamespace(
        status=SimpleNamespace(value="ACTIVE")
    )

    with patch.object(
        handler,
        "_is_allowed_chat",
        return_value=True,
    ), patch.object(
        handler,
        "_audit",
    ), patch(
        "stock_platform.risk_engine.kill_switch_service.KillSwitchService"
    ) as ks_cls:
        ks = ks_cls.return_value
        ks.activate.return_value = state

        step1 = await handler.handle(chat_id="1", text="/kill")
        assert step1.ok is True
        assert "승인 필요" in step1.reply_text
        assert "Token" in step1.reply_text
        ks.activate.assert_not_called()

        step2 = await handler.handle(chat_id="1", text="YES")
        assert step2.ok is True
        assert "ACTIVE" in step2.reply_text
        ks.activate.assert_called_once()


@pytest.mark.asyncio
async def test_resume_approval_with_confirm_token() -> None:
    session = MagicMock()
    handler = TelegramCommandHandler(session)
    state_off = SimpleNamespace(
        status=SimpleNamespace(value="INACTIVE")
    )

    with patch.object(
        handler,
        "_is_allowed_chat",
        return_value=True,
    ), patch.object(
        handler,
        "_audit",
    ), patch(
        "stock_platform.risk_engine.kill_switch_service.KillSwitchService"
    ) as ks_cls, patch(
        "stock_platform.notification.telegram_commands.notification_publisher.publish_async",
        new=AsyncMock(),
    ):
        ks = ks_cls.return_value
        ks.deactivate.return_value = state_off

        step1 = await handler.handle(chat_id="1", text="/resume")
        token_line = [
            line
            for line in step1.reply_text.splitlines()
            if "Token" in line
        ][0]
        token = token_line.split("<code>")[1].split("</code>")[0]

        step2 = await handler.handle(
            chat_id="1",
            text=f"/confirm {token}",
        )
        assert "OFF" in step2.reply_text
        ks.deactivate.assert_called_once()


@pytest.mark.asyncio
async def test_approval_replay_rejected() -> None:
    session = MagicMock()
    handler = TelegramCommandHandler(session)
    state = SimpleNamespace(
        status=SimpleNamespace(value="ACTIVE")
    )

    with patch.object(
        handler,
        "_is_allowed_chat",
        return_value=True,
    ), patch.object(
        handler,
        "_audit",
    ), patch(
        "stock_platform.risk_engine.kill_switch_service.KillSwitchService"
    ) as ks_cls:
        ks = ks_cls.return_value
        ks.activate.return_value = state

        await handler.handle(chat_id="1", text="/kill")
        first = await handler.handle(chat_id="1", text="YES")
        assert "ACTIVE" in first.reply_text

        replay = await handler.handle(chat_id="1", text="YES")
        assert "승인 대기 없음" in replay.reply_text
        assert ks.activate.call_count == 1


@pytest.mark.asyncio
async def test_whitelist_denied() -> None:
    session = MagicMock()
    handler = TelegramCommandHandler(session)
    with patch.object(
        handler,
        "_is_allowed_chat",
        return_value=False,
    ), patch.object(
        handler,
        "_audit",
    ):
        result = await handler.handle(
            chat_id="999",
            text="/status",
        )
    assert result.authorized is False


@pytest.mark.asyncio
async def test_read_only_status_command() -> None:
    session = MagicMock()
    handler = TelegramCommandHandler(session)
    with patch.object(
        handler,
        "_is_allowed_chat",
        return_value=True,
    ), patch.object(
        handler,
        "_audit",
    ), patch.object(
        handler._status,
        "build_status_text",
        new=AsyncMock(return_value="<b>DASH</b>"),
    ):
        result = await handler.handle(chat_id="1", text="/status")
    assert result.ok is True
    assert "DASH" in result.reply_text


@pytest.mark.asyncio
async def test_approval_service_ttl_expiry() -> None:
    svc = TelegramApprovalService(ttl_seconds=0)
    pending = svc.request(
        chat_id="1",
        actor="test",
        action="kill_switch_activate",
    )
    assert svc.get_pending("1") is None
    assert svc.confirm_yes(chat_id="1") is None
    assert pending.token


@pytest.mark.asyncio
async def test_notify_order_event_mock() -> None:
    with patch(
        "stock_platform.notification.telegram_operations_notifier.notification_publisher.publish_async",
        new=AsyncMock(),
    ) as publish:
        await notify_order_event(
            status="PARTIAL",
            order_id=42,
            market="KRW-BTC",
        )
        publish.assert_awaited_once()


def test_action_executors_registered() -> None:
    assert "kill_switch_activate" in ACTION_EXECUTORS
    assert "scheduler_start" in ACTION_EXECUTORS
