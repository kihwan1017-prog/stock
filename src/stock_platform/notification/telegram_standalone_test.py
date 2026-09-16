"""Telegram 실제 발송 단독 점검 (주문·Broker·Scheduler·DB 미사용)."""

from __future__ import annotations

import asyncio
import os
import re
import uuid
from datetime import datetime
from typing import Any

import httpx

from stock_platform.common.settings import get_settings
from stock_platform.notification.models import (
    NotificationMessage,
    NotificationSendStatus,
)
from stock_platform.notification.telegram_sender import (
    TelegramNotificationSender,
)

_ALLOWED_APP_ENVS = frozenset({"local", "dev", "development"})
_ALLOW_FLAG = "TELEGRAM_STANDALONE_TEST_ALLOWED"

# 사용자에게 보여줄 오류 코드 (토큰/채팅 ID 미포함)
ERROR_BOT_BLOCKED = "bot_was_blocked_by_the_user"
ERROR_CHAT_NOT_FOUND = "chat_not_found"
ERROR_NOT_MEMBER = "bot_is_not_a_member_of_the_group_chat"
ERROR_NOT_ENOUGH_RIGHTS = "not_enough_rights"
ERROR_INVALID_TOKEN = "invalid_token"
ERROR_TELEGRAM_API = "telegram_api_error"
ERROR_CONFIG = "config_error"
ERROR_ENV = "env_not_allowed"


def mask_secrets(text: str, *secrets: str) -> str:
    """Token/Chat ID/DSN 등 민감정보 마스킹."""

    redacted = text or ""
    for secret in secrets:
        if secret and len(secret) >= 4:
            redacted = redacted.replace(secret, "***")
    # Bot token 패턴 전체 마스킹
    redacted = re.sub(
        r"bot[0-9]+:[A-Za-z0-9_-]+",
        "bot***:***",
        redacted,
        flags=re.I,
    )
    redacted = re.sub(
        r"(?<=/bot)[0-9]+:[A-Za-z0-9_-]+",
        "***:***",
        redacted,
        flags=re.I,
    )
    redacted = re.sub(
        r"postgresql(\+psycopg)?://[^\s]+",
        "postgresql://***",
        redacted,
        flags=re.I,
    )
    # chat_id 숫자 나열을 URL/쿼리에서 과도하게 지우지 않도록
    # 명시적으로 전달된 chat_id만 위에서 치환
    return redacted


def classify_telegram_error(
    description: str,
    *,
    http_status: int | None = None,
) -> str:
    """Telegram description/HTTP 상태를 안전한 오류 코드로 분류."""

    text = (description or "").lower()
    if "blocked by the user" in text:
        return ERROR_BOT_BLOCKED
    if "chat not found" in text:
        return ERROR_CHAT_NOT_FOUND
    if "not a member of the" in text or "bot is not a member" in text:
        return ERROR_NOT_MEMBER
    if "not enough rights" in text or "have no rights" in text:
        return ERROR_NOT_ENOUGH_RIGHTS
    if (
        http_status in {401, 404}
        or "unauthorized" in text
        or "invalid token" in text
        or "token is invalid" in text
    ):
        return ERROR_INVALID_TOKEN
    return ERROR_TELEGRAM_API


def extract_telegram_description(
    response: httpx.Response | None,
    fallback: str,
) -> str:
    """응답 JSON의 description을 안전하게 추출."""

    if response is None:
        return fallback
    try:
        payload = response.json()
    except Exception:  # noqa: BLE001
        return fallback
    if isinstance(payload, dict):
        desc = payload.get("description")
        if desc:
            return str(desc)
    return fallback


async def telegram_method(
    client: httpx.AsyncClient,
    *,
    bot_token: str,
    method: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """getMe/getChat/sendMessage 등 Bot API 호출 (시크릿 미로깅)."""

    url = f"https://api.telegram.org/bot{bot_token}/{method}"
    try:
        if payload is None:
            response = await client.get(url)
        else:
            response = await client.post(url, json=payload)
    except httpx.TimeoutException as exc:
        return {
            "ok": False,
            "http_status": None,
            "description": f"Timeout: {type(exc).__name__}",
            "error_code": ERROR_TELEGRAM_API,
            "result": None,
        }
    except httpx.HTTPError as exc:
        return {
            "ok": False,
            "http_status": None,
            "description": f"HTTPError: {type(exc).__name__}",
            "error_code": ERROR_TELEGRAM_API,
            "result": None,
        }

    description = extract_telegram_description(
        response,
        fallback=f"HTTP {response.status_code}",
    )
    try:
        body = response.json()
    except Exception:  # noqa: BLE001
        body = {}

    ok = bool(isinstance(body, dict) and body.get("ok") is True)
    if response.status_code >= 400 or not ok:
        return {
            "ok": False,
            "http_status": response.status_code,
            "description": description,
            "error_code": classify_telegram_error(
                description,
                http_status=response.status_code,
            ),
            "result": None,
        }
    return {
        "ok": True,
        "http_status": response.status_code,
        "description": description if description != f"HTTP {response.status_code}" else "ok",
        "error_code": None,
        "result": body.get("result") if isinstance(body, dict) else None,
    }


def assert_standalone_env_allowed() -> tuple[bool, str]:
    settings = get_settings()
    env = settings.app_env.strip().lower()
    flag = (os.environ.get(_ALLOW_FLAG) or "").strip().lower()
    if env in _ALLOWED_APP_ENVS:
        return True, env
    if flag in {"1", "true", "yes", "on"}:
        return True, f"{env}+flag"
    return (
        False,
        (
            f"app_env={env} not allowed for standalone telegram test; "
            f"use LOCAL/DEV or set {_ALLOW_FLAG}=true"
        ),
    )


def build_test_message(*, test_id: str, app_env: str) -> NotificationMessage:
    now = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")
    body = (
        "Telegram 운영 알림 테스트\n"
        f"환경: {app_env.upper()}\n"
        "실거래 주문: 실행 안 함\n"
        "Paper 주문: 실행 안 함\n"
        f"시각: {now}\n"
        f"결과 확인용 ID: {test_id}"
    )
    return NotificationMessage(
        title="[stock-platform]",
        message=body,
        detail={
            "test_id": test_id,
            "source": "telegram_standalone_test",
            "live_order": False,
            "paper_order": False,
        },
    )


def _safe_fail(
    *,
    reason: str,
    error_code: str,
    token: str = "",
    chat_id: str = "",
    test_id: str | None = None,
    get_me: str | None = None,
    get_chat: str | None = None,
    description: str | None = None,
) -> dict[str, Any]:
    return {
        "ok": False,
        "exit_code": 1,
        "message_sent": False,
        "test_id": test_id,
        "error_code": error_code,
        "reason": mask_secrets(reason, token, chat_id),
        "description": (
            mask_secrets(description, token, chat_id)
            if description
            else None
        ),
        "getMe": get_me,
        "getChat": get_chat,
    }


async def send_standalone_telegram_test(
    *,
    sender: TelegramNotificationSender | None = None,
    client: httpx.AsyncClient | None = None,
) -> dict[str, Any]:
    """
    getMe → getChat → sendMessage 순으로 진단·발송.
    주문/Broker/Scheduler/DB 세션을 import·호출하지 않는다.
    """

    allowed, env_label = assert_standalone_env_allowed()
    if not allowed:
        return _safe_fail(
            reason=env_label,
            error_code=ERROR_ENV,
        )

    settings = get_settings()
    token = settings.telegram_bot_token.strip()
    chat_id = settings.telegram_chat_id.strip()
    if not token:
        return _safe_fail(
            reason="Telegram Bot Token not configured",
            error_code=ERROR_CONFIG,
        )
    if not chat_id:
        return _safe_fail(
            reason="Telegram Chat ID not configured",
            error_code=ERROR_CONFIG,
        )

    test_id = f"tg-test-{uuid.uuid4().hex[:12]}"
    owns_client = client is None
    active_client = client or httpx.AsyncClient(timeout=10.0)

    try:
        # 1) 토큰 유효성
        me = await telegram_method(
            active_client, bot_token=token, method="getMe"
        )
        if not me["ok"]:
            return _safe_fail(
                reason=f"getMe failed: {me['description']}",
                error_code=me["error_code"] or ERROR_INVALID_TOKEN,
                token=token,
                chat_id=chat_id,
                test_id=test_id,
                get_me="fail",
                get_chat="skipped",
                description=me["description"],
            )

        # 2) Chat ID 접근 가능 여부
        chat = await telegram_method(
            active_client,
            bot_token=token,
            method="getChat",
            payload={"chat_id": chat_id},
        )
        if not chat["ok"]:
            return _safe_fail(
                reason=f"getChat failed: {chat['description']}",
                error_code=chat["error_code"] or ERROR_TELEGRAM_API,
                token=token,
                chat_id=chat_id,
                test_id=test_id,
                get_me="ok",
                get_chat="fail",
                description=chat["description"],
            )

        # 3) 실제 발송 (기존 Sender 재사용 또는 주입된 mock)
        message = build_test_message(
            test_id=test_id,
            app_env=settings.app_env,
        )
        active_sender = sender or TelegramNotificationSender(
            enabled=True,
            bot_token=token,
            chat_id=chat_id,
            timeout_seconds=10.0,
            client=active_client,
        )
        result = await active_sender.send(message)
        if result.status == NotificationSendStatus.SUCCESS:
            return {
                "ok": True,
                "exit_code": 0,
                "message_sent": True,
                "test_id": test_id,
                "reason": None,
                "error_code": None,
                "description": None,
                "getMe": "ok",
                "getChat": "ok",
            }

        raw = result.message or "Telegram send failed"
        error_code = classify_telegram_error(raw)
        return _safe_fail(
            reason=raw,
            error_code=error_code,
            token=token,
            chat_id=chat_id,
            test_id=test_id,
            get_me="ok",
            get_chat="ok",
            description=raw,
        )
    finally:
        if owns_client:
            await active_client.aclose()


def run_standalone_telegram_test() -> int:
    try:
        outcome = asyncio.run(send_standalone_telegram_test())
    except Exception as exc:  # noqa: BLE001
        settings = get_settings()
        reason = mask_secrets(
            f"{type(exc).__name__}: {exc}",
            settings.telegram_bot_token,
            settings.telegram_chat_id,
        )
        print("TELEGRAM_TEST_FAIL")
        print(f"error_code={ERROR_TELEGRAM_API}")
        print(f"reason={reason}")
        return 2

    if outcome.get("ok"):
        print("TELEGRAM_TEST_OK")
        print("message_sent=true")
        print(f"test_id={outcome.get('test_id')}")
        print("getMe=ok")
        print("getChat=ok")
        return 0

    print("TELEGRAM_TEST_FAIL")
    print(f"error_code={outcome.get('error_code') or ERROR_TELEGRAM_API}")
    if outcome.get("description"):
        print(f"description={outcome.get('description')}")
    print(f"reason={outcome.get('reason')}")
    if outcome.get("getMe") is not None:
        print(f"getMe={outcome.get('getMe')}")
    if outcome.get("getChat") is not None:
        print(f"getChat={outcome.get('getChat')}")
    if outcome.get("test_id"):
        print(f"test_id={outcome.get('test_id')}")
    return int(outcome.get("exit_code") or 1)
