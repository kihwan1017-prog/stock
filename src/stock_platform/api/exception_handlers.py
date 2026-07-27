from __future__ import annotations

import logging
import uuid

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from stock_platform.ai.ollama_client import OllamaError
from stock_platform.broker.exceptions import BrokerError
from stock_platform.broker.kiwoom.market.exceptions import KiwoomError
from stock_platform.broker.upbit.exceptions import UpbitError
from stock_platform.common.error_catalog import (
    ERROR_CATALOG,
    error_envelope,
    resolve_error_code,
)
from stock_platform.common.exceptions import (
    DomainError,
    sanitize_error_message,
)
from stock_platform.common.settings import get_settings
from stock_platform.disclosure.dart_client import DartError
from stock_platform.news.naver_client import NaverNewsError


logger = logging.getLogger(__name__)

# HTTP status → 카탈로그 코드 (HTTP_* 남발 방지)
_STATUS_TO_CODE: dict[int, str] = {
    400: "DOMAIN_ERROR",
    401: "UNAUTHORIZED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    409: "CONFLICT",
    422: "VALIDATION_ERROR",
    429: "RATE_LIMITED",
    500: "INTERNAL_ERROR",
    502: "EXTERNAL_API_ERROR",
}


def _request_id(request: Request) -> str:
    return request.headers.get(
        "X-Request-ID",
        str(uuid.uuid4()),
    )


def _code_for_status(status_code: int, fallback: str | None = None) -> str:
    if status_code in _STATUS_TO_CODE:
        return _STATUS_TO_CODE[status_code]
    if fallback and fallback in ERROR_CATALOG:
        return fallback
    return f"HTTP_{status_code}"


def _log_external_failure(
    *,
    request: Request,
    code: str,
    exc: BaseException,
) -> None:
    """외부/브로커 오류는 서버 로그에만 원문(가능하면)을 남긴다."""

    logger.warning(
        "external_api_error code=%s path=%s exc_type=%s message=%s",
        code,
        request.url.path,
        type(exc).__name__,
        sanitize_error_message(str(exc)),
    )


def _error_response(
    *,
    request: Request,
    status_code: int,
    code: str,
    message: str,
    detail: dict | list | str | None = None,
) -> JSONResponse:
    safe_message = sanitize_error_message(message)
    safe_detail = detail
    if isinstance(detail, str):
        safe_detail = sanitize_error_message(detail)
    # Envelope + 레거시 top-level 필드 병행 (FE 호환)
    body = error_envelope(
        code=code,
        message=safe_message,
        request_id=_request_id(request),
        detail=safe_detail,
    )
    body["code"] = code
    body["message"] = safe_message
    body["detail"] = safe_detail
    return JSONResponse(status_code=status_code, content=body)


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(DomainError)
    async def handle_domain_error(
        request: Request,
        exc: DomainError,
    ) -> JSONResponse:
        code = resolve_error_code(exc.code, fallback="DOMAIN_ERROR")
        return _error_response(
            request=request,
            status_code=exc.status_code,
            code=code,
            message=exc.message,
            detail=exc.detail,
        )

    @app.exception_handler(BrokerError)
    async def handle_broker_error(
        request: Request,
        exc: BrokerError,
    ) -> JSONResponse:
        code = "BROKER_ERROR"
        _log_external_failure(request=request, code=code, exc=exc)
        return _error_response(
            request=request,
            status_code=502,
            code=code,
            message=str(exc),
        )

    @app.exception_handler(KiwoomError)
    async def handle_kiwoom_error(
        request: Request,
        exc: KiwoomError,
    ) -> JSONResponse:
        code = "KIWOOM_API_ERROR"
        _log_external_failure(request=request, code=code, exc=exc)
        return _error_response(
            request=request,
            status_code=502,
            code=code,
            message=str(exc),
        )

    @app.exception_handler(UpbitError)
    async def handle_upbit_error(
        request: Request,
        exc: UpbitError,
    ) -> JSONResponse:
        code = "UPBIT_API_ERROR"
        _log_external_failure(request=request, code=code, exc=exc)
        return _error_response(
            request=request,
            status_code=502,
            code=code,
            message=str(exc),
        )

    @app.exception_handler(DartError)
    async def handle_dart_error(
        request: Request,
        exc: DartError,
    ) -> JSONResponse:
        code = "DART_API_ERROR"
        _log_external_failure(request=request, code=code, exc=exc)
        return _error_response(
            request=request,
            status_code=502,
            code=code,
            message=str(exc),
        )

    @app.exception_handler(OllamaError)
    async def handle_ollama_error(
        request: Request,
        exc: OllamaError,
    ) -> JSONResponse:
        code = "OLLAMA_API_ERROR"
        _log_external_failure(request=request, code=code, exc=exc)
        return _error_response(
            request=request,
            status_code=502,
            code=code,
            message=str(exc),
        )

    @app.exception_handler(NaverNewsError)
    async def handle_naver_error(
        request: Request,
        exc: NaverNewsError,
    ) -> JSONResponse:
        code = "NAVER_API_ERROR"
        _log_external_failure(request=request, code=code, exc=exc)
        return _error_response(
            request=request,
            status_code=502,
            code=code,
            message=str(exc),
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        return _error_response(
            request=request,
            status_code=422,
            code="VALIDATION_ERROR",
            message=ERROR_CATALOG["VALIDATION_ERROR"]["message"],
            detail=exc.errors(),
        )

    @app.exception_handler(HTTPException)
    async def handle_http_exception(
        request: Request,
        exc: HTTPException,
    ) -> JSONResponse:
        detail = exc.detail
        if isinstance(detail, str):
            message = detail
            body_detail: dict | list | str | None = None
        else:
            message = ERROR_CATALOG.get(
                _code_for_status(exc.status_code),
                {},
            ).get("message", "HTTP error")
            body_detail = detail  # type: ignore[assignment]
        return _error_response(
            request=request,
            status_code=exc.status_code,
            code=_code_for_status(exc.status_code),
            message=message,
            detail=body_detail,
        )

    @app.exception_handler(Exception)
    async def handle_unhandled_exception(
        request: Request,
        exc: Exception,
    ) -> JSONResponse:
        try:
            from stock_platform.operation.exception_rate import (
                exception_rate_tracker,
            )

            exception_rate_tracker.record()
        except Exception:
            pass
        logger.exception(
            "unhandled_exception",
            extra={"path": str(request.url.path)},
        )
        message = ERROR_CATALOG["INTERNAL_ERROR"]["message"]
        detail: str | None = None
        if not get_settings().is_production_env:
            detail = sanitize_error_message(str(exc))
            message = sanitize_error_message(str(exc)) or message
        return _error_response(
            request=request,
            status_code=500,
            code="INTERNAL_ERROR",
            message=message,
            detail=detail,
        )
