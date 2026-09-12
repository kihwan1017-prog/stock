"""Kiwoom OAuth token client — redirect/gateway 오류 명시."""

from __future__ import annotations

from datetime import datetime, timezone

import httpx
import pytest

from stock_platform.broker.exceptions import BrokerAuthenticationError
from stock_platform.broker.kiwoom.config import KiwoomOrderConfig
from stock_platform.broker.kiwoom.token_client import KiwoomTokenClient


def _config(*, use_mock: bool = False) -> KiwoomOrderConfig:
    return KiwoomOrderConfig(
        base_url=(
            "https://mockapi.kiwoom.com"
            if use_mock
            else "https://api.kiwoom.com"
        ),
        app_key="app",
        secret_key="secret",
        use_mock=use_mock,
        live_order_enabled=False,
        timeout_seconds=5.0,
    )


def test_token_issue_success_does_not_follow_html() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/oauth2/token"
        assert request.headers.get("api-id") == "au10001"
        assert request.headers.get("content-type", "").startswith(
            "application/json"
        )
        return httpx.Response(
            200,
            json={
                "return_code": 0,
                "token": "tok-1",
                "token_type": "bearer",
                "expires_dt": "20991231235959",
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    token = KiwoomTokenClient(_config(), client=client).issue()
    assert token.token == "tok-1"
    assert token.expires_at > datetime.now(timezone.utc)


def test_token_issue_rejects_gateway_redirect() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            302,
            headers={"location": "http://api.kiwoom.com/start.html?x"},
            text="Found",
        )

    client = httpx.Client(
        transport=httpx.MockTransport(handler),
        follow_redirects=False,
    )
    with pytest.raises(BrokerAuthenticationError) as ei:
        KiwoomTokenClient(_config(use_mock=False), client=client).issue()
    msg = str(ei.value)
    assert "KIWOOM_OAUTH_GATEWAY_REDIRECT" in msg
    assert "start.html" in msg
