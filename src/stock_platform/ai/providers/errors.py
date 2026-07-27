"""STEP 11-1 — Provider 공통 오류."""

from __future__ import annotations


class AIProviderError(Exception):
    """Provider 공통 예외."""

    def __init__(
        self,
        message: str,
        *,
        code: str = "PROVIDER_ERROR",
        provider_id: str | None = None,
        retryable: bool = False,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.provider_id = provider_id
        self.retryable = retryable


class ProviderNotConfiguredError(AIProviderError):
    def __init__(self, provider_id: str, message: str | None = None) -> None:
        super().__init__(
            message or f"Provider '{provider_id}' is not configured",
            code="NOT_CONFIGURED",
            provider_id=provider_id,
            retryable=False,
        )


class ProviderTimeoutError(AIProviderError):
    def __init__(self, provider_id: str, message: str | None = None) -> None:
        super().__init__(
            message or f"Provider '{provider_id}' timed out",
            code="TIMEOUT",
            provider_id=provider_id,
            retryable=True,
        )


class ProviderCircuitOpenError(AIProviderError):
    def __init__(self, provider_id: str) -> None:
        super().__init__(
            f"Circuit open for provider '{provider_id}'",
            code="CIRCUIT_OPEN",
            provider_id=provider_id,
            retryable=False,
        )


class ProviderCapabilityError(AIProviderError):
    def __init__(self, provider_id: str, capability: str) -> None:
        super().__init__(
            f"Provider '{provider_id}' lacks capability '{capability}'",
            code="CAPABILITY_NOT_SUPPORTED",
            provider_id=provider_id,
            retryable=False,
        )
        self.capability = capability


class ProviderDisabledError(AIProviderError):
    def __init__(self, provider_id: str) -> None:
        super().__init__(
            f"Provider '{provider_id}' is disabled",
            code="DISABLED",
            provider_id=provider_id,
            retryable=False,
        )


class ProviderSafetyBlockedError(AIProviderError):
    def __init__(self, provider_id: str, message: str | None = None) -> None:
        super().__init__(
            message or "Response blocked by safety policy",
            code="SAFETY_BLOCKED",
            provider_id=provider_id,
            retryable=False,
        )
