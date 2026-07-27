from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from stock_platform.ai.ollama_client import OllamaError
from stock_platform.api.exception_handlers import register_exception_handlers
from stock_platform.broker.exceptions import BrokerAuthenticationError
from stock_platform.broker.kiwoom.market.exceptions import KiwoomRequestError
from stock_platform.broker.upbit.exceptions import UpbitRateLimitError
from stock_platform.common.error_catalog import (
    ERROR_CATALOG,
    resolve_error_code,
)
from stock_platform.common.exceptions import (
    ExternalApiError,
    NotFoundError,
    PermissionDeniedError,
    sanitize_error_message,
)
from stock_platform.disclosure.dart_client import DartError
from stock_platform.news.naver_client import NaverNewsError


def _client() -> TestClient:
    app = FastAPI()
    register_exception_handlers(app)

    @app.get("/not-found")
    def raise_not_found() -> None:
        raise NotFoundError(
            "resource not found",
            detail={"resource": "order", "id": "1"},
        )

    @app.get("/external")
    def raise_external() -> None:
        raise ExternalApiError(
            "token=secret-value account=81305419 failed"
        )

    @app.get("/kiwoom")
    def raise_kiwoom() -> None:
        raise KiwoomRequestError("Kiwoom API failed: secret=abc")

    @app.get("/upbit")
    def raise_upbit() -> None:
        raise UpbitRateLimitError("rate limited")

    @app.get("/dart")
    def raise_dart() -> None:
        raise DartError("DART failed")

    @app.get("/ollama")
    def raise_ollama() -> None:
        raise OllamaError("Ollama unavailable")

    @app.get("/naver")
    def raise_naver() -> None:
        raise NaverNewsError("Naver failed token=xyz")

    @app.get("/broker")
    def raise_broker() -> None:
        raise BrokerAuthenticationError("auth failed")

    @app.get("/forbidden-domain")
    def raise_forbidden() -> None:
        raise PermissionDeniedError("no access")

    return TestClient(app, raise_server_exceptions=False)


def test_error_catalog_contains_external_codes() -> None:
    for code in (
        "EXTERNAL_API_ERROR",
        "BROKER_ERROR",
        "KIWOOM_API_ERROR",
        "UPBIT_API_ERROR",
        "DART_API_ERROR",
        "OLLAMA_API_ERROR",
        "NAVER_API_ERROR",
        "PERMISSION_DENIED",
    ):
        assert code in ERROR_CATALOG
        assert ERROR_CATALOG[code]["http"]


def test_resolve_error_code_fallback() -> None:
    assert resolve_error_code("KIWOOM_API_ERROR") == "KIWOOM_API_ERROR"
    assert resolve_error_code("UNKNOWN_X") == "DOMAIN_ERROR"


def test_domain_error_response_format() -> None:
    response = _client().get("/not-found")

    assert response.status_code == 404
    body = response.json()
    assert body["code"] == "NOT_FOUND"
    assert body["message"] == "resource not found"
    assert body["detail"] == {"resource": "order", "id": "1"}
    assert "request_id" in body
    assert body["ok"] is False
    assert body["error"]["code"] == "NOT_FOUND"


def test_external_api_error_sanitizes_secrets() -> None:
    response = _client().get("/external")

    assert response.status_code == 502
    body = response.json()
    assert body["code"] == "EXTERNAL_API_ERROR"
    assert "secret" not in body["message"].lower()
    assert "81305419" not in body["message"]
    assert "[redacted]" in body["message"]


def test_kiwoom_error_maps_to_502() -> None:
    response = _client().get("/kiwoom")
    assert response.status_code == 502
    body = response.json()
    assert body["code"] == "KIWOOM_API_ERROR"
    assert "secret" not in body["message"].lower()


def test_upbit_error_maps_to_502() -> None:
    response = _client().get("/upbit")
    assert response.status_code == 502
    assert response.json()["code"] == "UPBIT_API_ERROR"


def test_dart_error_maps_to_502() -> None:
    response = _client().get("/dart")
    assert response.status_code == 502
    assert response.json()["code"] == "DART_API_ERROR"


def test_ollama_error_maps_to_502() -> None:
    response = _client().get("/ollama")
    assert response.status_code == 502
    assert response.json()["code"] == "OLLAMA_API_ERROR"


def test_naver_error_maps_to_502() -> None:
    response = _client().get("/naver")
    assert response.status_code == 502
    body = response.json()
    assert body["code"] == "NAVER_API_ERROR"
    assert "xyz" not in body["message"] or "[redacted]" in body["message"]


def test_broker_error_maps_to_502() -> None:
    response = _client().get("/broker")
    assert response.status_code == 502
    assert response.json()["code"] == "BROKER_ERROR"


def test_permission_denied_maps_to_403() -> None:
    response = _client().get("/forbidden-domain")
    assert response.status_code == 403
    assert response.json()["code"] == "PERMISSION_DENIED"


def test_sanitize_error_message() -> None:
    text = sanitize_error_message(
        "Authorization Bearer abc token=xyz account 1234567890"
    )
    assert "Bearer" not in text or "[redacted]" in text
    assert "1234567890" not in text
