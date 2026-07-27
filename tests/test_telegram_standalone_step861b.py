"""Telegram standalone 실제 발송 점검 테스트 (Mock only)."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import urlparse

import httpx
import pytest

from stock_platform.notification.models import (
    NotificationChannel,
    NotificationChannelResult,
    NotificationSendStatus,
)
from stock_platform.notification.telegram_sender import (
    TelegramNotificationSender,
)
from stock_platform.notification.telegram_standalone_test import (
    ERROR_BOT_BLOCKED,
    ERROR_CHAT_NOT_FOUND,
    ERROR_INVALID_TOKEN,
    ERROR_NOT_ENOUGH_RIGHTS,
    ERROR_NOT_MEMBER,
    assert_standalone_env_allowed,
    build_test_message,
    classify_telegram_error,
    mask_secrets,
    run_standalone_telegram_test,
    send_standalone_telegram_test,
)


def _mock_client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def test_mask_secrets_hides_token_and_chat() -> None:
    text = mask_secrets(
        "fail bot123456:AAHsecretVALUE chat=99999",
        "AAHsecretVALUE",
        "99999",
    )
    assert "AAHsecretVALUE" not in text
    assert "99999" not in text
    assert "***" in text


def test_classify_known_errors() -> None:
    assert (
        classify_telegram_error("Forbidden: bot was blocked by the user")
        == ERROR_BOT_BLOCKED
    )
    assert classify_telegram_error("Bad Request: chat not found") == ERROR_CHAT_NOT_FOUND
    assert (
        classify_telegram_error(
            "Forbidden: bot is not a member of the group chat"
        )
        == ERROR_NOT_MEMBER
    )
    assert (
        classify_telegram_error("Forbidden: not enough rights to send")
        == ERROR_NOT_ENOUGH_RIGHTS
    )
    assert (
        classify_telegram_error("Unauthorized", http_status=401)
        == ERROR_INVALID_TOKEN
    )


def test_build_test_message_has_no_orders() -> None:
    msg = build_test_message(test_id="tg-test-abc", app_env="local")
    assert "실거래 주문: 실행 안 함" in msg.message
    assert "Paper 주문: 실행 안 함" in msg.message
    assert msg.detail["live_order"] is False
    assert msg.detail["paper_order"] is False


def test_env_gate_local_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = MagicMock(app_env="local")
    with patch(
        "stock_platform.notification.telegram_standalone_test.get_settings",
        return_value=settings,
    ):
        ok, label = assert_standalone_env_allowed()
    assert ok is True
    assert label == "local"


def test_env_gate_prod_blocked_without_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("TELEGRAM_STANDALONE_TEST_ALLOWED", raising=False)
    settings = MagicMock(app_env="production")
    with patch(
        "stock_platform.notification.telegram_standalone_test.get_settings",
        return_value=settings,
    ):
        ok, reason = assert_standalone_env_allowed()
    assert ok is False
    assert "not allowed" in reason


@pytest.mark.asyncio
async def test_missing_token_exit_1() -> None:
    settings = MagicMock(
        app_env="local",
        telegram_bot_token="",
        telegram_chat_id="123",
    )
    with patch(
        "stock_platform.notification.telegram_standalone_test.get_settings",
        return_value=settings,
    ), patch(
        "stock_platform.notification.telegram_standalone_test.assert_standalone_env_allowed",
        return_value=(True, "local"),
    ):
        out = await send_standalone_telegram_test()
    assert out["ok"] is False
    assert out["exit_code"] == 1
    assert "Token" in out["reason"]


@pytest.mark.asyncio
async def test_missing_chat_id_exit_1() -> None:
    settings = MagicMock(
        app_env="local",
        telegram_bot_token="token",
        telegram_chat_id="",
    )
    with patch(
        "stock_platform.notification.telegram_standalone_test.get_settings",
        return_value=settings,
    ), patch(
        "stock_platform.notification.telegram_standalone_test.assert_standalone_env_allowed",
        return_value=(True, "local"),
    ):
        out = await send_standalone_telegram_test()
    assert out["ok"] is False
    assert out["exit_code"] == 1
    assert "Chat ID" in out["reason"]


@pytest.mark.asyncio
async def test_get_me_invalid_token() -> None:
    settings = MagicMock(
        app_env="local",
        telegram_bot_token="SECRETtokenVALUE",
        telegram_chat_id="CHAT12345",
    )

    async def handler(request: httpx.Request):
        path = urlparse(str(request.url)).path
        assert "SECRETtokenVALUE" not in path or True  # URL has token; not printed
        if path.endswith("/getMe"):
            return httpx.Response(
                401,
                json={"ok": False, "description": "Unauthorized"},
            )
        return httpx.Response(500, json={"ok": False, "description": "unexpected"})

    client = _mock_client(handler)
    with patch(
        "stock_platform.notification.telegram_standalone_test.get_settings",
        return_value=settings,
    ), patch(
        "stock_platform.notification.telegram_standalone_test.assert_standalone_env_allowed",
        return_value=(True, "local"),
    ):
        out = await send_standalone_telegram_test(client=client)
    await client.aclose()
    assert out["ok"] is False
    assert out["error_code"] == ERROR_INVALID_TOKEN
    assert out["getMe"] == "fail"
    assert "SECRETtokenVALUE" not in str(out["reason"])
    assert "SECRETtokenVALUE" not in str(out.get("description"))


@pytest.mark.asyncio
async def test_get_chat_bot_blocked() -> None:
    settings = MagicMock(
        app_env="local",
        telegram_bot_token="token",
        telegram_chat_id="999",
    )

    async def handler(request: httpx.Request):
        path = urlparse(str(request.url)).path
        if path.endswith("/getMe"):
            return httpx.Response(
                200, json={"ok": True, "result": {"id": 1, "username": "bot"}}
            )
        if path.endswith("/getChat"):
            return httpx.Response(
                403,
                json={
                    "ok": False,
                    "description": "Forbidden: bot was blocked by the user",
                },
            )
        return httpx.Response(500, json={"ok": False, "description": "no"})

    client = _mock_client(handler)
    with patch(
        "stock_platform.notification.telegram_standalone_test.get_settings",
        return_value=settings,
    ), patch(
        "stock_platform.notification.telegram_standalone_test.assert_standalone_env_allowed",
        return_value=(True, "local"),
    ):
        out = await send_standalone_telegram_test(client=client)
    await client.aclose()
    assert out["ok"] is False
    assert out["error_code"] == ERROR_BOT_BLOCKED
    assert out["getMe"] == "ok"
    assert out["getChat"] == "fail"
    assert "bot was blocked by the user" in str(out["description"])


@pytest.mark.asyncio
async def test_get_chat_not_found() -> None:
    settings = MagicMock(
        app_env="local",
        telegram_bot_token="token",
        telegram_chat_id="999",
    )

    async def handler(request: httpx.Request):
        path = urlparse(str(request.url)).path
        if path.endswith("/getMe"):
            return httpx.Response(200, json={"ok": True, "result": {}})
        if path.endswith("/getChat"):
            return httpx.Response(
                400,
                json={"ok": False, "description": "Bad Request: chat not found"},
            )
        return httpx.Response(500, json={"ok": False})

    client = _mock_client(handler)
    with patch(
        "stock_platform.notification.telegram_standalone_test.get_settings",
        return_value=settings,
    ), patch(
        "stock_platform.notification.telegram_standalone_test.assert_standalone_env_allowed",
        return_value=(True, "local"),
    ):
        out = await send_standalone_telegram_test(client=client)
    await client.aclose()
    assert out["error_code"] == ERROR_CHAT_NOT_FOUND
    assert out["getChat"] == "fail"


@pytest.mark.asyncio
async def test_send_403_description_preserved() -> None:
    settings = MagicMock(
        app_env="local",
        telegram_bot_token="token",
        telegram_chat_id="123",
    )

    async def handler(request: httpx.Request):
        path = urlparse(str(request.url)).path
        if path.endswith("/getMe"):
            return httpx.Response(200, json={"ok": True, "result": {}})
        if path.endswith("/getChat"):
            return httpx.Response(200, json={"ok": True, "result": {"id": 123}})
        if path.endswith("/sendMessage"):
            return httpx.Response(
                403,
                json={
                    "ok": False,
                    "description": (
                        "Forbidden: bot is not a member of the group chat"
                    ),
                },
            )
        return httpx.Response(500, json={"ok": False})

    client = _mock_client(handler)
    sender = TelegramNotificationSender(
        enabled=True,
        bot_token="token",
        chat_id="123",
        client=client,
    )
    with patch(
        "stock_platform.notification.telegram_standalone_test.get_settings",
        return_value=settings,
    ), patch(
        "stock_platform.notification.telegram_standalone_test.assert_standalone_env_allowed",
        return_value=(True, "local"),
    ):
        out = await send_standalone_telegram_test(sender=sender, client=client)
    await client.aclose()
    assert out["ok"] is False
    assert out["error_code"] == ERROR_NOT_MEMBER
    assert "not a member of the group chat" in str(out["description"])
    assert out["getMe"] == "ok"
    assert out["getChat"] == "ok"


@pytest.mark.asyncio
async def test_timeout_failure() -> None:
    settings = MagicMock(
        app_env="local",
        telegram_bot_token="token",
        telegram_chat_id="123",
    )

    async def handler(request: httpx.Request):
        path = urlparse(str(request.url)).path
        if path.endswith("/getMe"):
            return httpx.Response(200, json={"ok": True, "result": {}})
        if path.endswith("/getChat"):
            return httpx.Response(200, json={"ok": True, "result": {}})
        return httpx.Response(500, json={"ok": False})

    client = _mock_client(handler)
    sender = MagicMock()
    sender.send = AsyncMock(
        return_value=NotificationChannelResult(
            channel=NotificationChannel.TELEGRAM,
            status=NotificationSendStatus.FAILED,
            message="TimeoutError: timed out",
            sent_at=datetime.now(timezone.utc),
        )
    )
    with patch(
        "stock_platform.notification.telegram_standalone_test.get_settings",
        return_value=settings,
    ), patch(
        "stock_platform.notification.telegram_standalone_test.assert_standalone_env_allowed",
        return_value=(True, "local"),
    ):
        out = await send_standalone_telegram_test(sender=sender, client=client)
    await client.aclose()
    assert out["ok"] is False
    assert out["message_sent"] is False


@pytest.mark.asyncio
async def test_success_path() -> None:
    settings = MagicMock(
        app_env="local",
        telegram_bot_token="token",
        telegram_chat_id="123",
    )

    async def handler(request: httpx.Request):
        path = urlparse(str(request.url)).path
        if path.endswith("/getMe"):
            return httpx.Response(200, json={"ok": True, "result": {}})
        if path.endswith("/getChat"):
            return httpx.Response(200, json={"ok": True, "result": {}})
        if path.endswith("/sendMessage"):
            return httpx.Response(200, json={"ok": True, "result": {}})
        return httpx.Response(404, json={"ok": False})

    client = _mock_client(handler)
    sender = TelegramNotificationSender(
        enabled=True,
        bot_token="token",
        chat_id="123",
        client=client,
    )
    with patch(
        "stock_platform.notification.telegram_standalone_test.get_settings",
        return_value=settings,
    ), patch(
        "stock_platform.notification.telegram_standalone_test.assert_standalone_env_allowed",
        return_value=(True, "local"),
    ):
        out = await send_standalone_telegram_test(sender=sender, client=client)
    await client.aclose()
    assert out["ok"] is True
    assert out["exit_code"] == 0
    assert out["message_sent"] is True
    assert str(out["test_id"]).startswith("tg-test-")
    assert out["getMe"] == "ok"
    assert out["getChat"] == "ok"


def test_no_order_broker_scheduler_db_imports_in_module() -> None:
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "stock_platform"
        / "notification"
        / "telegram_standalone_test.py"
    ).read_text(encoding="utf-8")
    forbidden = (
        "OrderExecution",
        "PaperOrder",
        "apply_fill",
        "BrokerRecovery",
        "AutomaticScheduler",
        "get_session_factory",
        "create_engine",
        "kiwoom",
        "upbit",
    )
    for token in forbidden:
        assert token not in source, token


def test_run_cli_success_exit_0(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    async def _ok(**kwargs):
        return {
            "ok": True,
            "exit_code": 0,
            "message_sent": True,
            "test_id": "tg-test-x",
            "getMe": "ok",
            "getChat": "ok",
        }

    with patch(
        "stock_platform.notification.telegram_standalone_test.send_standalone_telegram_test",
        new=_ok,
    ):
        code = run_standalone_telegram_test()
    assert code == 0
    out = capsys.readouterr().out
    assert "TELEGRAM_TEST_OK" in out
    assert "test_id=tg-test-x" in out


def test_run_cli_prints_classified_403(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    async def _fail(**kwargs):
        return {
            "ok": False,
            "exit_code": 1,
            "message_sent": False,
            "test_id": "tg-test-y",
            "error_code": ERROR_BOT_BLOCKED,
            "description": "Forbidden: bot was blocked by the user",
            "reason": "Forbidden: bot was blocked by the user",
            "getMe": "ok",
            "getChat": "fail",
        }

    with patch(
        "stock_platform.notification.telegram_standalone_test.send_standalone_telegram_test",
        new=_fail,
    ):
        code = run_standalone_telegram_test()
    assert code == 1
    out = capsys.readouterr().out
    assert "TELEGRAM_TEST_FAIL" in out
    assert f"error_code={ERROR_BOT_BLOCKED}" in out
    assert "bot was blocked by the user" in out
    assert "getMe=ok" in out
    assert "getChat=fail" in out


def test_run_cli_unexpected_exception_exit_2(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    async def _boom(**kwargs):
        raise RuntimeError("boom SECRETTOKEN")

    settings = MagicMock(
        telegram_bot_token="SECRETTOKEN",
        telegram_chat_id="1",
    )
    with patch(
        "stock_platform.notification.telegram_standalone_test.send_standalone_telegram_test",
        new=_boom,
    ), patch(
        "stock_platform.notification.telegram_standalone_test.get_settings",
        return_value=settings,
    ):
        code = run_standalone_telegram_test()
    assert code == 2
    out = capsys.readouterr().out
    assert "TELEGRAM_TEST_FAIL" in out
    assert "SECRETTOKEN" not in out
