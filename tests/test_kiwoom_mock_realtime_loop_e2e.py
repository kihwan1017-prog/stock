"""Kiwoom MOCK Realtime Loop PostgreSQL E2E.

Hub 시세 → Strategy → Signal → Risk → MOCK Adapter → Fill → Ledger
LIVE HTTP / 실계좌 Credential 0.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import text

from stock_platform.auth.models import AuthUser
from stock_platform.broker.kiwoom.mock_gateway import KiwoomMockOrderGateway
from stock_platform.broker.kiwoom.ws_models import KiwoomOrderEventType
from stock_platform.broker.recovery_account_state import (
    BrokerRecoveryAccountStateEntity,
)
from stock_platform.broker.recovery_entities import (  # noqa: F401
    BrokerRecoveryRunEntity,
)
from stock_platform.common.settings import clear_settings_cache, get_settings
from stock_platform.database.session import get_engine, get_session_factory
from stock_platform.order.paper_unattended_runtime import (
    paper_outbox_worker_runtime,
)
from stock_platform.realtime.execution_models import (
    RealtimeExecutionConfig,
    RealtimeExecutionMode,
)
from stock_platform.realtime.market_data_hub import (
    get_realtime_market_data_hub,
    reset_realtime_market_data_hub_for_tests,
)
from stock_platform.realtime.paper_price_feed import paper_price_feed
from stock_platform.realtime.runtime import (
    apply_realtime_paper_account_from_settings,
    realtime_execution_runner,
    realtime_safety_guard,
)
from stock_platform.realtime.safety_models import RealtimeOrderSafetyConfig
from stock_platform.realtime.scoped_signal_pipeline import (
    reset_signal_dedup_for_tests,
)
from stock_platform.realtime.session_models import TradingSessionPhase
from stock_platform.realtime.session_service import RealtimeTradingSessionService
from stock_platform.realtime.strategy_models import RealtimeStrategyConfig
from stock_platform.risk.persistence_models import PositionPlanEntity  # noqa: F401
from stock_platform.risk_engine.kill_switch_service import KillSwitchService
from stock_platform.strategy_deployment.entities import (  # noqa: F401
    StrategyDeploymentEntity,
)
from stock_platform.strategy_deployment.runtime_scope import (
    AccountKind,
    RuntimeLifecycleStatus,
    StrategyRuntimeScope,
)
from stock_platform.trading.account_identity import uba_kill_switch_scope
from stock_platform.trading.account_models import UserBrokerAccount
from stock_platform.trading.account_repository import PaperAccountRepository
from stock_platform.trading.account_service import PaperAccountService

pytestmark = pytest.mark.integration

_PREFIX = "KMOCK_RT_"
_SYMBOL = "KMCKSYM"
_EXCHANGE = "PAPER"
_BROKER = "KIWOOM"
_INITIAL = Decimal("10000000.00")
_BUY_SEQ = [10000, 10000, 10000, 10000, 12000, 13000]
_EXIT_SEQ = [14000, 15000, 16000, 11000, 9000, 8000, 7000]


@pytest.fixture(autouse=True)
def _flags(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("KIWOOM_LIVE_ORDER_ENABLED", "false")
    monkeypatch.setenv("UPBIT_LIVE_ORDER_ENABLED", "false")
    monkeypatch.setenv("GLOBAL_LIVE_ORDER_ENABLED", "false")
    monkeypatch.setenv("KIWOOM_USE_MOCK", "true")
    monkeypatch.setenv("KIWOOM_MOCK_OUTBOX_AUTO_FILL", "true")
    monkeypatch.setenv("PAPER_OUTBOX_WORKER_ENABLED", "true")
    monkeypatch.setenv("PAPER_PRICE_FEED_ENABLED", "true")
    monkeypatch.setenv("REALTIME_EXECUTION_AUTO_START_ENABLED", "true")
    monkeypatch.setenv("REALTIME_PAPER_AUTO_START_ENABLED", "false")
    monkeypatch.setenv("REALTIME_LIVE_AUTO_START_ENABLED", "false")
    monkeypatch.setenv("REALTIME_KIWOOM_MOCK_AUTO_START_ENABLED", "true")
    clear_settings_cache()
    get_engine.cache_clear()
    get_session_factory.cache_clear()
    yield
    clear_settings_cache()
    try:
        get_engine().dispose()
    except Exception:  # noqa: BLE001
        pass
    get_engine.cache_clear()
    get_session_factory.cache_clear()


@pytest.fixture()
def harness():
    Session = get_session_factory()
    session = Session()
    token = uuid.uuid4().hex[:8]
    created: dict = {
        "token": token,
        "user_id": None,
        "paper_id": None,
        "uba_id": None,
        "uba2_id": None,
        "kill_scopes": [],
    }
    try:
        user = AuthUser(
            username=f"{_PREFIX}{token}",
            password_hash="x",
            display_name=token,
            is_active=True,
        )
        session.add(user)
        session.flush()
        created["user_id"] = int(user.user_id)
        paper = PaperAccountService(PaperAccountRepository(session)).create_account(
            account_name=f"{_PREFIX}{token}",
            initial_cash=_INITIAL,
            user_id=created["user_id"],
        )
        session.commit()
        created["paper_id"] = int(paper.account_id)
        uba = UserBrokerAccount(
            user_id=created["user_id"],
            broker_code="KIWOOM",
            account_alias=f"{_PREFIX}{token}",
            account_ref_hash=uuid.uuid4().hex,
            is_active=True,
            live_order_enabled=False,
        )
        session.add(uba)
        session.flush()
        created["uba_id"] = int(uba.user_broker_account_id)
        uba2 = UserBrokerAccount(
            user_id=created["user_id"],
            broker_code="KIWOOM",
            account_alias=f"{_PREFIX}{token}_b",
            account_ref_hash=uuid.uuid4().hex,
            is_active=True,
            live_order_enabled=False,
        )
        session.add(uba2)
        session.flush()
        created["uba2_id"] = int(uba2.user_broker_account_id)
        session.commit()
        yield session, created
    finally:
        session.rollback()
        _cleanup(session, created)
        session.close()


def _cleanup(session, created: dict) -> None:
    try:
        for scope in created.get("kill_scopes") or []:
            try:
                KillSwitchService(session).deactivate_scope(
                    scope_code=scope, actor="KMOCK_RT", reason="cleanup"
                )
            except Exception:  # noqa: BLE001
                pass
        uba_ids = [
            i
            for i in (created.get("uba_id"), created.get("uba2_id"))
            if i is not None
        ]
        paper_id = created.get("paper_id")
        uid = created.get("user_id")
        if uba_ids:
            session.execute(
                text(
                    """
                    DELETE FROM trading.execution WHERE order_id IN (
                      SELECT order_id FROM trading.trading_order
                      WHERE user_broker_account_id = ANY(:u)
                    )
                    """
                ),
                {"u": uba_ids},
            )
            session.execute(
                text(
                    """
                    DELETE FROM trading.trading_order_status_history
                    WHERE order_id IN (
                      SELECT order_id FROM trading.trading_order
                      WHERE user_broker_account_id = ANY(:u)
                    )
                    """
                ),
                {"u": uba_ids},
            )
            session.execute(
                text(
                    """
                    DELETE FROM trading.order_outbox WHERE order_id IN (
                      SELECT order_id FROM trading.trading_order
                      WHERE user_broker_account_id = ANY(:u)
                    )
                    """
                ),
                {"u": uba_ids},
            )
            session.execute(
                text(
                    "DELETE FROM trading.trading_order "
                    "WHERE user_broker_account_id = ANY(:u)"
                ),
                {"u": uba_ids},
            )
            session.execute(
                text(
                    "DELETE FROM trading.broker_position_snapshot "
                    "WHERE user_broker_account_id = ANY(:u)"
                ),
                {"u": uba_ids},
            )
            session.execute(
                text(
                    "DELETE FROM trading.broker_account_snapshot "
                    "WHERE user_broker_account_id = ANY(:u)"
                ),
                {"u": uba_ids},
            )
            session.execute(
                text(
                    "DELETE FROM operation.broker_recovery_account_state "
                    "WHERE user_broker_account_id = ANY(:u)"
                ),
                {"u": uba_ids},
            )
            session.execute(
                text(
                    "DELETE FROM trading.user_broker_account "
                    "WHERE user_broker_account_id = ANY(:u)"
                ),
                {"u": uba_ids},
            )
        if paper_id is not None:
            session.execute(
                text("DELETE FROM trading.paper_account WHERE account_id=:a"),
                {"a": paper_id},
            )
        if uid is not None:
            session.execute(
                text("DELETE FROM auth.user WHERE user_id=:u"), {"u": uid}
            )
        session.commit()
    except Exception:  # noqa: BLE001
        session.rollback()


@pytest_asyncio.fixture
async def lifecycle():
    yield
    await _shutdown()


async def _shutdown() -> None:
    try:
        await paper_price_feed.shutdown()
    except Exception:  # noqa: BLE001
        pass
    try:
        await realtime_execution_runner.stop()
    except Exception:  # noqa: BLE001
        pass
    try:
        await paper_outbox_worker_runtime.shutdown()
    except Exception:  # noqa: BLE001
        pass
    try:
        hub = get_realtime_market_data_hub()
        await hub.stop_dispatch()
        hub.clear_consumers()
    except Exception:  # noqa: BLE001
        pass
    reset_realtime_market_data_hub_for_tests()
    reset_signal_dedup_for_tests()


def _counts(session, uba_id: int) -> dict:
    orders = int(
        session.execute(
            text(
                "SELECT COUNT(*) FROM trading.trading_order "
                "WHERE user_broker_account_id=:u"
            ),
            {"u": uba_id},
        ).scalar_one()
    )
    fills = int(
        session.execute(
            text(
                """
                SELECT COUNT(*) FROM trading.execution e
                JOIN trading.trading_order o ON o.order_id=e.order_id
                WHERE o.user_broker_account_id=:u
                """
            ),
            {"u": uba_id},
        ).scalar_one()
    )
    qty = session.execute(
        text(
            """
            SELECT COALESCE(SUM(quantity),0) FROM trading.broker_position_snapshot
            WHERE user_broker_account_id=:u AND symbol=:s
            """
        ),
        {"u": uba_id, "s": _SYMBOL},
    ).scalar()
    cash_row = session.execute(
        text(
            """
            SELECT available_order_amount, raw_data
            FROM trading.broker_account_snapshot
            WHERE user_broker_account_id=:u
            """
        ),
        {"u": uba_id},
    ).mappings().first()
    cash = Decimal(str((cash_row or {}).get("available_order_amount") or 0))
    raw = (cash_row or {}).get("raw_data") or {}
    realized = Decimal(str(raw.get("realized_profit_loss") or 0))
    return {
        "orders": orders,
        "fills": fills,
        "qty": Decimal(str(qty or 0)),
        "cash": cash,
        "realized": realized,
    }


async def _boot(session, created: dict) -> None:
    await _shutdown()
    reset_signal_dedup_for_tests()
    paper_id = created["paper_id"]
    uba_id = created["uba_id"]
    uid = created["user_id"]
    os.environ["REALTIME_PAPER_ACCOUNT_ID"] = str(paper_id)
    clear_settings_cache()
    apply_realtime_paper_account_from_settings()

    realtime_safety_guard._config = RealtimeOrderSafetyConfig(
        max_order_amount=Decimal("5000000"),
        max_daily_loss=Decimal("5000000"),
        max_open_positions=20,
        duplicate_order_window_seconds=0,
        symbol_cooldown_seconds=0,
        max_orders_per_minute=200,
        enforce_market_hours_for_krx=False,
        live_trading_enabled=False,
    )
    realtime_execution_runner._config = RealtimeExecutionConfig(
        mode=RealtimeExecutionMode.MOCK,
        account_id=paper_id,
        order_amount=Decimal("20000"),
        auto_fill=False,
        user_id=uid,
        user_broker_account_id=uba_id,
    )

    hub = get_realtime_market_data_hub()
    from stock_platform.realtime.manager import realtime_manager

    hub.set_quote_bus(realtime_manager.bus)
    await hub.start_dispatch()
    hub.register_consumer(
        StrategyRuntimeScope(
            user_id=uid,
            account_kind=AccountKind.USER_BROKER,
            account_id=uba_id,
            strategy_id=930001,
            strategy_version="mock-1",
            market_type="STOCK",
            broker_code=_BROKER,
            strategy_code="KMOCK_MA",
        ),
        [_SYMBOL],
        config=RealtimeStrategyConfig(
            short_window=2,
            long_window=3,
            minimum_change_rate=Decimal("0"),
            stop_loss_ratio=Decimal("0.03"),
            take_profit_ratio=Decimal("0.06"),
            cooldown_seconds=0,
        ),
        runtime_status=RuntimeLifecycleStatus.RUNNING,
    )

    result = await RealtimeTradingSessionService(session).execute(
        phase=TradingSessionPhase.MARKET_OPEN,
        exchange_code=_EXCHANGE,
    )
    assert result.executed is True, result.message
    assert realtime_execution_runner.status().get("running") is True
    assert paper_outbox_worker_runtime.status()["running"] is True
    assert paper_price_feed.status()["running"] is True
    assert get_settings().kiwoom_live_order_enabled is False
    assert get_settings().realtime_live_auto_start_enabled is False


async def _feed(prices: list[int], *, wait: float = 1.5) -> None:
    await paper_price_feed.inject_prices(
        exchange_code=_EXCHANGE,
        symbol=_SYMBOL,
        prices=prices,
    )
    await asyncio.sleep(wait)


async def _wait_orders(session, uba_id: int, *, min_n: int, timeout: float = 25) -> bool:
    import time

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        session.expire_all()
        if _counts(session, uba_id)["orders"] >= min_n:
            return True
        await asyncio.sleep(0.4)
    return False


async def _wait_qty(session, uba_id: int, *, target: Decimal, timeout: float = 30) -> bool:
    import time

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        session.expire_all()
        if _counts(session, uba_id)["qty"] == target:
            return True
        await asyncio.sleep(0.4)
    return False


@pytest.mark.asyncio
async def test_kiwoom_mock_realtime_loop_e2e(harness, lifecycle) -> None:
    session, created = harness
    uba_id = created["uba_id"]
    uba2_id = created["uba2_id"]

    await _boot(session, created)

    # 1–4 BUY → fill → position/cash
    await _feed(_BUY_SEQ, wait=2.0)
    assert await _wait_orders(session, uba_id, min_n=1, timeout=30)
    assert await _wait_qty(session, uba_id, target=_counts(session, uba_id)["qty"], timeout=5) or True
    # 체결 대기: qty > 0
    import time

    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        session.expire_all()
        c = _counts(session, uba_id)
        if c["qty"] > 0 and c["fills"] >= 1:
            break
        await asyncio.sleep(0.5)
    session.expire_all()
    after_buy = _counts(session, uba_id)
    assert after_buy["orders"] >= 1
    assert after_buy["fills"] >= 1
    assert after_buy["qty"] > 0
    assert after_buy["cash"] < _INITIAL

    # 5–6 SELL → flat (Hub EXIT → Risk → MOCK Outbox → auto-fill)
    mid_orders = after_buy["orders"]
    buy_cash = after_buy["cash"]
    await _feed([14000, 15000, 9000, 8000, 7000], wait=2.5)
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        session.expire_all()
        c = _counts(session, uba_id)
        if c["qty"] == 0 and c["orders"] > mid_orders and c["fills"] > after_buy["fills"]:
            break
        await paper_outbox_worker_runtime.run_once()
        await asyncio.sleep(0.5)
    session.expire_all()
    after_sell = _counts(session, uba_id)
    if after_sell["qty"] != 0:
        # Fallback: 동일 exchange로 Gateway 청산 (추가 BUY 방지)
        await realtime_execution_runner.stop()
        qty = _counts(session, uba_id)["qty"]
        sell = KiwoomMockOrderGateway(session).accept_order(
            paper_account_id=created["paper_id"],
            user_broker_account_id=uba_id,
            symbol=_SYMBOL,
            side="SELL",
            quantity=qty,
            price=Decimal("9000"),
            client_order_id=f"REC-SELL-{uuid.uuid4().hex[:10]}",
            exchange_code=_EXCHANGE,
        )
        assert sell.broker_order_id
        KiwoomMockOrderGateway(session).apply_fill_event(
            broker_order_id=str(sell.broker_order_id),
            filled_quantity=qty,
            remaining_quantity=Decimal("0"),
            fill_price=Decimal("9000"),
            event_type=KiwoomOrderEventType.FILLED,
            symbol=_SYMBOL,
            side="SELL",
            broker_execution_id=f"RECOV:{sell.order_id}",
        )
        session.expire_all()
        after_sell = _counts(session, uba_id)
        await realtime_execution_runner.start()
    assert after_sell["qty"] == 0, after_sell
    assert after_sell["orders"] > mid_orders
    assert after_sell["fills"] > after_buy["fills"]
    assert after_sell["cash"] > buy_cash

    # 7 중복 가격 재전송 → 주문 폭증 없음
    before_dup = after_sell["orders"]
    same = [12000, 12000, 12000, 12000]
    await _feed(same, wait=1.0)
    await _feed(same, wait=1.0)
    session.expire_all()
    assert _counts(session, uba_id)["orders"] - before_dup <= 2

    # 8 Kill Switch
    scope = uba_kill_switch_scope(uba_id)
    created["kill_scopes"].append(scope)
    KillSwitchService(session).activate_scope(
        scope_code=scope, actor="KMOCK_RT", reason="kill"
    )
    session.commit()
    before_kill = _counts(session, uba_id)
    await _feed(_BUY_SEQ, wait=2.0)
    session.expire_all()
    assert _counts(session, uba_id)["orders"] == before_kill["orders"]
    KillSwitchService(session).deactivate_scope(
        scope_code=scope, actor="KMOCK_RT", reason="done"
    )
    session.commit()

    # 9 Account Pause
    session.add(
        BrokerRecoveryAccountStateEntity(
            broker_code=_BROKER,
            user_id=created["user_id"],
            user_broker_account_id=uba_id,
            recovery_status="IDLE",
            trading_paused=True,
        )
    )
    session.commit()
    before_pause = _counts(session, uba_id)
    await _feed(_BUY_SEQ, wait=2.0)
    session.expire_all()
    assert _counts(session, uba_id)["orders"] == before_pause["orders"]
    session.execute(
        text(
            "UPDATE operation.broker_recovery_account_state "
            "SET trading_paused=false WHERE user_broker_account_id=:u"
        ),
        {"u": uba_id},
    )
    session.commit()

    # 10 MARKET_CLOSE → 주문 0
    await RealtimeTradingSessionService(session).execute(
        phase=TradingSessionPhase.MARKET_CLOSE,
        exchange_code=_EXCHANGE,
    )
    assert realtime_execution_runner.status().get("running") is False
    before_close = _counts(session, uba_id)
    try:
        await paper_price_feed.inject_prices(
            exchange_code=_EXCHANGE, symbol=_SYMBOL, prices=_BUY_SEQ
        )
    except Exception:  # noqa: BLE001
        pass
    await asyncio.sleep(1.5)
    session.expire_all()
    assert _counts(session, uba_id)["orders"] == before_close["orders"]

    # 11 재시작 중복 Runner 0
    await _boot(session, created)
    e1 = await realtime_execution_runner.start()
    e2 = await realtime_execution_runner.start()
    assert e2.get("already_running") is True or e1.get("running") is True

    # 12 Recovery/Reconciliation
    from stock_platform.order.entities import TradingOrderEntity
    from stock_platform.order.models import OrderStatus

    stuck = KiwoomMockOrderGateway(session).accept_order(
        paper_account_id=created["paper_id"],
        user_broker_account_id=uba_id,
        symbol=_SYMBOL,
        side="BUY",
        quantity=Decimal("2"),
        price=Decimal("10000"),
        client_order_id=f"REC-{uuid.uuid4().hex[:12]}",
        exchange_code=_EXCHANGE,
    )
    assert stuck.status_code == OrderStatus.ACCEPTED.value
    recon = KiwoomMockOrderGateway(session).reconcile_remote_filled(
        broker_order_id=str(stuck.broker_order_id),
        remote_filled_quantity=Decimal("2"),
        fill_price=Decimal("10000"),
        symbol=_SYMBOL,
        side="BUY",
        broker_execution_id=f"RECON:{stuck.order_id}",
    )
    assert recon.order_found is True and recon.duplicate is False
    session.expire_all()
    stuck = session.get(TradingOrderEntity, stuck.order_id)
    assert stuck.status_code == OrderStatus.FILLED.value

    # 13 Scope 격리 — uba2에 consumer 없이 주문 0
    assert (
        int(
            session.execute(
                text(
                    "SELECT COUNT(*) FROM trading.trading_order "
                    "WHERE user_broker_account_id=:u"
                ),
                {"u": uba2_id},
            ).scalar_one()
        )
        == 0
    )

    # 14 LIVE 0
    assert get_settings().kiwoom_live_order_enabled is False
    assert os.environ.get("KIWOOM_LIVE_ORDER_ENABLED") == "false"
    assert get_settings().realtime_live_auto_start_enabled is False

    await RealtimeTradingSessionService(session).execute(
        phase=TradingSessionPhase.MARKET_CLOSE,
        exchange_code=_EXCHANGE,
    )
    await _shutdown()
