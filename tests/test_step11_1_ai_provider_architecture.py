"""STEP 11-1 — AI Provider Framework tests (Mock only, no live API)."""

from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from stock_platform.ai.providers.capability import AICapability
from stock_platform.ai.providers.circuit_breaker import CircuitBreaker, CircuitState
from stock_platform.ai.providers.config import AIProviderConfig
from stock_platform.ai.providers.dto import AIChatRequest, ChatMessage, FinishReason
from stock_platform.ai.providers.manager import AIManager, reset_ai_manager
from stock_platform.ai.providers.mock_provider import MockAIProvider
from stock_platform.ai.providers.registry import (
    AIProviderRegistry,
    build_default_registry,
)
from stock_platform.ai.providers.security import mask_secret, sanitize_for_log


@pytest.fixture(autouse=True)
def _reset_manager():
    reset_ai_manager()
    yield
    reset_ai_manager()


def test_mask_secret() -> None:
    masked = mask_secret("sk-abcdefghijklmnop")
    assert masked.endswith("mnop")
    assert "*" in masked
    assert "sk-abcd" not in masked
    assert sanitize_for_log({"api_key": "secret-value-1234"})["api_key"].endswith(
        "1234"
    )


def test_mock_chat_fixed_signal() -> None:
    provider = MockAIProvider(
        AIProviderConfig(
            provider_id="mock",
            enabled=True,
            model="mock-v1",
            extra={"fixed_signal": "BUY", "latency_ms": 1},
        )
    )

    async def _run() -> None:
        await provider.initialize()
        health = await provider.health()
        assert health.status.value == "HEALTHY"
        response = await provider.chat(
            AIChatRequest(messages=[ChatMessage(role="user", content="hello")])
        )
        assert response.ok
        assert response.content == "BUY"
        assert response.provider_id == "mock"

    asyncio.run(_run())


def test_mock_error_and_timeout_simulation() -> None:
    err_provider = MockAIProvider(
        AIProviderConfig(
            provider_id="mock",
            enabled=True,
            extra={"simulate_error": True},
        )
    )
    timeout_provider = MockAIProvider(
        AIProviderConfig(
            provider_id="mock",
            enabled=True,
            extra={"simulate_timeout": True},
        )
    )

    async def _run() -> None:
        err = await err_provider.chat(
            AIChatRequest(messages=[ChatMessage(role="user", content="x")])
        )
        assert not err.ok
        assert err.error and err.error.code == "MOCK_ERROR"

        timed = await timeout_provider.chat(
            AIChatRequest(messages=[ChatMessage(role="user", content="x")])
        )
        assert not timed.ok
        assert timed.finish_reason == FinishReason.TIMEOUT

    asyncio.run(_run())


def test_registry_and_capabilities() -> None:
    registry = build_default_registry()
    assert "mock" in registry.list_ids()
    mock = registry.require("mock")
    assert mock.supports(AICapability.CHAT)
    assert registry.default_provider() is not None
    assert registry.providers_with_capability(AICapability.CHAT)


def test_circuit_breaker() -> None:
    cb = CircuitBreaker(failure_threshold=2, reset_seconds=60)
    assert cb.allow()
    cb.record_failure()
    assert cb.state == CircuitState.CLOSED
    cb.record_failure()
    assert cb.state == CircuitState.OPEN
    assert not cb.allow()
    cb.record_success()  # won't run while open unless half-open
    # force half-open path
    cb.state = CircuitState.HALF_OPEN
    assert cb.allow()
    cb.record_success()
    assert cb.state == CircuitState.CLOSED


@pytest.mark.asyncio
async def test_manager_chat_retry_and_fallback() -> None:
    registry = AIProviderRegistry()
    failing = MockAIProvider(
        AIProviderConfig(
            provider_id="mock",
            enabled=True,
            is_default=True,
            priority=1,
            retry_max=1,
            timeout_seconds=2,
            extra={"simulate_error": True},
        )
    )
    # 두 번째 provider — 동일 mock 클래스지만 id를 바꿔 등록
    backup_cfg = AIProviderConfig(
        provider_id="mock_backup",
        enabled=True,
        priority=2,
        model="mock-v1",
        extra={"fixed_signal": "SELL", "latency_ms": 1},
    )
    backup = MockAIProvider(backup_cfg)
    # provider_id는 config에서 설정됨

    registry.register(failing, failing._config)
    registry.register(backup, backup_cfg)
    manager = AIManager(registry=registry)

    response = await manager.chat(
        AIChatRequest(messages=[ChatMessage(role="user", content="go")]),
        fallback=True,
    )
    assert response.ok
    assert response.content == "SELL"
    assert response.provider_id == "mock_backup"


@pytest.mark.asyncio
async def test_manager_circuit_opens() -> None:
    registry = AIProviderRegistry()
    provider = MockAIProvider(
        AIProviderConfig(
            provider_id="mock",
            enabled=True,
            is_default=True,
            retry_max=0,
            circuit_failure_threshold=1,
            extra={"simulate_error": True},
        )
    )
    registry.register(provider, provider._config)
    manager = AIManager(registry=registry)

    first = await manager.chat(
        AIChatRequest(messages=[ChatMessage(role="user", content="a")]),
        fallback=False,
    )
    assert not first.ok
    second = await manager.chat(
        AIChatRequest(messages=[ChatMessage(role="user", content="b")]),
        fallback=False,
    )
    assert not second.ok
    assert second.error and second.error.code == "CIRCUIT_OPEN"


@pytest.mark.asyncio
async def test_manager_timeout() -> None:
    registry = AIProviderRegistry()
    provider = MockAIProvider(
        AIProviderConfig(
            provider_id="mock",
            enabled=True,
            is_default=True,
            timeout_seconds=0.01,
            retry_max=0,
            extra={"latency_ms": 200},
        )
    )
    registry.register(provider, provider._config)
    manager = AIManager(registry=registry)
    response = await manager.chat(
        AIChatRequest(messages=[ChatMessage(role="user", content="slow")]),
        fallback=False,
    )
    assert not response.ok
    assert response.finish_reason == FinishReason.TIMEOUT


@pytest.mark.asyncio
async def test_manager_health_and_dashboard() -> None:
    manager = AIManager.create_default()
    await manager.initialize()
    health = await manager.health()
    assert any(h.provider_id == "mock" for h in health)
    block = manager.dashboard_block()
    assert block["count"] >= 1
    assert any(i["id"] == "mock" for i in block["items"])
    test = await manager.test_provider("mock", prompt="HOLD")
    assert test["response"]["ok"] is True


def test_admin_providers_api() -> None:
    from stock_platform.api.main import app
    from stock_platform.auth.deps import AuthenticatedUser, require_admin

    client = TestClient(app)

    def _fake_admin() -> AuthenticatedUser:
        return AuthenticatedUser(
            user_id=1,
            username="admin",
            roles=["admin"],
            permissions=[],
        )

    app.dependency_overrides[require_admin] = _fake_admin
    try:
        listed = client.get("/api/v1/admin/ai/providers")
        assert listed.status_code == 200
        body = listed.json()
        assert body["count"] >= 1
        assert any(p["id"] == "mock" for p in body["providers"])

        health = client.get("/api/v1/admin/ai/providers/health")
        assert health.status_code == 200

        one = client.get("/api/v1/admin/ai/providers/mock")
        assert one.status_code == 200

        tested = client.post(
            "/api/v1/admin/ai/providers/test",
            json={"provider_id": "mock", "prompt": "BUY"},
        )
        assert tested.status_code == 200
        assert tested.json()["response"]["ok"] is True

        denied = TestClient(app)
        # override 유지 중이라 별도 클라이언트로 401 확인은 skip
    finally:
        app.dependency_overrides.clear()

    # override 해제 후 미인증
    denied = client.get("/api/v1/admin/ai/providers")
    assert denied.status_code in {401, 403}


@pytest.mark.asyncio
async def test_telegram_providers_commands() -> None:
    from unittest.mock import AsyncMock, MagicMock, patch

    from stock_platform.notification.telegram_commands import TelegramCommandHandler

    session = MagicMock()
    handler = TelegramCommandHandler(session)
    with patch.object(handler, "_is_allowed_chat", return_value=True), patch.object(
        handler, "_audit"
    ), patch.object(
        handler._status,
        "build_providers_text",
        return_value="PROVIDERS_OK",
    ), patch.object(
        handler._status,
        "build_provider_health_text",
        new=AsyncMock(return_value="HEALTH_OK"),
    ):
        listed = await handler.handle(chat_id="1", text="/providers")
        health = await handler.handle(chat_id="1", text="/provider_health")
    assert listed.ok and "PROVIDERS_OK" in listed.reply_text
    assert health.ok and "HEALTH_OK" in health.reply_text


def test_dto_to_dict() -> None:
    from stock_platform.ai.providers.dto import AIResponse, TokenUsage

    response = AIResponse(
        provider_id="mock",
        model="mock-v1",
        content="HOLD",
        usage=TokenUsage(1, 2, 3),
    )
    data = response.to_dict()
    assert data["ok"] is True
    assert data["usage"]["total_tokens"] == 3
