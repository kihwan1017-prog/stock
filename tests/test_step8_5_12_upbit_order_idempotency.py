"""STEP 8-5-12 — Upbit Identifier / Ambiguous Resolver tests."""

from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from stock_platform.broker.upbit.ambiguous_constants import (
    RemoteLookupStatus,
)
from stock_platform.broker.upbit.client_order_identifier import (
    UPBIT_IDENTIFIER_MAX_LEN,
    UpbitClientOrderIdentifierFactory,
)
from stock_platform.order.models import OrderStatus
from stock_platform.order.state_machine import OrderStateMachine
from tests.migration_helpers import (
    alembic_current_head,
    assert_revision_exists,
)


def test_step8_5_12_revision_head() -> None:
    assert_revision_exists("a4b5c6d7e8f9")
    # STEP 8-5-14 가 이후 head 이므로 존재 여부만 검증 (정확한 head 비교는
    # test_step8_5_14 에서 수행).
    alembic_current_head()


def test_identifier_stable_and_unique() -> None:
    a = UpbitClientOrderIdentifierFactory.build(
        broker_code="UPBIT",
        user_broker_account_id=12,
        local_order_id=100,
        submission_generation=1,
    )
    b = UpbitClientOrderIdentifierFactory.build(
        broker_code="UPBIT",
        user_broker_account_id=12,
        local_order_id=100,
        submission_generation=1,
    )
    c = UpbitClientOrderIdentifierFactory.build(
        broker_code="UPBIT",
        user_broker_account_id=12,
        local_order_id=100,
        submission_generation=2,
    )
    d = UpbitClientOrderIdentifierFactory.build(
        broker_code="UPBIT",
        user_broker_account_id=13,
        local_order_id=100,
        submission_generation=1,
    )
    assert a == b
    assert a != c
    assert a != d
    assert a.startswith("spu-")
    assert len(a) == UPBIT_IDENTIFIER_MAX_LEN
    UpbitClientOrderIdentifierFactory.validate(a)


def test_identifier_no_sensitive_material() -> None:
    value = UpbitClientOrderIdentifierFactory.build(
        broker_code="UPBIT",
        user_broker_account_id=99,
        local_order_id=1,
        submission_generation=1,
    )
    assert "@" not in value
    assert "secret" not in value.lower()
    assert "email" not in value.lower()


def test_fingerprint_stable() -> None:
    fp1 = UpbitClientOrderIdentifierFactory.order_fingerprint(
        user_broker_account_id=1,
        strategy_id="S1",
        signal_id="sig-1",
        market="KRW-BTC",
        side="BUY",
        order_type="LIMIT",
        price="1000.0",
        volume="0.1",
        generation=1,
    )
    fp2 = UpbitClientOrderIdentifierFactory.order_fingerprint(
        user_broker_account_id=1,
        strategy_id="S1",
        signal_id="sig-1",
        market="KRW-BTC",
        side="BUY",
        order_type="LIMIT",
        price="1000.0",
        volume="0.1",
        generation=1,
    )
    assert fp1 == fp2
    assert len(fp1) == 64


def test_ambiguous_state_transitions() -> None:
    assert OrderStateMachine.can_transition(
        OrderStatus.PENDING, OrderStatus.SUBMITTING
    )
    assert OrderStateMachine.can_transition(
        OrderStatus.SUBMITTING, OrderStatus.AMBIGUOUS_SUBMISSION
    )
    assert OrderStateMachine.can_transition(
        OrderStatus.AMBIGUOUS_SUBMISSION,
        OrderStatus.REMOTE_LOOKUP_PENDING,
    )
    assert OrderStateMachine.can_transition(
        OrderStatus.REMOTE_LOOKUP_PENDING, OrderStatus.ACCEPTED
    )
    assert OrderStateMachine.can_transition(
        OrderStatus.REMOTE_LOOKUP_PENDING,
        OrderStatus.MANUAL_REVIEW_REQUIRED,
    )
    assert not OrderStateMachine.can_transition(
        OrderStatus.FILLED, OrderStatus.AMBIGUOUS_SUBMISSION
    )


def test_mapper_prefers_upbit_identifier() -> None:
    from decimal import Decimal

    from stock_platform.broker.models import (
        BrokerOrderRequest,
        BrokerOrderSide,
        BrokerOrderType,
    )
    from stock_platform.broker.upbit.order_mapper import UpbitOrderMapper

    req = BrokerOrderRequest(
        client_order_id="ORD-LOCAL-1234567890",
        exchange_code="UPBIT",
        symbol="BTC",
        side=BrokerOrderSide.BUY,
        order_type=BrokerOrderType.LIMIT,
        quantity=Decimal("0.01"),
        price=Decimal("1000000"),
        upbit_client_identifier="spu-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    )
    body = UpbitOrderMapper.body(req)
    assert body["identifier"] == (
        "spu-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    )


def test_get_order_accepts_identifier(monkeypatch) -> None:
    from stock_platform.broker.upbit.order_client import (
        UpbitOrderRestClient,
    )

    client = UpbitOrderRestClient.__new__(UpbitOrderRestClient)
    captured = {}

    def _request(method, endpoint, *, params=None, **kwargs):
        captured["method"] = method
        captured["endpoint"] = endpoint
        captured["params"] = params
        return {"uuid": "u-1", "identifier": params.get("identifier")}

    client._request = _request  # type: ignore[method-assign]
    out = UpbitOrderRestClient.get_order(
        client, identifier="spu-test"
    )
    assert captured["params"]["identifier"] == "spu-test"
    assert out["uuid"] == "u-1"


def test_adapter_ambiguous_not_rejected(monkeypatch) -> None:
    from stock_platform.broker.models import (
        BrokerOrderRequest,
        BrokerOrderSide,
        BrokerOrderStatus,
        BrokerOrderType,
    )
    from stock_platform.broker.upbit.adapter import UpbitBrokerAdapter
    from stock_platform.broker.upbit.exceptions import (
        UpbitAmbiguousOrderResultError,
    )
    from decimal import Decimal

    settings = SimpleNamespace(
        upbit_use_mock=False,
        global_live_order_enabled=True,
        upbit_live_order_enabled=True,
        upbit_allowed_market_set=lambda: set(),
    )
    adapter = UpbitBrokerAdapter(settings=settings)  # type: ignore[arg-type]
    adapter._assert_order_allowed = lambda: None  # type: ignore[method-assign]
    adapter._assert_market_allowed = lambda r: None  # type: ignore[method-assign]

    def _boom(_body):
        raise UpbitAmbiguousOrderResultError("timeout")

    adapter._client = SimpleNamespace(create_order=_boom)  # type: ignore[assignment]
    monkeypatch.setattr(
        "stock_platform.broker.upbit.adapter.require_user_broker_context_for_live",
        lambda r: None,
    )
    monkeypatch.setattr(
        "stock_platform.broker.upbit.adapter.UpbitOrderMapper.body",
        lambda request: {
            "market": "KRW-BTC",
            "side": "bid",
            "ord_type": "limit",
            "volume": "0.01",
            "price": "1000000",
            "identifier": "spu-bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
        },
    )
    req = BrokerOrderRequest(
        client_order_id="ORD-1",
        exchange_code="UPBIT",
        symbol="BTC",
        side=BrokerOrderSide.BUY,
        order_type=BrokerOrderType.LIMIT,
        quantity=Decimal("0.01"),
        price=Decimal("1000000"),
        user_broker_account_id=1,
        upbit_client_identifier="spu-bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
    )
    result = adapter.submit_order(req)
    assert result.accepted is False
    assert result.status == BrokerOrderStatus.AMBIGUOUS
    assert result.reject_code == "AMBIGUOUS_ORDER_RESULT"


def test_resolver_match_links_uuid() -> None:
    from stock_platform.broker.upbit.ambiguous_resolver import (
        UpbitAmbiguousOrderResolver,
    )

    order = SimpleNamespace(
        order_id=7,
        broker_code="UPBIT",
        client_order_identifier="spu-cccccccccccccccccccccccccccccccc",
        broker_order_id=None,
        side_code="BUY",
        symbol="BTC",
        order_quantity=__import__("decimal").Decimal("0.01"),
        order_price=__import__("decimal").Decimal("100"),
        status_code=OrderStatus.REMOTE_LOOKUP_PENDING.value,
        remote_lookup_status=None,
        remote_lookup_attempt_count=1,
        next_remote_lookup_at=None,
        ambiguous_since=datetime.now(timezone.utc),
        user_broker_account_id=1,
        submission_attempt_count=1,
    )
    session = MagicMock()
    repo = MagicMock()
    repo.get_by_broker_order_id.return_value = None
    resolver = UpbitAmbiguousOrderResolver(session)
    resolver._repo = repo
    resolver._record_attempt = lambda *a, **k: None  # type: ignore[method-assign]
    resolver._audit = lambda *a, **k: None  # type: ignore[method-assign]

    out = resolver._match_and_link(
        order,
        payload={
            "uuid": "remote-uuid-1",
            "identifier": "spu-cccccccccccccccccccccccccccccccc",
            "market": "KRW-BTC",
            "side": "bid",
            "volume": "0.01",
        },
        actor="test",
    )
    assert out["status"] == RemoteLookupStatus.FOUND_MATCHED.value
    assert order.broker_order_id == "remote-uuid-1"
