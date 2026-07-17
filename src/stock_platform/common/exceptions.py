from __future__ import annotations

import re


class DomainError(Exception):
    """도메인 규칙 위반 및 API 매핑용 공통 예외."""

    code: str = "DOMAIN_ERROR"
    status_code: int = 400

    def __init__(
        self,
        message: str,
        *,
        detail: dict | list | str | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail


class ValidationError(DomainError):
    code = "VALIDATION_ERROR"
    status_code = 422


class NotFoundError(DomainError):
    code = "NOT_FOUND"
    status_code = 404


class ConflictError(DomainError):
    code = "CONFLICT"
    status_code = 409


class ExternalApiError(DomainError):
    """외부 API(키움/업비트/DART/Ollama 등) 오류."""

    code = "EXTERNAL_API_ERROR"
    status_code = 502


class PermissionDeniedError(DomainError):
    code = "PERMISSION_DENIED"
    status_code = 403


_SENSITIVE_PATTERNS = (
    re.compile(
        r"(?i)(password|secret|token|api[_-]?key|"
        r"authorization|bearer|app[_-]?key|secret[_-]?key)"
    ),
    # 계좌번호·긴 숫자 식별자
    re.compile(r"\b\d{6,}\b"),
)


def sanitize_error_message(message: str) -> str:
    """외부 API/설정 오류 메시지에서 민감 정보를 제거한다."""

    sanitized = message
    for pattern in _SENSITIVE_PATTERNS:
        sanitized = pattern.sub("[redacted]", sanitized)
    return sanitized
