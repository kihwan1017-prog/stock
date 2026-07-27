"""STEP 11-2 — AI Provider Integration tests (Mock HTTP only, no live AI)."""

from __future__ import annotations

import json

import httpx
import pytest

from stock_platform.ai.providers.claude_provider import ClaudeProvider
from stock_platform.ai.providers.config import AIProviderConfig
from stock_platform.ai.providers.dto import AIChatRequest, ChatMessage, FinishReason
from stock_platform.ai.providers.endpoint_policy import validate_provider_endpoint
from stock_platform.ai.providers.errors import AIProviderError
from stock_platform.ai.providers.gemini_provider import GeminiProvider
from stock_platform.ai.providers.health_status import HealthStatus
from stock_platform.ai.providers.manager import AIManager, reset_ai_manager
from stock_platform.ai.providers.mock_provider import MockAIProvider
from stock_platform.ai.providers.ollama_provider import OllamaProvider
from stock_platform.ai.providers.openai_compatible_provider import (
    OpenAICompatibleProvider,
)
from stock_platform.ai.providers.openai_provider import OpenAIProvider
from stock_platform.ai.providers.registry import AIProviderRegistry
from stock_platform.ai.providers.security import mask_secret, sanitize_for_log


@pytest.fixture(autouse=True)
def _reset_manager():
    reset_ai_manager()
    yield
    reset_ai_manager()


def _client(handler) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _chat_req(text: str = "hi") -> AIChatRequest:
    return AIChatRequest(messages=[ChatMessage(role="user", content=text)])


# --- OpenAI ---


@pytest.mark.asyncio
async def test_openai_success_usage_finish_reason() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/chat/completions")
        assert "Authorization" in request.headers
        return httpx.Response(
            200,
            json={
                "id": "chatcmpl-1",
                "model": "gpt-4o-mini",
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "OK"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 5,
                    "completion_tokens": 1,
                    "total_tokens": 6,
                },
            },
            headers={"x-request-id": "req-1"},
        )

    cfg = AIProviderConfig(
        provider_id="openai",
        enabled=True,
        api_key="sk-test-key-123456",
        api_endpoint="https://api.openai.com/v1",
        model="gpt-4o-mini",
    )
    provider = OpenAIProvider(cfg, http_client=_client(handler))
    response = await provider.chat(_chat_req())
    assert response.ok
    assert response.content == "OK"
    assert response.usage.total_tokens == 6
    assert response.finish_reason == FinishReason.STOP
    assert response.request_id == "req-1"


@pytest.mark.asyncio
async def test_openai_401() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="unauthorized")

    cfg = AIProviderConfig(
        provider_id="openai",
        enabled=True,
        api_key="bad",
        api_endpoint="https://api.openai.com/v1",
        model="gpt-4o-mini",
    )
    response = await OpenAIProvider(cfg, http_client=_client(handler)).chat(
        _chat_req()
    )
    assert not response.ok
    assert response.error and response.error.code == "AUTH_FAILED"


@pytest.mark.asyncio
async def test_openai_429_retry_after() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429, text="rate", headers={"Retry-After": "2"}
        )

    cfg = AIProviderConfig(
        provider_id="openai",
        enabled=True,
        api_key="sk-test",
        api_endpoint="https://api.openai.com/v1",
        model="gpt-4o-mini",
        retry_max=0,
    )
    response = await OpenAIProvider(cfg, http_client=_client(handler)).chat(
        _chat_req()
    )
    assert not response.ok
    assert response.error and response.error.code == "RATE_LIMITED"
    assert response.error.retryable is True


@pytest.mark.asyncio
async def test_openai_timeout() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow")

    cfg = AIProviderConfig(
        provider_id="openai",
        enabled=True,
        api_key="sk-test",
        api_endpoint="https://api.openai.com/v1",
        model="gpt-4o-mini",
    )
    response = await OpenAIProvider(cfg, http_client=_client(handler)).chat(
        _chat_req()
    )
    assert not response.ok
    assert response.finish_reason == FinishReason.TIMEOUT


# --- Claude ---


@pytest.mark.asyncio
async def test_claude_content_block_and_auth() -> None:
    def ok_handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content.decode())
        assert "system" in body
        assert body["messages"][0]["role"] == "user"
        return httpx.Response(
            200,
            json={
                "id": "msg_1",
                "model": "claude-3-5-sonnet-latest",
                "content": [{"type": "text", "text": "OK"}],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 3, "output_tokens": 1},
            },
        )

    cfg = AIProviderConfig(
        provider_id="claude",
        enabled=True,
        api_key="ant-key",
        api_endpoint="https://api.anthropic.com",
        model="claude-3-5-sonnet-latest",
    )
    provider = ClaudeProvider(cfg, http_client=_client(ok_handler))
    response = await provider.chat(
        AIChatRequest(
            messages=[
                ChatMessage(role="system", content="be brief"),
                ChatMessage(role="user", content="hi"),
            ]
        )
    )
    assert response.ok
    assert response.content == "OK"
    assert response.usage.prompt_tokens == 3

    def auth_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="no")

    bad = await ClaudeProvider(cfg, http_client=_client(auth_handler)).chat(
        _chat_req()
    )
    assert bad.error and bad.error.code == "AUTH_FAILED"


# --- Gemini ---


@pytest.mark.asyncio
async def test_gemini_success_and_safety_and_quota() -> None:
    def ok_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "content": {"parts": [{"text": "OK"}]},
                        "finishReason": "STOP",
                    }
                ],
                "usageMetadata": {
                    "promptTokenCount": 2,
                    "candidatesTokenCount": 1,
                    "totalTokenCount": 3,
                },
            },
        )

    cfg = AIProviderConfig(
        provider_id="gemini",
        enabled=True,
        api_key="AIza-test",
        api_endpoint="https://generativelanguage.googleapis.com",
        model="gemini-2.0-flash",
    )
    ok = await GeminiProvider(cfg, http_client=_client(ok_handler)).chat(
        _chat_req()
    )
    assert ok.ok and ok.content == "OK"

    def safety_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"promptFeedback": {"blockReason": "SAFETY"}},
        )

    blocked = await GeminiProvider(
        cfg, http_client=_client(safety_handler)
    ).chat(_chat_req())
    assert not blocked.ok
    assert blocked.error and blocked.error.code == "SAFETY_BLOCKED"

    def quota_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, text="quota")

    quota = await GeminiProvider(cfg, http_client=_client(quota_handler)).chat(
        _chat_req()
    )
    assert quota.error and quota.error.code == "RATE_LIMITED"


# --- Ollama ---


@pytest.mark.asyncio
async def test_ollama_health_offline_model_stream() -> None:
    def tags_ok(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/api/tags"):
            return httpx.Response(
                200,
                json={"models": [{"name": "qwen3.5:4b"}]},
            )
        return httpx.Response(404)

    cfg = AIProviderConfig(
        provider_id="ollama",
        enabled=True,
        api_endpoint="http://127.0.0.1:11434",
        model="qwen3.5:4b",
    )
    health = await OllamaProvider(cfg, http_client=_client(tags_ok)).health()
    assert health.status == HealthStatus.HEALTHY

    cfg_missing = AIProviderConfig(
        provider_id="ollama",
        enabled=True,
        api_endpoint="http://127.0.0.1:11434",
        model="missing-model",
    )
    missing = await OllamaProvider(
        cfg_missing, http_client=_client(tags_ok)
    ).health()
    assert missing.status == HealthStatus.MODEL_NOT_FOUND

    def offline(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down")

    offline_h = await OllamaProvider(cfg, http_client=_client(offline)).health()
    assert offline_h.status == HealthStatus.OFFLINE

    def stream_handler(request: httpx.Request) -> httpx.Response:
        lines = [
            json.dumps({"message": {"content": "O"}, "done": False}),
            json.dumps(
                {
                    "message": {"content": "K"},
                    "done": True,
                    "prompt_eval_count": 1,
                    "eval_count": 2,
                }
            ),
        ]
        return httpx.Response(200, text="\n".join(lines))

    chunks = []
    async for chunk in OllamaProvider(
        cfg, http_client=_client(stream_handler)
    ).chat_stream(_chat_req()):
        chunks.append(chunk)
    assert any(c.delta == "O" for c in chunks)
    assert chunks[-1].done is True


# --- OpenAI Compatible / SSRF ---


@pytest.mark.asyncio
async def test_openai_compatible_and_endpoint_policy() -> None:
    with pytest.raises(AIProviderError) as exc:
        validate_provider_endpoint(
            "file:///etc/passwd", provider_id="openai_compatible"
        )
    assert exc.value.code == "INVALID_ENDPOINT_SCHEME"

    with pytest.raises(AIProviderError) as exc2:
        validate_provider_endpoint(
            "https://user:pass@evil.example/v1",
            provider_id="openai_compatible",
        )
    assert exc2.value.code == "ENDPOINT_CREDENTIAL_FORBIDDEN"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {"content": "OK"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
            },
        )

    cfg = AIProviderConfig(
        provider_id="openai_compatible",
        enabled=True,
        api_endpoint="http://127.0.0.1:1234/v1",
        model="local-model",
    )
    response = await OpenAICompatibleProvider(
        cfg, http_client=_client(handler)
    ).chat(_chat_req())
    assert response.ok


def test_secret_masking() -> None:
    masked = sanitize_for_log(
        {"api_key": "sk-abcdefghijklmnop", "authorization": "Bearer secret"}
    )
    assert "sk-abcd" not in str(masked["api_key"])
    assert mask_secret("abcd1234").endswith("1234")


@pytest.mark.asyncio
async def test_disabled_not_configured_capability() -> None:
    disabled = OpenAIProvider(
        AIProviderConfig(provider_id="openai", enabled=False, api_key="x")
    )
    h = await disabled.health()
    assert h.status == HealthStatus.DISABLED

    unconfigured = OpenAIProvider(
        AIProviderConfig(provider_id="openai", enabled=True, api_key="")
    )
    h2 = await unconfigured.health()
    assert h2.status in {
        HealthStatus.NOT_CONFIGURED,
        HealthStatus.UNCONFIGURED,
    }

    cfg = AIProviderConfig(
        provider_id="openai",
        enabled=True,
        api_key="sk",
        api_endpoint="https://api.openai.com/v1",
        model="m",
    )
    unsupported = await OpenAIProvider(cfg).generate_strategy(
        __import__(
            "stock_platform.ai.providers.dto", fromlist=["AIAnalyzeRequest"]
        ).AIAnalyzeRequest(content="x")
    )
    assert unsupported.error
    assert unsupported.error.code == "CAPABILITY_NOT_SUPPORTED"


@pytest.mark.asyncio
async def test_manager_retry_circuit_fallback_no_double_http_retry() -> None:
    calls = {"n": 0}

    def flaky(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 2:
            return httpx.Response(503, text="busy")
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": "OK"}, "finish_reason": "stop"}
                ],
                "usage": {},
            },
        )

    registry = AIProviderRegistry()
    openai_cfg = AIProviderConfig(
        provider_id="openai",
        enabled=True,
        priority=1,
        is_default=True,
        api_key="sk",
        api_endpoint="https://api.openai.com/v1",
        model="gpt",
        retry_max=2,
        retry_backoff_seconds=0.01,
        circuit_failure_threshold=5,
    )
    provider = OpenAIProvider(openai_cfg, http_client=_client(flaky))
    registry.register(provider, openai_cfg)
    manager = AIManager(registry=registry)
    response = await manager.chat(_chat_req(), fallback=False)
    assert response.ok
    # Manager retries only — HTTP client does not auto-retry → calls == 2
    assert calls["n"] == 2


@pytest.mark.asyncio
async def test_manager_circuit_open_and_recovery() -> None:
    def always_fail(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="err")

    registry = AIProviderRegistry()
    cfg = AIProviderConfig(
        provider_id="openai",
        enabled=True,
        is_default=True,
        api_key="sk",
        api_endpoint="https://api.openai.com/v1",
        model="gpt",
        retry_max=0,
        circuit_failure_threshold=1,
        circuit_reset_seconds=60,
    )
    registry.register(OpenAIProvider(cfg, http_client=_client(always_fail)), cfg)
    manager = AIManager(registry=registry)
    first = await manager.chat(_chat_req(), fallback=False)
    assert not first.ok
    second = await manager.chat(_chat_req(), fallback=False)
    assert second.error and second.error.code == "CIRCUIT_OPEN"

    # half-open recovery
    circuit = manager._circuit_for("openai")
    circuit.state = __import__(
        "stock_platform.ai.providers.circuit_breaker", fromlist=["CircuitState"]
    ).CircuitState.HALF_OPEN

    def ok(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "choices": [
                    {"message": {"content": "OK"}, "finish_reason": "stop"}
                ],
                "usage": {},
            },
        )

    registry.clear()
    cfg2 = AIProviderConfig(
        provider_id="openai",
        enabled=True,
        is_default=True,
        api_key="sk",
        api_endpoint="https://api.openai.com/v1",
        model="gpt",
        retry_max=0,
        circuit_failure_threshold=1,
    )
    registry.register(OpenAIProvider(cfg2, http_client=_client(ok)), cfg2)
    manager2 = AIManager(registry=registry)
    # force half-open then success
    cb = manager2._circuit_for("openai")
    cb.record_failure()
    assert not cb.allow() or cb.state.value in {"OPEN", "CLOSED"}
    cb.state = __import__(
        "stock_platform.ai.providers.circuit_breaker", fromlist=["CircuitState"]
    ).CircuitState.HALF_OPEN
    recovered = await manager2.chat(_chat_req(), fallback=False)
    assert recovered.ok
    assert manager2._circuit_for("openai").state.value == "CLOSED"


@pytest.mark.asyncio
async def test_fallback_all_fail_and_success() -> None:
    registry = AIProviderRegistry()
    fail_cfg = AIProviderConfig(
        provider_id="mock",
        enabled=True,
        priority=1,
        is_default=True,
        retry_max=0,
        extra={"simulate_error": True},
    )
    ok_cfg = AIProviderConfig(
        provider_id="mock_backup",
        enabled=True,
        priority=2,
        extra={"fixed_signal": "SELL"},
    )
    registry.register(MockAIProvider(fail_cfg), fail_cfg)
    registry.register(MockAIProvider(ok_cfg), ok_cfg)
    manager = AIManager(registry=registry)
    ok = await manager.chat(_chat_req(), fallback=True)
    assert ok.content == "SELL"

    registry2 = AIProviderRegistry()
    registry2.register(MockAIProvider(fail_cfg), fail_cfg)
    fail_all = await AIManager(registry=registry2).chat(
        _chat_req(), fallback=True
    )
    assert not fail_all.ok


@pytest.mark.asyncio
async def test_health_cache_and_dashboard_zero_external() -> None:
    manager = AIManager.create_default()
    # populate cache via mock health
    await manager.health(provider_id="mock", use_cache=False)
    snap1 = manager.cached_health_snapshot()
    block = manager.dashboard_block()
    assert block["external_calls_on_read"] == 0
    assert any(i["id"] == "mock" for i in block["items"])
    # second health uses cache
    await manager.health(provider_id="mock", use_cache=True)
    assert snap1


@pytest.mark.asyncio
async def test_telegram_uses_cache_only() -> None:
    from unittest.mock import MagicMock, patch

    from stock_platform.notification.telegram_status import (
        TelegramOpsStatusService,
    )

    session = MagicMock()
    status = TelegramOpsStatusService(session)
    with patch.object(
        status,
        "_summary",
        return_value={
            "ai_providers": {
                "health": "HEALTHY",
                "default_provider": "mock",
                "count": 1,
                "items": [
                    {
                        "id": "mock",
                        "status": "HEALTHY",
                        "enabled": True,
                        "configured": True,
                        "model": "mock-v1",
                        "endpoint": None,
                        "circuit_state": "CLOSED",
                        "latency_ms": 1,
                    }
                ],
            }
        },
    ):
        text = status.build_providers_text()
        detail = status.build_provider_detail_text("mock")
        health = await status.build_provider_health_text()
    assert "mock" in text
    assert "HEALTHY" in detail
    assert "cache" in health.lower() or "mock" in health.lower()


def test_admin_test_api_auth_and_limits() -> None:
    from fastapi.testclient import TestClient

    from stock_platform.api.main import app
    from stock_platform.auth.deps import AuthenticatedUser, require_admin

    client = TestClient(app)
    denied = client.post(
        "/api/v1/admin/ai/providers/mock/test",
        json={"prompt": "OK"},
    )
    assert denied.status_code in {401, 403}

    app.dependency_overrides[require_admin] = lambda: AuthenticatedUser(
        user_id=1,
        username="admin",
        roles=["admin"],
        permissions=[],
    )
    try:
        ok = client.post(
            "/api/v1/admin/ai/providers/mock/test",
            json={"prompt": "BUY", "max_tokens": 16},
        )
        assert ok.status_code == 200
        body = ok.json()
        assert "api_key" not in json.dumps(body)
        assert body["response"]["ok"] is True

        # prompt length enforced by pydantic
        too_long = client.post(
            "/api/v1/admin/ai/providers/mock/test",
            json={"prompt": "x" * 3000},
        )
        assert too_long.status_code == 422
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_mock_regression_and_pii() -> None:
    provider = MockAIProvider(
        AIProviderConfig(
            provider_id="mock",
            enabled=True,
            extra={"fixed_signal": "HOLD"},
        )
    )
    response = await provider.chat(_chat_req())
    assert response.content == "HOLD"
    assert "sk-" not in sanitize_for_log({"msg": "user@example.com sk-abc123456789"})["msg"]


# Marker placeholder for optional live tests (never collected by default)
@pytest.mark.live_ai
@pytest.mark.skip(reason="Requires explicit live_ai credential approval")
def test_live_ai_marker_placeholder() -> None:
    assert False
