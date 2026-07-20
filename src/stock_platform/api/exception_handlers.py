from __future__ import annotations

import logging
import uuid

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from stock_platform.ai.ollama_client import OllamaError
from stock_platform.broker.exceptions import BrokerError
from stock_platform.brokers.kiwoom.exceptions import KiwoomError
from stock_platform.brokers.upbit.exceptions import UpbitError
from stock_platform.common.exceptions import (
    DomainError,
    sanitize_error_message,
)
from stock_platform.common.settings import get_settings
from stock_platform.disclosure.dart_client import DartError
from stock_platform.news.naver_client import NaverNewsError


logger = logging.getLogger(__name__)


def _request_id(request: Request) -> str:
    return request.headers.get(
        "X-Request-ID",
        str(uuid.uuid4()),
    )


def _error_response(
    *,
    request: Request,
    status_code: int,
    code: str,
    message: str,
    detail: dict | list | str | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "code": code,
            "message": sanitize_error_message(message),
            "detail": detail,
            "request_id": _request_id(request),
        },
    )


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(DomainError)
    async def handle_domain_error(
        request: Request,
        exc: DomainError,
    ) -> JSONResponse:
        return _error_response(
            request=request,
            status_code=exc.status_code,
            code=exc.code,
            message=exc.message,
            detail=exc.detail,
        )

    @app.exception_handler(BrokerError)
    async def handle_broker_error(
        request: Request,
        exc: BrokerError,
    ) -> JSONResponse:
        return _error_response(
            request=request,
            status_code=502,
            code="BROKER_ERROR",
            message=str(exc),
        )

    @app.exception_handler(KiwoomError)
    async def handle_kiwoom_error(
        request: Request,
        exc: KiwoomError,
    ) -> JSONResponse:
        return _error_response(
            request=request,
            status_code=502,
            code="KIWOOM_API_ERROR",
            message=str(exc),
        )

    @app.exception_handler(UpbitError)
    async def handle_upbit_error(
        request: Request,
        exc: UpbitError,
    ) -> JSONResponse:
        return _error_response(
            request=request,
            status_code=502,
            code="UPBIT_API_ERROR",
            message=str(exc),
        )

    @app.exception_handler(DartError)
    async def handle_dart_error(
        request: Request,
        exc: DartError,
    ) -> JSONResponse:
        return _error_response(
            request=request,
            status_code=502,
            code="DART_API_ERROR",
            message=str(exc),
        )

    @app.exception_handler(OllamaError)
    async def handle_ollama_error(
        request: Request,
        exc: OllamaError,
    ) -> JSONResponse:
        return _error_response(
            request=request,
            status_code=502,
            code="OLLAMA_API_ERROR",
            message=str(exc),
        )

    @app.exception_handler(NaverNewsError)
    async def handle_naver_error(
        request: Request,
        exc: NaverNewsError,
    ) -> JSONResponse:
        return _error_response(
            request=request,
            status_code=502,
            code="NAVER_API_ERROR",
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
            message="Request validation failed",
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
            message = "HTTP error"
            body_detail = detail  # type: ignore[assignment]
        return _error_response(
            request=request,
            status_code=exc.status_code,
            code=f"HTTP_{exc.status_code}",
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
        message = "Internal server error"
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
