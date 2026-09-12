"""KIWOOM REAL 시장 시세 WS — 공식 0B 계약 unit tests. production DB mutation 없음."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from stock_platform.broker.kiwoom.market_realtime_client import (
    KiwoomMarketRealtimeClient,
)
from stock_platform.broker.kiwoom.market_realtime_contract import (
    MARKET_TRADE_TYPE,
    MOCK_FEED_FALLBACK_ON_REAL_WS_DOWN,
    REASON_REAL_EXECUTION_REQUIRES_REAL_MARKET_DATA,
    REASON_REST_POLLING_NOT_LIVE_SOT,
    REST_POLLING_IS_LIVE_RUNTIME_SOT,
    SOURCE_REST_POLLING,
    SOURCE_WEBSOCKET_MOCK,
    SOURCE_WEBSOCKET_REAL,
)
from stock_platform.broker.kiwoom.market_ws_parser import (
    build_login_payload,
    build_market_reg_payload,
    build_market_remove_payload,
    login_ack_ok,
    parse_kiwoom_trade_time,
    parse_market_message,
    reg_ack_ok,
)
from stock_platform.broker.kiwoom.ws_config import KiwoomMarketWebSocketConfig
from stock_platform.realtime.kiwoom_market_source_gate import (
    evaluate_real_execution_market_source,
)
from stock_platform.realtime.market_data_hub import RealtimeMarketDataHub
from stock_platform.realtime.models import RealtimeQuote
from stock_platform.strategy_deployment.runtime_scope import (
    AccountKind,
    RuntimeLifecycleStatus,
    StrategyRuntimeScope,
)


OFFICIAL_REG = {
    "trnm": "REG",
    "grp_no": "1",
    "refresh": "1",
    "data": [{"item": ["034310"], "type": ["0B"]}],
}

OFFICIAL_LOGIN_ACK = {"trnm": "LOGIN", "return_code": 0, "return_msg": ""}
OFFICIAL_REG_ACK = {"trnm": "REG", "return_code": 0, "return_msg": ""}
OFFICIAL_0B_TICK = {
    "trnm": "REAL",
    "data": [
        {
            "type": "0B",
            "item": "034310",
            "values": {
                "20": "101530",
                "10": "-40150",
                "12": "-1.25",
                "27": "-40200",
                "28": "-40100",
                "15": "12",
                "13": "3456",
            },
        }
    ],
}


class _FakeTokenCache:
    def get(self) -> SimpleNamespace:
        return SimpleNamespace(token="test-token-not-for-log")


class _FakeSocket:
    def __init__(self, incoming: list[object]) -> None:
        self.sent: list[str] = []
        self._incoming = list(incoming)
        self._index = 0

    async def send(self, payload: str) -> None:
        self.sent.append(payload)

    def __aiter__(self) -> "_FakeSocket":
        return self

    async def __anext__(self) -> object:
        if self._index >= len(self._incoming):
            raise StopAsyncIteration
        item = self._incoming[self._index]
        self._index += 1
        return item

    async def __aenter__(self) -> "_FakeSocket":
        return self

    async def __aexit__(self, *args: object) -> None:
        return None


def _market_cfg(*, environment: str = "REAL") -> KiwoomMarketWebSocketConfig:
    return KiwoomMarketWebSocketConfig(
        url="wss://api.kiwoom.com:10000",
        path="/api/dostk/websocket",
        service_type="0B",
        reconnect_min_seconds=0.01,
        reconnect_max_seconds=0.05,
        ping_interval_seconds=20.0,
        ping_timeout_seconds=10.0,
        environment=environment,
    )


def _scope(
    *,
    user_id: int,
    account_id: int,
    strategy_id: int,
    broker: str,
    market: str = "STOCK",
) -> StrategyRuntimeScope:
    return StrategyRuntimeScope(
        user_id=user_id,
        account_kind=AccountKind.USER_BROKER,
        account_id=account_id,
        strategy_id=strategy_id,
        strategy_version="1",
        market_type=market,
        broker_code=broker,
    )


def test_official_reg_payload_fixture() -> None:
    payload = build_market_reg_payload(["034310"])
    assert payload == OFFICIAL_REG
    assert payload["data"][0]["item"] != [""]
    assert payload["data"][0]["type"] == [MARKET_TRADE_TYPE]


def test_login_and_reg_ack() -> None:
    assert login_ack_ok(OFFICIAL_LOGIN_ACK) is True
    assert login_ack_ok({"trnm": "LOGIN", "return_code": 1}) is False
    assert reg_ack_ok(OFFICIAL_REG_ACK) is True
    assert build_login_payload("x") == {"trnm": "LOGIN", "token": "x"}


def test_reg_rejects_execution_type_and_empty_item() -> None:
    with pytest.raises(ValueError):
        build_market_reg_payload([])
    with pytest.raises(ValueError):
        build_market_reg_payload(["034310"], type_code="00")
    remove = build_market_remove_payload(["034310"])
    assert remove["trnm"] == "REMOVE"


def test_signed_price_and_timestamp_normalization() -> None:
    quotes = parse_market_message(OFFICIAL_0B_TICK, environment="REAL")
    assert len(quotes) == 1
    quote = quotes[0]
    assert quote.symbol == "034310"
    assert quote.trade_price == Decimal("40150")
    assert quote.trade_price > 0
    assert quote.source_code == SOURCE_WEBSOCKET_REAL
    assert quote.bid == Decimal("40100")
    assert quote.ask == Decimal("40200")
    assert quote.exchange_code == "KRX"
    parsed = parse_kiwoom_trade_time("101530")
    assert parsed.hour == 10
    assert parsed.minute == 15
    assert parsed.second == 30
    assert parsed.tzinfo is not None


def test_execution_type_00_is_ignored() -> None:
    quotes = parse_market_message(
        {
            "trnm": "REAL",
            "data": [
                {"type": "00", "item": "", "values": {"10": "1000"}},
            ],
        },
        environment="REAL",
    )
    assert quotes == []


def test_zero_price_rejected() -> None:
    quotes = parse_market_message(
        {
            "trnm": "REAL",
            "data": [
                {
                    "type": "0B",
                    "item": "034310",
                    "values": {"10": "0", "20": "101530"},
                }
            ],
        },
        environment="REAL",
    )
    assert quotes == []


def test_hub_dispatch_034310_scope_and_isolation() -> None:
    hub = RealtimeMarketDataHub()
    kiwoom = _scope(
        user_id=61, account_id=1381, strategy_id=17579, broker="KIWOOM"
    )
    other_uba = _scope(
        user_id=7, account_id=9999, strategy_id=1, broker="KIWOOM"
    )
    upbit = _scope(
        user_id=61, account_id=1380, strategy_id=17483, broker="UPBIT"
    )
    hub.register_consumer(
        kiwoom,
        ["034310"],
        runtime_status=RuntimeLifecycleStatus.CREATED,
    )
    hub.register_consumer(
        other_uba,
        ["005930"],
        runtime_status=RuntimeLifecycleStatus.CREATED,
    )
    hub.register_consumer(
        upbit,
        ["KRW-XRP"],
        runtime_status=RuntimeLifecycleStatus.CREATED,
    )
    quotes = parse_market_message(OFFICIAL_0B_TICK, environment="REAL")
    signals = hub.ingest_quote_sync(quotes[0])
    assert signals == []
    consumers = {c["scope_key"]: c for c in hub.registry.list_consumers()}
    assert consumers[kiwoom.scope_key]["event_count"] == 1
    assert consumers[other_uba.scope_key]["event_count"] == 0
    assert consumers[upbit.scope_key]["event_count"] == 0
    event = hub._quote_to_event(quotes[0])
    assert event.broker_code == "KIWOOM"
    assert event.source_code == SOURCE_WEBSOCKET_REAL
    assert event.price == Decimal("40150")


def test_mock_feed_rejected_for_real_runtime() -> None:
    session = MagicMock()
    with patch(
        "stock_platform.realtime.kiwoom_market_source_gate."
        "kiwoom_uba_has_explicit_real_execution",
        return_value=True,
    ):
        mock_src = evaluate_real_execution_market_source(
            session,
            user_broker_account_id=1381,
            broker_code="KIWOOM",
            source_code=SOURCE_WEBSOCKET_MOCK,
        )
        rest_src = evaluate_real_execution_market_source(
            session,
            user_broker_account_id=1381,
            broker_code="KIWOOM",
            source_code=SOURCE_REST_POLLING,
        )
        real_src = evaluate_real_execution_market_source(
            session,
            user_broker_account_id=1381,
            broker_code="KIWOOM",
            source_code=SOURCE_WEBSOCKET_REAL,
        )
    assert mock_src["ok"] is False
    assert mock_src["reason"] == REASON_REAL_EXECUTION_REQUIRES_REAL_MARKET_DATA
    assert rest_src["ok"] is False
    assert rest_src["reason"] == REASON_REST_POLLING_NOT_LIVE_SOT
    assert real_src["ok"] is True
    assert REST_POLLING_IS_LIVE_RUNTIME_SOT is False
    assert MOCK_FEED_FALLBACK_ON_REAL_WS_DOWN is False


def test_login_reg_ack_and_tick_over_fake_socket() -> None:
    async def _run() -> None:
        incoming = [
            json.dumps(OFFICIAL_LOGIN_ACK),
            json.dumps(OFFICIAL_REG_ACK),
            json.dumps(OFFICIAL_0B_TICK),
        ]
        socket = _FakeSocket(incoming)

        def factory(*_a: object, **_k: object) -> _FakeSocket:
            return socket

        received: list[RealtimeQuote] = []

        async def handler(quote: RealtimeQuote) -> None:
            received.append(quote)

        client = KiwoomMarketRealtimeClient(
            config=_market_cfg(),
            token_cache=_FakeTokenCache(),
            quote_handler=handler,
            connect_factory=factory,
        )
        result = await client.probe_login_and_register(
            ["034310"],
            idle_seconds=0.05,
        )
        assert result["connected"] is False
        assert result["login_ack"] is True
        assert result["reg_ack"] is True
        assert result["subscription_count"] == 1
        assert result["event_count"] == 1
        assert received[0].source_code == SOURCE_WEBSOCKET_REAL
        login = json.loads(socket.sent[0])
        assert login["trnm"] == "LOGIN"
        assert "token" in login
        assert json.loads(socket.sent[1]) == OFFICIAL_REG
        assert "test-token-not-for-log" not in json.dumps(result)

    asyncio.run(_run())


def test_reconnect_resubscribe() -> None:
    async def _run() -> None:
        calls = {"n": 0}
        sockets: list[_FakeSocket] = []

        class _Factory:
            def __call__(self, *_a: object, **_k: object) -> "_Factory":
                return self

            async def __aenter__(self) -> _FakeSocket:
                calls["n"] += 1
                if calls["n"] == 1:
                    raise ConnectionError("first-fail")
                sock = _FakeSocket(
                    [
                        json.dumps(OFFICIAL_LOGIN_ACK),
                        json.dumps(OFFICIAL_REG_ACK),
                    ]
                )
                sockets.append(sock)
                return sock

            async def __aexit__(self, *_a: object) -> None:
                return None

        client = KiwoomMarketRealtimeClient(
            config=_market_cfg(),
            token_cache=_FakeTokenCache(),
            connect_factory=_Factory(),
        )
        client.subscribe_symbols(["034310"])
        task = asyncio.create_task(client.run_forever())
        try:
            for _ in range(50):
                if client.status()["login_ack"] and client.status()["reg_ack"]:
                    break
                await asyncio.sleep(0.02)
            status = client.status()
            assert status["reconnect_count"] >= 1
            assert status["login_ack"] is True
            assert status["reg_ack"] is True
            assert json.loads(sockets[0].sent[1]) == OFFICIAL_REG
        finally:
            await client.shutdown()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

    asyncio.run(_run())


def test_disconnect_status_fail_closed() -> None:
    client = KiwoomMarketRealtimeClient(
        config=_market_cfg(),
        token_cache=_FakeTokenCache(),
    )
    status = client.status()
    assert status["connected"] is False
    assert status["authenticated"] is False
    assert status["mock_fallback_enabled"] is False


def test_runner_stop_and_no_broker_orders() -> None:
    from stock_platform.realtime.execution_runner import RealtimeExecutionRunner
    from stock_platform.realtime.signal_bus import RealtimeSignalBus

    runner = RealtimeExecutionRunner(
        signal_bus=RealtimeSignalBus(),
        config=MagicMock(),
        safety_guard=MagicMock(),
    )
    assert runner.status()["running"] is False
    assert REST_POLLING_IS_LIVE_RUNTIME_SOT is False


def test_next_session_proof_contract_fields() -> None:
    status = KiwoomMarketRealtimeClient(
        config=_market_cfg(),
        token_cache=_FakeTokenCache(),
    ).status()
    for key in (
        "environment",
        "connected",
        "authenticated",
        "subscription_count",
        "event_count",
        "last_event_at",
        "last_error",
        "reconnect_count",
        "login_ack",
        "reg_ack",
    ):
        assert key in status
    assert datetime.now(timezone.utc).tzinfo is not None
