from __future__ import annotations

import uuid

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from stock_platform.ai.ollama_client import OllamaError
from stock_platform.broker.exceptions import BrokerError
from stock_platform.brokers.kiwoom.exceptions import KiwoomError
from stock_platform.brokers.upbit.exceptions import UpbitError
from stock_platform.common.exceptions import (
    DomainError,
    sanitize_error_message,
)
from stock_platform.disclosure.dart_client import DartError
from stock_platform.news.naver_client import NaverNewsError


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
