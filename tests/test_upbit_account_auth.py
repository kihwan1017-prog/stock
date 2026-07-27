"""업비트 JWT / QueryHash / 잔고 매핑 단위 테스트 (STEP2)."""

from __future__ import annotations

import hashlib
from decimal import Decimal
from urllib.parse import urlencode

import jwt
import pytest

from stock_platform.broker.upbit.account_mapper import UpbitAccountMapper
from stock_platform.broker.upbit.auth import (
    build_jwt_payload,
    build_query_hash,
    encode_authorization_token,
)
from stock_platform.broker.upbit.private_client import (
    MOCK_ACCOUNTS,
    UpbitPrivateClient,
)
from stock_platform.common.settings import Settings


def test_build_query_hash_matches_sha512() -> None:
    params = {"market": "KRW-BTC", "side": "bid"}
    expected = hashlib.sha512(
        urlencode(
            [(str(k), str(v)) for k, v in params.items()],
            doseq=True,
        ).encode("utf-8")
    ).hexdigest()
    digest, alg = build_query_hash(params)
    assert alg == "SHA512"
    assert digest == expected


def test_build_query_hash_empty() -> None:
    assert build_query_hash(None) == (None, None)
    assert build_query_hash({}) == (None, None)


def test_encode_jwt_contains_access_key_and_nonce() -> None:
    token = encode_authorization_token(
        access_key="access-demo",
        secret_key="secret-demo",
    )
    decoded = jwt.decode(
        token,
        "secret-demo",
        algorithms=["HS256"],
    )
    assert decoded["access_key"] == "access-demo"
    assert "nonce" in decoded
    assert "query_hash" not in decoded


def test_encode_jwt_with_query_hash() -> None:
    params = {"uuid": "order-1"}
    token = encode_authorization_token(
        access_key="access-demo",
        secret_key="secret-demo",
        params=params,
    )
    decoded = jwt.decode(
        token,
        "secret-demo",
        algorithms=["HS256"],
    )
    digest, _ = build_query_hash(params)
    assert decoded["query_hash"] == digest
    assert decoded["query_hash_alg"] == "SHA512"


def test_build_jwt_payload_requires_access_key() -> None:
    with pytest.raises(ValueError, match="access_key"):
        build_jwt_payload(access_key="  ")


def test_upbit_account_mapper_krw_and_positions() -> None:
    result = UpbitAccountMapper.map(
        account_number="MAIN",
        accounts=[
            {
                "currency": "KRW",
                "balance": "9000000",
                "locked": "1000000",
                "avg_buy_price": "0",
                "unit_currency": "KRW",
            },
            {
                "currency": "BTC",
                "balance": "0.1",
                "locked": "0",
                "avg_buy_price": "50000000",
                "unit_currency": "KRW",
            },
        ],
        tickers_by_market={
            "KRW-BTC": {"market": "KRW-BTC", "trade_price": "55000000"},
        },
    )
    assert result.broker_code == "UPBIT"
    assert result.account_number == "MAIN"
    assert result.deposit_amount == Decimal("10000000")
    assert result.available_order_amount == Decimal("9000000")
    assert len(result.positions) == 1
    pos = result.positions[0]
    assert pos.symbol == "KRW-BTC"
    assert pos.quantity == Decimal("0.1")
    assert pos.current_price == Decimal("55000000")
    assert pos.evaluation_amount == Decimal("5500000.00000000")


def test_upbit_account_mapper_skips_zero_balance() -> None:
    result = UpbitAccountMapper.map(
        account_number="MAIN",
        accounts=[
            {
                "currency": "ETH",
                "balance": "0",
                "locked": "0",
                "avg_buy_price": "1",
                "unit_currency": "KRW",
            },
        ],
    )
    assert result.positions == []


@pytest.mark.asyncio
async def test_private_client_mock_connection() -> None:
    settings = Settings(
        db_host="localhost",
        db_name="stock_platform",
        db_user="stock_app",
        db_password="test",
        upbit_use_mock=True,
        upbit_access_key="",
        upbit_secret_key="",
        upbit_account_ref="MAIN",
    )
    client = UpbitPrivateClient(settings=settings)
    status = await client.test_connection()
    assert status["ok"] is True
    assert status["mode"] == "mock"
    assert status["currency_count"] == len(MOCK_ACCOUNTS)
    accounts = await client.list_accounts()
    assert accounts[0]["currency"] == "KRW"


def test_validate_upbit_credentials_skipped_in_mock() -> None:
    settings = Settings(
        db_host="localhost",
        db_name="stock_platform",
        db_user="stock_app",
        db_password="test",
        upbit_use_mock=True,
        upbit_access_key="",
        upbit_secret_key="",
    )
    settings.validate_upbit_credentials()


def test_validate_upbit_credentials_requires_keys() -> None:
    settings = Settings(
        db_host="localhost",
        db_name="stock_platform",
        db_user="stock_app",
        db_password="test",
        upbit_use_mock=False,
        upbit_access_key="",
        upbit_secret_key="",
    )
    with pytest.raises(ValueError, match="UPBIT_ACCESS_KEY"):
        settings.validate_upbit_credentials()


def test_live_order_and_mock_mutually_exclusive() -> None:
    settings = Settings(
        db_host="localhost",
        db_name="stock_platform",
        db_user="stock_app",
        db_password="test",
        upbit_use_mock=True,
        upbit_live_order_enabled=True,
        jwt_secret="x" * 32,
        admin_api_key="test-admin-key",
        cors_allow_origins="http://localhost:3000",
        app_env="development",
    )
    with pytest.raises(ValueError, match="UPBIT_LIVE_ORDER_ENABLED"):
        settings.validate_startup()
