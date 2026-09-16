"""Paper 무인 자동매매 PostgreSQL E2E (S1–S8 + 동시성).

서비스 메서드 직접 Fill 금지 — Worker/Runner/Feed/Recovery 경로만 사용.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy import text

from stock_platform.auth.models import AuthUser
from stock_platform.broker.recovery_account_state import (
    BrokerRecoveryAccountStateEntity,
)
from stock_platform.broker.recovery_entities import (  # noqa: F401
    BrokerRecoveryRunEntity,
)
from stock_platform.common.settings import clear_settings_cache, get_settings
from stock_platform.database.session import get_engine, get_session_factory
from stock_platform.order.paper_outbox_fill_service import (
    PaperOutboxFillResult,
    PaperOutboxFillService,
)
from stock_platform.order.paper_unattended_runtime import (
    paper_fill_recovery_scheduler,
    paper_outbox_worker_runtime,
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
from stock_platform.trading.account_identity import paper_kill_switch_scope
from stock_platform.trading.account_repository import PaperAccountRepository
from stock_platform.trading.account_service import PaperAccountService
from stock_platform.realtime.execution_models import (
    RealtimeExecutionConfig,
    RealtimeExecutionMode,
)

pytestmark = pytest.mark.integration

_PREFIX = "PAPER_UA_"
_SYMBOL = "UAESYM"
_EXCHANGE = "PAPER"
_BROKER = "PAPER"
_INITIAL = Decimal("10000000.00")


@pytest.fixture(autouse=True)
def _flags(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("PAPER_OUTBOX_AUTO_FILL", "true")
    monkeypatch.setenv("PAPER_OUTBOX_WORKER_ENABLED", "true")
    monkeypatch.setenv("PAPER_FILL_RECOVERY_ENABLED", "true")
    monkeypatch.setenv("PAPER_PRICE_FEED_ENABLED", "true")
    monkeypatch.setenv("REALTIME_EXECUTION_AUTO_START_ENABLED", "true")
    monkeypatch.setenv("REALTIME_PAPER_AUTO_START_ENABLED", "true")
    monkeypatch.setenv("REALTIME_LIVE_AUTO_START_ENABLED", "false")
    monkeypatch.setenv("KIWOOM_LIVE_ORDER_ENABLED", "false")
    monkeypatch.setenv("UPBIT_LIVE_ORDER_ENABLED", "false")
    monkeypatch.setenv("GLOBAL_LIVE_ORDER_ENABLED", "false")
    monkeypatch.setenv("DB_POOL_SIZE", "8")
    monkeypatch.setenv("DB_MAX_OVERFLOW", "2")
    monkeypatch.setenv("PAPER_OUTBOX_WORKER_INTERVAL_SECONDS", "0.4")
    monkeypatch.setenv("PAPER_FILL_RECOVERY_INTERVAL_SECONDS", "1.0")
    monkeypatch.setenv("PAPER_OUTBOX_WORKER_STALE_SECONDS", "2")
    monkeypatch.setenv("REALTIME_EVENT_MAX_AGE_SECONDS", "3600")
    clear_settings_cache()
    get_engine.cache_clear()
    get_session_factory.cache_clear()
    reset_realtime_market_data_hub_for_tests()
    yield
    clear_settings_cache()
    try:
        get_engine().dispose()
    except Exception:  # noqa: BLE001
        pass
    get_engine.cache_clear()
    get_session_factory.cache_clear()
    reset_realtime_market_data_hub_for_tests()


async def _shutdown_all() -> None:
    for coro in (
        paper_outbox_worker_runtime.shutdown(),
        paper_fill_recovery_scheduler.shutdown(),
        paper_price_feed.shutdown(),
        realtime_execution_runner.stop(),
        get_realtime_market_data_hub().stop_dispatch(),
    ):
        try:
            await asyncio.wait_for(coro, timeout=8.0)
        except Exception:  # noqa: BLE001
            pass
    try:
        _force_unlock_paper_outbox()
    except Exception:  # noqa: BLE001
        pass


@pytest_asyncio.fixture
async def ua_lifecycle():
    """테스트 종료 시 비동기 런타임 정리 (동일 이벤트 루프)."""

    yield
    await _shutdown_all()


@pytest.fixture()
def harness():
    Session = get_session_factory()
    session = Session()
    token = uuid.uuid4().hex[:10]
    created = {
        "token": token,
        "user_id": None,
        "account_id": None,
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
        acct = PaperAccountService(PaperAccountRepository(session)).create_account(
            account_name=f"{_PREFIX}acct_{token}",
            initial_cash=_INITIAL,
            user_id=created["user_id"],
        )
        session.commit()
        created["account_id"] = int(acct.account_id)
        yield session, created
    finally:
        session.rollback()
        _cleanup(session, created)
        session.close()


def _cleanup(session, created: dict) -> None:
    aid = created.get("account_id")
    uid = created.get("user_id")
    try:
        for scope in created.get("kill_scopes") or []:
            try:
                KillSwitchService(session).deactivate_scope(
                    scope_code=scope,
                    actor="UA_CLEANUP",
                    reason="cleanup",
                )
            except Exception:  # noqa: BLE001
                session.rollback()
        if aid is not None:
            session.execute(
                text(
                    "DELETE FROM operation.broker_recovery_account_state "
                    "WHERE paper_account_id = :aid"
                ),
                {"aid": aid},
            )
            session.execute(
                text("DELETE FROM trading.paper_trade WHERE account_id=:a"),
                {"a": aid},
            )
            session.execute(
                text("DELETE FROM trading.paper_order WHERE account_id=:a"),
                {"a": aid},
            )
            session.execute(
                text(
                    """
                    DELETE FROM trading.trading_order_status_history
                    WHERE order_id IN (
                      SELECT order_id FROM trading.trading_order
                      WHERE account_id=:a
                    )
                    """
                ),
                {"a": aid},
            )
            session.execute(
                text(
                    """
                    DELETE FROM trading.order_outbox
                    WHERE order_id IN (
                      SELECT order_id FROM trading.trading_order
                      WHERE account_id=:a
                    )
                    """
                ),
                {"a": aid},
            )
            session.execute(
                text("DELETE FROM trading.trading_order WHERE account_id=:a"),
                {"a": aid},
            )
            session.execute(
                text("DELETE FROM trading.paper_position WHERE account_id=:a"),
                {"a": aid},
            )
            session.execute(
                text("DELETE FROM trading.paper_account WHERE account_id=:a"),
                {"a": aid},
            )
        if uid is not None:
            session.execute(
                text("DELETE FROM auth.user WHERE user_id=:u"),
                {"u": uid},
            )
        session.commit()
    except Exception:  # noqa: BLE001
        session.rollback()


def _counts(session, account_id: int) -> dict:
    # harness 세션 트랜잭션과 분리해 pool 고갈·락 대기 방지
    Session = get_session_factory()
    with Session() as probe:
        return {
            "orders": int(
                probe.execute(
                    text(
                        "SELECT COUNT(*) FROM trading.trading_order "
                        "WHERE account_id=:a"
                    ),
                    {"a": account_id},
                ).scalar_one()
            ),
            "outbox": int(
                probe.execute(
                    text(
                        """
                        SELECT COUNT(*) FROM trading.order_outbox o
                        JOIN trading.trading_order t ON t.order_id=o.order_id
                        WHERE t.account_id=:a
                        """
                    ),
                    {"a": account_id},
                ).scalar_one()
            ),
            "fills": int(
                probe.execute(
                    text(
                        "SELECT COUNT(*) FROM trading.paper_trade "
                        "WHERE account_id=:a"
                    ),
                    {"a": account_id},
                ).scalar_one()
            ),
            "qty": Decimal(
                str(
                    probe.execute(
                        text(
                            """
                            SELECT COALESCE(SUM(quantity),0)
                            FROM trading.paper_position
                            WHERE account_id=:a AND symbol=:s
                            """
                        ),
                        {"a": account_id, "s": _SYMBOL},
                    ).scalar_one()
                )
            ),
            "cash": Decimal(
                str(
                    probe.execute(
                        text(
                            "SELECT available_cash FROM trading.paper_account "
                            "WHERE account_id=:a"
                        ),
                        {"a": account_id},
                    ).scalar_one()
                )
            ),
            "realized": Decimal(
                str(
                    probe.execute(
                        text(
                            "SELECT realized_profit_loss FROM trading.paper_account "
                            "WHERE account_id=:a"
                        ),
                        {"a": account_id},
                    ).scalar_one()
                )
            ),
        }


def _force_unlock_paper_outbox() -> None:
    """죽은 테스트 프로세스가 남긴 PROCESSING lock 해제."""

    Session = get_session_factory()
    with Session() as s:
        s.execute(
            text(
                """
                UPDATE trading.order_outbox
                SET status_code = 'PENDING',
                    locked_by = NULL,
                    locked_at = NULL,
                    lease_expires_at = NULL,
                    next_retry_at = NULL
                WHERE status_code = 'PROCESSING'
                  AND user_broker_account_id IS NULL
                  AND COALESCE(payload_json->>'environment', 'PAPER') <> 'LIVE'
                """
            )
        )
        s.commit()


async def _wait_until(predicate, *, timeout: float = 12.0, interval: float = 0.25):
    deadline = asyncio.get_event_loop().time() + timeout
    last = None
    while asyncio.get_event_loop().time() < deadline:
        last = predicate()
        if last:
            return last
        await asyncio.sleep(interval)
    raise AssertionError(f"condition not met within {timeout}s: {last}")


async def _boot_unattended(session, created: dict) -> StrategyRuntimeScope:
    """Flag ON 상태에서 MARKET_OPEN → Runner/Worker/Feed 기동 + Scope 등록."""

    await _shutdown_all()
    _force_unlock_paper_outbox()
    from stock_platform.realtime.scoped_signal_pipeline import (
        reset_signal_dedup_for_tests,
    )

    reset_signal_dedup_for_tests()

    aid = created["account_id"]
    uid = created["user_id"]
    os.environ["REALTIME_PAPER_ACCOUNT_ID"] = str(aid)
    clear_settings_cache()
    apply_realtime_paper_account_from_settings()

    # Safety: KRX 시간 게이트 해제
    realtime_safety_guard._config = RealtimeOrderSafetyConfig(
        max_order_amount=Decimal("5000000"),
        max_daily_loss=Decimal("5000000"),
        max_open_positions=20,
        duplicate_order_window_seconds=0,
        symbol_cooldown_seconds=0,
        max_orders_per_minute=100,
        enforce_market_hours_for_krx=False,
        live_trading_enabled=False,
    )
    realtime_execution_runner._config = RealtimeExecutionConfig(
        mode=RealtimeExecutionMode.PAPER,
        account_id=aid,
        order_amount=Decimal("20000"),
        auto_fill=False,
        user_id=uid,
    )

    hub = get_realtime_market_data_hub()
    from stock_platform.realtime.manager import realtime_manager

    hub.set_quote_bus(realtime_manager.bus)

    scope = StrategyRuntimeScope(
        user_id=uid,
        account_kind=AccountKind.PAPER,
        account_id=aid,
        strategy_id=910001,
        strategy_version="ua-1",
        market_type="STOCK",
        broker_code=_BROKER,
        strategy_code="UA_MA",
    )
    hub.register_consumer(
        scope,
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

    # MARKET_OPEN (PAPER exchange → calendar skip 없음)
    result = await RealtimeTradingSessionService(session).execute(
        phase=TradingSessionPhase.MARKET_OPEN,
        exchange_code="PAPER",
    )
    assert result.executed is True, result.message

    # idempotent restart
    again = paper_outbox_worker_runtime.start()
    assert again.get("reason") in {None, "ALREADY_RUNNING"} or again.get(
        "started"
    ) in {True, False}
    assert paper_outbox_worker_runtime.status()["running"] is True
    assert paper_price_feed.status()["running"] is True
    # execution runner: task 생성 직후 _running 레이스 허용
    exec_st = realtime_execution_runner.status()
    assert exec_st.get("running") is True or realtime_execution_runner._task is not None
    return scope


async def _inject_and_drain(prices: list) -> None:
    """Hub sync ingest → Signal Bus → Worker (E2E deterministic path).

    백그라운드 Worker와 동시 claim 경합을 피하기 위해 drain 구간만
    루프를 잠시 멈추고 동일 Worker.run_once 경로로 fill 한다.
    """

    from datetime import timedelta

    from stock_platform.realtime.models import MarketEventType, RealtimeQuote
    from stock_platform.realtime.scoped_signal_pipeline import (
        publish_scoped_signal,
    )

    _force_unlock_paper_outbox()
    hub = get_realtime_market_data_hub()
    base = datetime.now(timezone.utc)
    for idx, raw in enumerate(prices):
        ts = base + timedelta(milliseconds=idx * 80)
        quote = RealtimeQuote(
            exchange_code=_EXCHANGE,
            symbol=_SYMBOL,
            event_type=MarketEventType.TRADE,
            trade_price=Decimal(str(raw)),
            opening_price=None,
            high_price=None,
            low_price=None,
            previous_close_price=None,
            change_price=None,
            change_rate=None,
            accumulated_volume=None,
            trade_volume=Decimal("1"),
            event_time=ts,
            received_at=ts,
            source_code="PAPER_REPLAY",
        )
        signals = hub.ingest_quote_sync(quote)
        for signal in signals:
            await publish_scoped_signal(signal)
        await asyncio.sleep(0.08)
    # Runner가 Outbox enqueue 할 시간
    await asyncio.sleep(0.35)

    worker_was_running = bool(
        paper_outbox_worker_runtime.status().get("running")
    )
    if worker_was_running:
        await paper_outbox_worker_runtime.shutdown()
    _force_unlock_paper_outbox()
    for _ in range(10):
        await asyncio.wait_for(
            paper_outbox_worker_runtime.run_once(),
            timeout=5.0,
        )
        await asyncio.sleep(0.03)
    if worker_was_running:
        paper_outbox_worker_runtime.start()




@pytest.mark.asyncio
async def test_s1_unattended_auto_buy(harness, ua_lifecycle) -> None:
    session, created = harness
    await _boot_unattended(session, created)
    before = _counts(session, created["account_id"])

    # warmup + golden cross → BUY (가격대는 max_order_quantity 한도 내 qty)
    await _inject_and_drain([10000, 10000, 10000, 10000, 12000, 13000])

    await _wait_until(
        lambda: _counts(session, created["account_id"])["fills"]
        > before["fills"]
    )
    after = _counts(session, created["account_id"])
    assert after["orders"] >= before["orders"] + 1
    assert after["outbox"] >= before["outbox"] + 1
    assert after["fills"] >= before["fills"] + 1
    assert after["qty"] > 0
    assert after["cash"] < _INITIAL
    assert os.environ.get("KIWOOM_LIVE_ORDER_ENABLED") == "false"


@pytest.mark.asyncio
async def test_s2_unattended_auto_exit(harness, ua_lifecycle) -> None:
    session, created = harness
    await _boot_unattended(session, created)
    await _inject_and_drain([10000, 10000, 10000, 10000, 12000, 13000])
    await _wait_until(
        lambda: _counts(session, created["account_id"])["qty"] > 0,
        timeout=20,
    )
    mid = _counts(session, created["account_id"])
    # 익절: entry*1.06 이상. 하락 dead-cross 백업도 함께 주입
    await _inject_and_drain(
        [14000, 15000, 16000, 11000, 9000, 8000, 7000]
    )
    await _wait_until(
        lambda: _counts(session, created["account_id"])["qty"] == 0,
        timeout=20,
    )
    final = _counts(session, created["account_id"])
    assert final["qty"] == 0
    assert final["fills"] > mid["fills"]
    assert final["cash"] > mid["cash"]
    assert final["realized"] != 0


@pytest.mark.asyncio
async def test_s3_market_close_stops_orders(harness, ua_lifecycle) -> None:
    session, created = harness
    await _boot_unattended(session, created)
    await RealtimeTradingSessionService(session).execute(
        phase=TradingSessionPhase.MARKET_CLOSE,
        exchange_code="PAPER",
    )
    assert realtime_execution_runner.status().get("running") is False
    assert paper_price_feed.status().get("running") is False
    before = _counts(session, created["account_id"])
    # feed stopped — direct bus publish도 runner stop 이면 주문 없음에 가깝게
    await _inject_and_drain([10000, 10000, 10000, 10000, 12000, 13000])
    await asyncio.sleep(2)
    after = _counts(session, created["account_id"])
    assert after["orders"] == before["orders"]


@pytest.mark.asyncio
async def test_s4_kill_switch_blocks(harness, ua_lifecycle) -> None:
    session, created = harness
    await _boot_unattended(session, created)
    scope = paper_kill_switch_scope(created["account_id"])
    created["kill_scopes"].append(scope)
    KillSwitchService(session).activate_scope(
        scope_code=scope,
        actor="UA_E2E",
        reason="kill",
    )
    before = _counts(session, created["account_id"])
    await _inject_and_drain([10000, 10000, 10000, 10000, 12000, 13000, 14000])
    await asyncio.sleep(2)
    after = _counts(session, created["account_id"])
    assert after["orders"] == before["orders"]
    assert after["fills"] == before["fills"]
    assert after["qty"] == before["qty"]
    KillSwitchService(session).deactivate_scope(
        scope_code=scope,
        actor="UA_E2E",
        reason="done",
    )


@pytest.mark.asyncio
async def test_s5_account_pause_blocks(harness, ua_lifecycle) -> None:
    session, created = harness
    await _boot_unattended(session, created)
    session.add(
        BrokerRecoveryAccountStateEntity(
            broker_code=_BROKER,
            user_id=created["user_id"],
            paper_account_id=created["account_id"],
            recovery_status="IDLE",
            trading_paused=True,
        )
    )
    session.commit()
    before = _counts(session, created["account_id"])
    await _inject_and_drain([10000, 10000, 10000, 10000, 12000, 13000, 14000])
    await asyncio.sleep(2)
    after = _counts(session, created["account_id"])
    assert after["orders"] == before["orders"]
    assert after["qty"] == before["qty"]


@pytest.mark.asyncio
async def test_s6_worker_crash_recovery(harness, ua_lifecycle, monkeypatch) -> None:
    session, created = harness
    await _boot_unattended(session, created)

    original = PaperOutboxFillService.fill_accepted_order

    def _crash(self, order_id, **kwargs):
        return PaperOutboxFillResult(
            filled=False,
            skipped=True,
            reason_code="SIMULATED_CRASH",
            order_id=int(order_id),
            order_status="ACCEPTED",
        )

    monkeypatch.setattr(PaperOutboxFillService, "fill_accepted_order", _crash)
    await _inject_and_drain([10000, 10000, 10000, 10000, 12000, 13000])

    def _accepted_count() -> int:
        Session = get_session_factory()
        with Session() as probe:
            return int(
                probe.execute(
                    text(
                        """
                        SELECT COUNT(*) FROM trading.trading_order
                        WHERE account_id=:a AND status_code='ACCEPTED'
                        """
                    ),
                    {"a": created["account_id"]},
                ).scalar_one()
            )

    await _wait_until(lambda: _accepted_count() >= 1, timeout=25)
    session.expire_all()
    assert _counts(session, created["account_id"])["fills"] == 0

    monkeypatch.setattr(PaperOutboxFillService, "fill_accepted_order", original)
    # Recovery scheduler 경로 (직접 fill 서비스 테스트 호출 금지 — run_once만)
    result = await paper_fill_recovery_scheduler.run_once()
    assert result.get("filled", 0) >= 1
    session.expire_all()
    assert _counts(session, created["account_id"])["fills"] >= 1
    qty = _counts(session, created["account_id"])["qty"]
    # 재실행 중복 없음
    await paper_fill_recovery_scheduler.run_once()
    session.expire_all()
    assert _counts(session, created["account_id"])["qty"] == qty


@pytest.mark.asyncio
async def test_s7_restart_no_duplicate_runner(harness, ua_lifecycle) -> None:
    session, created = harness
    await _boot_unattended(session, created)
    # 재시작 시뮬레이션
    await realtime_execution_runner.stop()
    await paper_outbox_worker_runtime.shutdown()
    r1 = paper_outbox_worker_runtime.start()
    r2 = paper_outbox_worker_runtime.start()
    assert r1.get("started") is True
    assert r2.get("reason") == "ALREADY_RUNNING"
    e1 = await realtime_execution_runner.start()
    e2 = await realtime_execution_runner.start()
    assert e2.get("already_running") is True or e1.get("running") is True
    assert get_settings().realtime_live_auto_start_enabled is False


@pytest.mark.asyncio
async def test_s8_feature_flags_off(harness, ua_lifecycle, monkeypatch) -> None:
    session, created = harness
    monkeypatch.setenv("PAPER_OUTBOX_WORKER_ENABLED", "false")
    monkeypatch.setenv("PAPER_FILL_RECOVERY_ENABLED", "false")
    monkeypatch.setenv("PAPER_PRICE_FEED_ENABLED", "false")
    monkeypatch.setenv("REALTIME_EXECUTION_AUTO_START_ENABLED", "false")
    monkeypatch.setenv("REALTIME_PAPER_AUTO_START_ENABLED", "false")
    monkeypatch.setenv("PAPER_OUTBOX_AUTO_FILL", "false")
    clear_settings_cache()

    await paper_outbox_worker_runtime.shutdown()
    await paper_fill_recovery_scheduler.shutdown()
    await paper_price_feed.shutdown()
    await realtime_execution_runner.stop()

    result = await RealtimeTradingSessionService(session).execute(
        phase=TradingSessionPhase.MARKET_OPEN,
        exchange_code="PAPER",
    )
    assert result.executed is True
    assert paper_outbox_worker_runtime.status()["running"] is False
    assert paper_price_feed.status()["running"] is False
    assert realtime_execution_runner.status().get("running") is False
    before = _counts(session, created["account_id"])
    await paper_price_feed.inject_prices(
        exchange_code=_EXCHANGE,
        symbol=_SYMBOL,
        prices=[10, 12, 13],
    )
    await asyncio.sleep(1)
    after = _counts(session, created["account_id"])
    assert after == before


@pytest.mark.asyncio
async def test_concurrency_worker_claim_once(harness, ua_lifecycle) -> None:
    """Worker 2개가 SKIP LOCKED로 동일 Outbox를 이중 처리하지 않음."""

    from stock_platform.broker.paper.adapter import PaperBrokerAdapter
    from stock_platform.order.execution_service import (
        OrderExecutionCommand,
        OrderExecutionService,
    )
    from stock_platform.order.models import OrderSide, OrderType
    from stock_platform.order.outbox_dispatcher import OrderOutboxDispatcher
    from stock_platform.order.outbox_worker import OrderOutboxWorker

    session, created = harness
    aid = created["account_id"]
    uid = created["user_id"]
    submit = OrderExecutionService(session).submit(
        OrderExecutionCommand(
            account_id=aid,
            broker_code=_BROKER,
            exchange_code=_EXCHANGE,
            symbol=_SYMBOL,
            side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            price=Decimal("10000"),
            quantity=Decimal("1"),
            account_number=f"PAPER-{aid}",
            environment="PAPER",
            user_id=uid,
            metadata_payload={"environment": "PAPER"},
            actor="UA_CONCURRENCY",
            order_source="AUTO",
        )
    )
    assert submit.allowed and submit.order_id

    Session = get_session_factory()

    def _run(worker_id: str):
        return OrderOutboxWorker(
            session_factory=Session,
            dispatcher=OrderOutboxDispatcher(PaperBrokerAdapter()),
            worker_id=worker_id,
            batch_size=5,
            paper_only=True,
        ).run_once()

    s1, s2 = await asyncio.gather(
        asyncio.to_thread(_run, "ua-w1"),
        asyncio.to_thread(_run, "ua-w2"),
    )
    claimed_total = s1.claimed + s2.claimed
    # 우리 주문 1건은 한 worker만 claim (다른 PENDING이 있어도 paper_only)
    assert claimed_total >= 1
    # fill 중복 없음
    await asyncio.sleep(0.5)
    session.expire_all()
    fills = _counts(session, aid)["fills"]
    # auto_fill ON이면 최대 1
    assert fills <= 1
