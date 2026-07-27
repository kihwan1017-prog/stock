"""STEP 11-2 — Endpoint SSRF 방지 정책."""

from __future__ import annotations

from urllib.parse import urlparse

from stock_platform.ai.providers.errors import AIProviderError


def validate_provider_endpoint(
    url: str,
    *,
    allow_localhost: bool = True,
    provider_id: str = "unknown",
) -> str:
    """허용 scheme·credential URL·비HTTP scheme 거부. 정규화된 URL 반환."""

    raw = (url or "").strip()
    if not raw:
        raise AIProviderError(
            "Endpoint is empty",
            code="INVALID_ENDPOINT",
            provider_id=provider_id,
            retryable=False,
        )
    parsed = urlparse(raw)
    scheme = (parsed.scheme or "").lower()
    if scheme not in {"http", "https"}:
        raise AIProviderError(
            f"Scheme '{scheme or 'none'}' not allowed",
            code="INVALID_ENDPOINT_SCHEME",
            provider_id=provider_id,
            retryable=False,
        )
    if parsed.username or parsed.password:
        raise AIProviderError(
            "Credential-embedded URL is rejected",
            code="ENDPOINT_CREDENTIAL_FORBIDDEN",
            provider_id=provider_id,
            retryable=False,
        )
    host = (parsed.hostname or "").lower()
    if not host:
        raise AIProviderError(
            "Endpoint host missing",
            code="INVALID_ENDPOINT",
            provider_id=provider_id,
            retryable=False,
        )
    local_hosts = {
        "localhost",
        "127.0.0.1",
        "::1",
        "0.0.0.0",
    }
    if host in local_hosts and not allow_localhost:
        raise AIProviderError(
            "Localhost endpoint not allowed by policy",
            code="ENDPOINT_LOCALHOST_FORBIDDEN",
            provider_id=provider_id,
            retryable=False,
        )
    return raw.rstrip("/")


def mask_endpoint(url: str | None) -> str:
    if not url:
        return ""
    parsed = urlparse(url)
    host = parsed.hostname or ""
    path = parsed.path or ""
    if len(path) > 24:
        path = path[:24] + "…"
    return f"{parsed.scheme}://{host}{path}"
