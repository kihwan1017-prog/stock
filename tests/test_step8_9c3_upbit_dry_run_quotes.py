"""STEP 8-9C-3 — Upbit market snapshot / dry-run readiness."""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from stock_platform.broker.upbit.market_snapshot import (
    UpbitMarketQuoteError,
    UpbitOrderbookSnapshot,
    UpbitTickerSnapshot,
    mock_orderbook,
    mock_ticker,
    parse_orderbook_row,
    parse_ticker_row,
    round_price_to_tick,
)
from stock_platform.trading.upbit_live_preflight_service import (
    UpbitLivePreflightService,
)
from stock_platform.trading.upbit_scheduler_readiness import (
    collect_scheduler_readiness,
)


def test_parse_ticker_list_response() -> None:
    snap = parse_ticker_row(
        [{"market": "KRW-XRP", "trade_price": "1607", "timestamp": 1_700_000_000_000}],
        expected_market="KRW-XRP",
    )
    assert isinstance(snap, UpbitTickerSnapshot)
    assert snap.market == "KRW-XRP"
    assert snap.trade_price == Decimal("1607")


def test_parse_ticker_dict_response() -> None:
    snap = parse_ticker_row(
        {"market": "KRW-XRP", "trade_price": "1600.5", "timestamp": 1},
        expected_market="KRW-XRP",
    )
    assert snap.trade_price == Decimal("1600.5")


def test_parse_ticker_malformed_fail_closed() -> None:
    with pytest.raises(UpbitMarketQuoteError) as exc:
        parse_ticker_row("not-a-dict")
    assert exc.value.reason_code == "TICKER_MALFORMED"


def test_parse_orderbook_units_ok() -> None:
    snap = parse_orderbook_row(
        {
            "market": "KRW-XRP",
            "timestamp": 1,
            "orderbook_units": [
                {
                    "bid_price": "1605",
                    "ask_price": "1606",
                    "bid_size": "10",
                    "ask_size": "12",
                }
            ],
        },
        expected_market="KRW-XRP",
    )
    assert isinstance(snap, UpbitOrderbookSnapshot)
    assert snap.best_bid_price == Decimal("1605")
    assert snap.best_ask_price == Decimal("1606")


def test_parse_orderbook_empty_fail_closed() -> None:
    with pytest.raises(UpbitMarketQuoteError) as exc:
        parse_orderbook_row(
            {"market": "KRW-XRP", "orderbook_units": []},
            expected_market="KRW-XRP",
        )
    assert exc.value.reason_code == "ORDERBOOK_UNITS_EMPTY"


def test_mock_live_dto_contract_identical() -> None:
    t = mock_ticker("KRW-XRP", Decimal("1600"))
    o = mock_orderbook("KRW-XRP", mid=Decimal("1600"))
    assert set(t.to_dict()) == {
        "market",
        "trade_price",
        "timestamp",
        "raw_ok",
    }
    assert set(o.to_dict()) >= {
        "market",
        "best_bid_price",
        "best_ask_price",
        "best_bid_size",
        "best_ask_size",
        "timestamp",
        "raw_ok",
    }


def test_slippage_fail_when_ticker_missing() -> None:
    session = MagicMock()
    uba = SimpleNamespace(
        user_broker_account_id=58,
        user_id=7,
        broker_code="UPBIT",
        is_active=True,
        live_order_enabled=True,
        live_armed=True,
    )
    session.get.return_value = uba
    from stock_platform.risk_engine.kill_switch_models import (
        KillSwitchState,
        KillSwitchStatus,
    )
    from stock_platform.risk_engine.resolved_policy import ResolvedRiskPolicy

    policy = ResolvedRiskPolicy(
        max_order_amount=Decimal("10000"),
        daily_max_order_amount=Decimal("200000"),
        max_total_investment_amount=Decimal("1000000"),
        max_position_amount=Decimal("200000"),
        max_position_count=5,
        max_position_weight=Decimal("0.2"),
        allow_duplicate_buy=True,
        daily_max_loss_amount=Decimal("30000"),
        daily_max_loss_rate=Decimal("0.05"),
        stop_loss_rate=Decimal("0.05"),
        take_profit_rate=Decimal("0.1"),
        trailing_stop_rate=Decimal("0.03"),
        auto_trading_enabled=True,
        buy_enabled=True,
        sell_enabled=True,
        sell_only=False,
        account_paused=False,
        max_order_quantity=Decimal("100"),
        daily_order_limit=20,
        duplicate_order_window_seconds=5,
        max_open_orders=20,
        max_slippage_rate=Decimal("0.05"),
        anomaly_orders_per_minute=10,
        loop_detect_window_seconds=60,
        arm_ttl_seconds=300,
        source_layers=("system",),
    )
    with (
        patch(
            "stock_platform.trading.upbit_live_preflight_service.KillSwitchService"
        ) as KS,
        patch(
            "stock_platform.trading.upbit_live_preflight_service.LiveArmService"
        ) as ARM,
        patch(
            "stock_platform.trading.upbit_live_preflight_service.ResolvedRiskPolicyResolver"
        ) as R,
        patch(
            "stock_platform.trading.upbit_live_preflight_service.emit_live_safety_audit"
        ),
        patch.object(
            UpbitLivePreflightService,
            "_check_credential",
            return_value=(True, "ok"),
        ),
        patch.object(
            UpbitLivePreflightService,
            "_check_broker_health",
            return_value=(True, "ok"),
        ),
        patch.object(
            UpbitLivePreflightService,
            "_open_order_count",
            return_value=0,
        ),
        patch.object(
            UpbitLivePreflightService,
            "_daily_order_count",
            return_value=0,
        ),
        patch.object(
            UpbitLivePreflightService,
            "_fetch_price_book",
            return_value={
                "ref_price": None,
                "ticker_ok": False,
                "book_ok": False,
                "ticker_msg": "TICKER_MALFORMED",
                "book_msg": "ORDERBOOK_UNITS_EMPTY",
            },
        ),
        patch(
            "stock_platform.broker.upbit.market_snapshot.resolve_tick_and_price",
            return_value={
                "requested_limit_price": "1607",
                "effective_limit_price": "1607",
                "tick_size": "1",
                "tick_source": "STATIC",
                "adjustment_reason": None,
                "effective_price": Decimal("1607"),
                "tick": Decimal("1"),
            },
        ),
    ):
        KS.return_value.get_state.return_value = KillSwitchState(
            status=KillSwitchStatus.INACTIVE,
            reason=None,
            activated_by=None,
            activated_at=None,
            deactivated_by=None,
            deactivated_at=None,
        )
        ARM.return_value.expire_if_needed.return_value = False
        ARM.return_value.get_arm_status.return_value = {
            "live_armed": True,
            "arm_expires_at": None,
        }
        ARM.return_value.validate_arm_token.return_value = (True, "ARM_OK")
        R.return_value.resolve.return_value = policy
        result = UpbitLivePreflightService(session).run(
            user_broker_account_id=58,
            market="KRW-XRP",
            side="BUY",
            amount=Decimal("5000"),
            limit_price=Decimal("1607"),
            arm_token="tok",
            skip_live_network=False,
            purpose="live_execution",
        )
    assert any("SLIPPAGE" in b for b in result.blockers)
    assert any("TICKER" in b for b in result.blockers)
    assert not any(
        c["code"] == "SLIPPAGE" and c["status"] == "PASS" for c in result.checks
    )


def test_scheduler_common_service_paused_when_not_running() -> None:
    fake = SimpleNamespace(scheduler=SimpleNamespace(running=False))
    with patch(
        "stock_platform.realtime.session_runtime.realtime_trading_scheduler",
        fake,
    ):
        snap = collect_scheduler_readiness()
    assert snap.trading_scheduler_paused is True
    assert snap.trading_scheduler_actual_state == "PAUSED"


def test_scheduler_active_is_blocker_state() -> None:
    fake = SimpleNamespace(scheduler=SimpleNamespace(running=True))
    with patch(
        "stock_platform.realtime.session_runtime.realtime_trading_scheduler",
        fake,
    ):
        snap = collect_scheduler_readiness()
    assert snap.trading_scheduler_paused is False
    assert snap.trading_scheduler_actual_state == "RUNNING"


def test_round_price_buy_records_adjustment() -> None:
    # Broker tick=1 → 1607 stays; tick=5 → 1605
    assert round_price_to_tick(
        Decimal("1607"), Decimal("5"), side="BUY"
    ) == Decimal("1605")
    assert round_price_to_tick(
        Decimal("1607"), Decimal("1"), side="BUY"
    ) == Decimal("1607")
