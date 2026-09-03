"""STEP54 — Telegram Operations Center tests."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from stock_platform.notification.events import (
    NotificationEventType,
    NotificationLevel,
    should_dispatch_event,
)
from stock_platform.notification.history import (
    NotificationHistory,
)
from stock_platform.notification.models import (
    NotificationChannel,
    NotificationChannelResult,
    NotificationSendResult,
    NotificationSendStatus,
)
from stock_platform.notification.publisher import (
    NotificationPublisher,
)
from stock_platform.notification.service import (
    NotificationService,
)
from stock_platform.notification.telegram_commands import (
    TelegramCommandHandler,
    _extract_command,
    parse_telegram_input,
)


def test_event_level_filtering() -> None:
    assert should_dispatch_event(
        NotificationEventType.KILL_SWITCH,
        NotificationLevel.CRITICAL,
    )
    assert not should_dispatch_event(
        NotificationEventType.ORDER_SUBMITTED,
        NotificationLevel.CRITICAL,
    )
    assert should_dispatch_event(
        NotificationEventType.STOP_LOSS,
        NotificationLevel.WARN,
    )


def test_extract_command() -> None:
    assert _extract_command("/status") == "/status"
    assert _extract_command("/status@MyBot") == "/status"
    assert _extract_command("hello") is None
    assert _extract_command("/unknown") is None
    assert parse_telegram_input("YES")[0] == "__confirm_yes__"


@pytest.mark.asyncio
async def test_publisher_dispatches_to_service() -> None:
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc)
    sender = MagicMock()
    sender.send = AsyncMock(
        return_value=NotificationSendResult(
            success=True,
            results=[
                NotificationChannelResult(
                    channel=NotificationChannel.TELEGRAM,
                    status=NotificationSendStatus.SUCCESS,
                    message="ok",
                    sent_at=now,
                )
            ],
            sent_at=now,
        )
    )
    history = NotificationHistory()
    service = NotificationService(
        sender=sender,
        history=history,
    )
    with patch.object(
        NotificationService,
        "_record_audit",
        staticmethod(lambda **kwargs: None),
    ):
        publisher = NotificationPublisher(service=service)
        event = await publisher.publish_async(
            event_type=NotificationEventType.SYSTEM_START,
            title="Start",
            message="started",
            detail={},
        )
    assert event.event_type == "SYSTEM_START"
    sender.send.assert_awaited_once()
    assert len(history.recent()) == 1


@pytest.mark.asyncio
async def test_command_permission_denied() -> None:
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
    assert "권한" in result.reply_text


@pytest.mark.asyncio
async def test_command_status_authorized() -> None:
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
        new=AsyncMock(return_value="<b>OK</b>"),
    ):
        result = await handler.handle(
            chat_id="1",
            text="/status",
        )
    assert result.ok is True
    assert result.command == "/status"
    assert "OK" in result.reply_text


@pytest.mark.asyncio
async def test_command_health() -> None:
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
        "build_health_text",
        new=AsyncMock(return_value="HEALTH_OK"),
    ):
        result = await handler.handle(
            chat_id="1",
            text="/health",
        )
    assert result.ok is True
    assert result.reply_text == "HEALTH_OK"


@pytest.mark.asyncio
async def test_kill_and_resume() -> None:
    session = MagicMock()
    handler = TelegramCommandHandler(session)
    state = SimpleNamespace(
        status=SimpleNamespace(value="ACTIVE")
    )
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
        ks.activate.return_value = state
        ks.deactivate.return_value = state_off

        kill_req = await handler.handle(
            chat_id="1",
            text="/kill",
        )
        assert kill_req.ok is True
        assert "승인 필요" in kill_req.reply_text
        kill = await handler.handle(
            chat_id="1",
            text="YES",
        )
        resume_req = await handler.handle(
            chat_id="1",
            text="/resume",
        )
        assert "승인 필요" in resume_req.reply_text
        resume = await handler.handle(
            chat_id="1",
            text="YES",
        )

    assert kill.ok is True
    assert "ACTIVE" in kill.reply_text
    assert resume.ok is True
    assert "OFF" in resume.reply_text


@pytest.mark.asyncio
async def test_telegram_sender_via_service_only() -> None:
    """도메인은 TelegramSender를 직접 호출하지 않는다."""

    from stock_platform.risk_engine.alert import (
        CompositeRiskAlertNotifier,
    )

    with patch(
        "stock_platform.risk_engine.alert.notification_publisher.publish_async",
        new=AsyncMock(),
    ) as publish:
        await CompositeRiskAlertNotifier().send(
            title="Daily loss",
            message="limit reached",
            detail={
                "event_type": NotificationEventType.DAILY_LOSS.value
            },
        )
        publish.assert_awaited_once()


def test_lifecycle_starts_telegram_ops_scheduler() -> None:
    from stock_platform.api.lifecycle import (
        ApplicationLifecycle,
    )

    lifecycle = ApplicationLifecycle()
    with patch(
        "stock_platform.api.lifecycle.validate_startup_settings"
    ), patch(
        "stock_platform.api.lifecycle.verify_database_connection",
        new=AsyncMock(),
    ), patch(
        "stock_platform.api.lifecycle.bootstrap_auth_admin",
        new=AsyncMock(),
    ), patch(
        "stock_platform.api.lifecycle.broker_recovery_manager.recover",
        new=AsyncMock(return_value={"success": True}),
    ), patch.object(
        lifecycle,
        "_startup_strategy_runtime",
        new=AsyncMock(),
    ), patch(
        "stock_platform.api.lifecycle.market_data_persistence_worker.start",
        new=AsyncMock(),
    ), patch.object(
        lifecycle,
        "_publish_lifecycle_event",
        new=AsyncMock(),
    ), patch(
        "stock_platform.api.lifecycle.daily_loss_monitor_scheduler.start"
    ), patch(
        "stock_platform.api.lifecycle.position_exit_monitor_scheduler.start"
    ), patch(
        "stock_platform.api.lifecycle.telegram_ops_scheduler.start"
    ) as tg_start, patch(
        "stock_platform.api.lifecycle.strategy_runtime_reload_scheduler.start"
    ), patch(
        "stock_platform.api.lifecycle.strategy_approval_scheduler.start"
    ), patch(
        "stock_platform.api.lifecycle.strategy_deployment_pipeline_scheduler.start"
    ), patch(
        "stock_platform.api.lifecycle.deployment_performance_monitor_scheduler.start"
    ), patch(
        "stock_platform.api.lifecycle.order_outbox_scheduler.start"
    ), patch(
        "stock_platform.api.lifecycle.broker_recovery_scheduler.start"
    ):
        asyncio.run(lifecycle.startup())

    tg_start.assert_called_once()
    assert lifecycle.started is True


def test_delivery_log_persists_original_payload_when_rendered_none() -> None:
    """alert_v2_formatted 경로에서도 dedupe_key가 durable log에 남아야 한다."""

    from stock_platform.notification.service import NotificationService

    class _FakeEntity:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    class _FakeSession:
        def __init__(self):
            self.added = []
            self.committed = False
            self.closed = False

        def add(self, entity):
            self.added.append(entity)

        def commit(self):
            self.committed = True

        def rollback(self):
            pass

        def close(self):
            self.closed = True

    fake_session = _FakeSession()

    class _FakeFactory:
        def __call__(self):
            return fake_session

    now = __import__("datetime").datetime.now(__import__("datetime").timezone.utc)
    result = NotificationSendResult(
        success=True,
        results=[
            NotificationChannelResult(
                channel=NotificationChannel.TELEGRAM,
                status=NotificationSendStatus.SUCCESS,
                message="ok",
                sent_at=now,
            )
        ],
        sent_at=now,
    )

    with patch(
        "stock_platform.database.session.get_session_factory",
        return_value=_FakeFactory(),
    ), patch(
        "stock_platform.notification.template_entities.ChannelDeliveryLogEntity",
        _FakeEntity,
    ):
        NotificationService._persist_delivery_log(
            event_type="UPBIT_AUTO_LONG_HOLD",
            rendered=None,
            result=result,
            original_payload={
                "dedupe_key": "LONG_HOLD:17483:6H",
                "symbol": "KRW-PROM",
            },
        )

    assert fake_session.committed is True
    assert len(fake_session.added) == 1
    payload = fake_session.added[0].kwargs.get("original_payload_json") or {}
    assert payload.get("dedupe_key") == "LONG_HOLD:17483:6H"
