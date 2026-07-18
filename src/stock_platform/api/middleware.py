from __future__ import annotations

import uuid

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


class RequestContextMiddleware(BaseHTTPMiddleware):
    """request_id를 헤더/로그 컨텍스트에 바인딩한다."""

    async def dispatch(
        self,
        request: Request,
        call_next,
    ) -> Response:
        request_id = (
            request.headers.get("X-Request-ID")
            or str(uuid.uuid4())
        )
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            request_id=request_id,
            path=str(request.url.path),
            method=request.method,
        )
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        return response
