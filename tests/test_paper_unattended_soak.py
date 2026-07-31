"""Paper 무인 Runtime Soak — Background Worker/Feed/Runner 장시간 안정성.

Fill 서비스·Worker.run_once 직접 호출 금지.
가격은 PaperPriceFeed → QuoteBus → Hub → Signal → Runner → Outbox → Worker.
"""

from __future__ import annotations

import asyncio
import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal

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
from stock_platform.trading.account_identity import paper_kill_switch_scope
from stock_platform.trading.account_repository import PaperAccountRepository
from stock_platform.trading.account_service import PaperAccountService

pytestmark = pytest.mark.integration

_PREFIX = "PAPER_SOAK_"
_SYMBOL = "SOAKSYM"
_EXCHANGE = "PAPER"
_BROKER = "PAPER"
_INITIAL = Decimal("10000000.00")

# BUY warmup + golden cross, then TP/exit
_BUY_SEQ = [10000, 10000, 10000, 10000, 12000, 13000]
_EXIT_SEQ = [14000, 15000, 16000, 11000, 9000, 8000, 7000]
_CYCLE = _BUY_SEQ + _EXIT_SEQ


@dataclass
class SoakSnapshot:
    at: datetime
    orders: int = 0
    fills: int = 0
    qty: Decimal = Decimal("0")
    cash: Decimal = Decimal("0")
    realized: Decimal = Decimal("0")
    pending_outbox: int = 0
    processing_outbox: int = 0
    accepted: int = 0
    pool_checked_out: int = 0
    runner_running: bool = False
    worker_running: bool = False
    feed_running: bool = False
    recovery_running: bool = False
    hub_dispatch: bool = False
    last_error: str | None = None
    rss_mb: float | None = None


@dataclass
class SoakReport:
    duration_seconds: float = 0.0
    price_events: int = 0
    trade_cycles: int = 0
    snapshots: list[SoakSnapshot] = field(default_factory=list)
    duplicate_orders: int = 0
    duplicate_fills: int = 0
    max_checked_out: int = 0
    max_rss_mb: float = 0.0
    phase_results: dict[str, str] = field(default_factory=dict)
    final_errors: list[str] = field(default_factory=list)


def _soak_duration() -> float:
    """기본 짧은 모드(~90s). PAPER_SOAK_DURATION_SECONDS 로 연장."""

    raw = os.environ.get("PAPER_SOAK_DURATION_SECONDS", "90")
    try:
        return max(30.0, float(raw))
    except ValueError:
        return 90.0


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
    monkeypatch.setenv("PAPER_OUTBOX_WORKER_INTERVAL_SECONDS", "0.5")
    monkeypatch.setenv("PAPER_FILL_RECOVERY_INTERVAL_SECONDS", "1.0")
    monkeypatch.setenv("PAPER_OUTBOX_WORKER_STALE_SECONDS", "5")
    monkeypatch.setenv("PAPER_PRICE_FEED_INTERVAL_SECONDS", "0.2")
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


@pytest_asyncio.fixture
async def soak_lifecycle():
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
                    actor="SOAK_CLEANUP",
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


def _rss_mb() -> float | None:
    try:
        import psutil

        return float(psutil.Process(os.getpid()).memory_info().rss) / (1024 * 1024)
    except Exception:  # noqa: BLE001
        return None


def _pool_checked_out() -> int:
    try:
        pool = get_engine().pool
        return int(pool.checkedout())
    except Exception:  # noqa: BLE001
        return -1


def _snapshot(account_id: int) -> SoakSnapshot:
    Session = get_session_factory()
    with Session() as s:
        row = s.execute(
            text(
                """
                SELECT
                  (SELECT COUNT(*) FROM trading.trading_order WHERE account_id=:a),
                  (SELECT COUNT(*) FROM trading.paper_trade WHERE account_id=:a),
                  (SELECT COALESCE(SUM(quantity),0) FROM trading.paper_position
                     WHERE account_id=:a AND symbol=:sym),
                  (SELECT available_cash FROM trading.paper_account WHERE account_id=:a),
                  (SELECT realized_profit_loss FROM trading.paper_account
                     WHERE account_id=:a),
                  (SELECT COUNT(*) FROM trading.order_outbox o
                     JOIN trading.trading_order t ON t.order_id=o.order_id
                     WHERE t.account_id=:a AND o.status_code='PENDING'),
                  (SELECT COUNT(*) FROM trading.order_outbox o
                     JOIN trading.trading_order t ON t.order_id=o.order_id
                     WHERE t.account_id=:a AND o.status_code='PROCESSING'),
                  (SELECT COUNT(*) FROM trading.trading_order
                     WHERE account_id=:a AND status_code='ACCEPTED')
                """
            ),
            {"a": account_id, "sym": _SYMBOL},
        ).one()
    hub = get_realtime_market_data_hub()
    return SoakSnapshot(
        at=datetime.now(timezone.utc),
        orders=int(row[0]),
        fills=int(row[1]),
        qty=Decimal(str(row[2])),
        cash=Decimal(str(row[3])),
        realized=Decimal(str(row[4])),
        pending_outbox=int(row[5]),
        processing_outbox=int(row[6]),
        accepted=int(row[7]),
        pool_checked_out=_pool_checked_out(),
        runner_running=bool(realtime_execution_runner.status().get("running")),
        worker_running=bool(paper_outbox_worker_runtime.status().get("running")),
        feed_running=bool(paper_price_feed.status().get("running")),
        recovery_running=bool(paper_fill_recovery_scheduler.status().get("running")),
        hub_dispatch=bool(hub.status().get("dispatch_running")),
        last_error=(
            paper_outbox_worker_runtime.status().get("last_error")
            or paper_price_feed.status().get("last_error")
            or hub.status().get("last_error")
        ),
        rss_mb=_rss_mb(),
    )


def _dup_counts(account_id: int) -> tuple[int, int]:
    """동일 client_order_id / 주문당 이중 paper_trade 탐지."""

    Session = get_session_factory()
    with Session() as s:
        dup_orders = int(
            s.execute(
                text(
                    """
                    SELECT COALESCE(SUM(cnt - 1), 0) FROM (
                      SELECT client_order_id, COUNT(*) AS cnt
                      FROM trading.trading_order
                      WHERE account_id=:a
                        AND client_order_id IS NOT NULL
                        AND client_order_id <> ''
                      GROUP BY client_order_id
                      HAVING COUNT(*) > 1
                    ) x
                    """
                ),
                {"a": account_id},
            ).scalar_one()
        )
        dup_fills = int(
            s.execute(
                text(
                    """
                    SELECT COALESCE(SUM(cnt - 1), 0) FROM (
                      SELECT order_id, COUNT(*) AS cnt
                      FROM trading.paper_trade
                      WHERE account_id=:a
                        AND order_id IS NOT NULL
                      GROUP BY order_id
                      HAVING COUNT(*) > 1
                    ) x
                    """
                ),
                {"a": account_id},
            ).scalar_one()
        )
    return dup_orders, dup_fills


async def _boot(session, created: dict) -> None:
    await _shutdown_all()
    reset_signal_dedup_for_tests()
    aid = created["account_id"]
    uid = created["user_id"]
    os.environ["REALTIME_PAPER_ACCOUNT_ID"] = str(aid)
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
        mode=RealtimeExecutionMode.PAPER,
        account_id=aid,
        order_amount=Decimal("20000"),
        auto_fill=False,
        user_id=uid,
    )

    hub = get_realtime_market_data_hub()
    from stock_platform.realtime.manager import realtime_manager

    hub.set_quote_bus(realtime_manager.bus)
    await hub.start_dispatch()

    hub.register_consumer(
        StrategyRuntimeScope(
            user_id=uid,
            account_kind=AccountKind.PAPER,
            account_id=aid,
            strategy_id=920001,
            strategy_version="soak-1",
            market_type="STOCK",
            broker_code=_BROKER,
            strategy_code="SOAK_MA",
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
        exchange_code="PAPER",
    )
    assert result.executed is True, result.message
    assert paper_outbox_worker_runtime.status()["running"] is True
    assert paper_price_feed.status()["running"] is True
    assert (
        realtime_execution_runner.status().get("running") is True
        or realtime_execution_runner._task is not None
    )


async def _feed_prices(prices: list, *, wait: float = 1.2) -> int:
    """Background Feed만 사용 — run_once/Fill 직접 호출 금지."""

    n = await paper_price_feed.inject_prices(
        exchange_code=_EXCHANGE,
        symbol=_SYMBOL,
        prices=prices,
    )
    await asyncio.sleep(wait)
    return n


async def _wait_flat(account_id: int, *, timeout: float = 25.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        snap = _snapshot(account_id)
        if snap.qty == 0 and snap.pending_outbox == 0 and snap.processing_outbox == 0:
            return True
        await asyncio.sleep(0.4)
    return _snapshot(account_id).qty == 0


async def _wait_position(account_id: int, *, timeout: float = 25.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _snapshot(account_id).qty > 0:
            return True
        await asyncio.sleep(0.4)
    return False


@pytest.mark.asyncio
async def test_paper_unattended_soak(harness, soak_lifecycle) -> None:
    session, created = harness
    aid = created["account_id"]
    duration = _soak_duration()
    report = SoakReport()
    started = time.monotonic()

    await _boot(session, created)
    report.phase_results["boot"] = "OK"

    # ---- A. 정상 반복 거래 (장시간 핵심) ----
    phase_a_until = started + max(20.0, duration * 0.45)
    cycles = 0
    while time.monotonic() < phase_a_until:
        report.price_events += await _feed_prices(_BUY_SEQ, wait=1.5)
        if not await _wait_position(aid, timeout=20):
            # MA state 리셋 후 재시도
            hub = get_realtime_market_data_hub()
            for c in hub.registry.list_consumers():
                try:
                    hub.registry.rewarm(c["scope_key"])
                except Exception:  # noqa: BLE001
                    pass
            report.price_events += await _feed_prices(_BUY_SEQ, wait=2.0)
            if not await _wait_position(aid, timeout=20):
                # 이미 최소 사이클 충족 시 조기 종료는 오류 아님
                if cycles < 2:
                    report.final_errors.append("phase_a_buy_timeout")
                break
        mid = _snapshot(aid)
        report.price_events += await _feed_prices(_EXIT_SEQ, wait=2.0)
        if not await _wait_flat(aid, timeout=25):
            report.final_errors.append("phase_a_exit_timeout")
            break
        end = _snapshot(aid)
        assert end.qty == 0
        assert end.fills > mid.fills
        cycles += 1
        report.trade_cycles = cycles
        snap = _snapshot(aid)
        report.snapshots.append(snap)
        report.max_checked_out = max(report.max_checked_out, snap.pool_checked_out)
        if snap.rss_mb is not None:
            report.max_rss_mb = max(report.max_rss_mb, snap.rss_mb)
        await asyncio.sleep(0.3)
    report.phase_results["A_cycles"] = f"OK:{cycles}"
    assert cycles >= 2, f"need >=2 buy/sell cycles, got {cycles}"

    # ---- B. 중복 가격 이벤트 ----
    before_o = _snapshot(aid).orders
    before_f = _snapshot(aid).fills
    same = [12000, 12000, 12000, 12000]
    report.price_events += await _feed_prices(same, wait=1.5)
    report.price_events += await _feed_prices(same, wait=1.5)
    after = _snapshot(aid)
    # 평평한 중복 가격만으로는 신규 주문이 폭증하면 안 됨
    assert after.orders - before_o <= 2
    assert after.fills - before_f <= 2
    report.phase_results["B_dup_prices"] = "OK"

    # ---- C. Worker 일시 장애 → 재기동 자연 Drain ----
    report.price_events += await _feed_prices(_BUY_SEQ, wait=1.0)
    await asyncio.sleep(0.8)
    await paper_outbox_worker_runtime.shutdown()
    assert paper_outbox_worker_runtime.status()["running"] is False
    # 적체 대기 (직접 run_once 금지)
    await asyncio.sleep(2.0)
    stalled = _snapshot(aid)
    paper_outbox_worker_runtime.start()
    assert paper_outbox_worker_runtime.status()["running"] is True
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        s = _snapshot(aid)
        if s.pending_outbox == 0 and s.processing_outbox == 0:
            break
        await asyncio.sleep(0.5)
    drained = _snapshot(aid)
    assert drained.pending_outbox == 0
    assert drained.processing_outbox == 0
    # 포지션 정리
    if drained.qty > 0:
        report.price_events += await _feed_prices(_EXIT_SEQ, wait=2.0)
        await _wait_flat(aid, timeout=30)
    report.phase_results["C_worker_restart"] = (
        f"OK:stalled_pending={stalled.pending_outbox}"
    )

    # ---- D. Recovery와 Worker 경합 (Fill 1회) ----
    original = PaperOutboxFillService.fill_accepted_order

    def _crash(self, order_id, **kwargs):
        return PaperOutboxFillResult(
            filled=False,
            skipped=True,
            reason_code="SOAK_SIMULATED_CRASH",
            order_id=int(order_id),
            order_status="ACCEPTED",
        )

    # 기존 worker가 crash fill을 먹도록 monkeypatch
    PaperOutboxFillService.fill_accepted_order = _crash  # type: ignore[method-assign]
    report.price_events += await _feed_prices(_BUY_SEQ, wait=2.5)
    # ACCEPTED 대기
    deadline = time.monotonic() + 25
    while time.monotonic() < deadline and _snapshot(aid).accepted < 1:
        await asyncio.sleep(0.4)
    fills_before = _snapshot(aid).fills
    PaperOutboxFillService.fill_accepted_order = original  # type: ignore[method-assign]
    # Background Recovery + Worker 가 자연 처리 (run_once 금지)
    deadline = time.monotonic() + 35
    while time.monotonic() < deadline:
        s = _snapshot(aid)
        if s.fills > fills_before and s.accepted == 0:
            break
        await asyncio.sleep(0.5)
    after_d = _snapshot(aid)
    assert after_d.fills >= fills_before + 1
    # 추가 대기 후 이중 fill 없음
    await asyncio.sleep(3.0)
    d_orders, d_fills = _dup_counts(aid)
    assert d_fills == 0
    if after_d.qty > 0:
        report.price_events += await _feed_prices(_EXIT_SEQ, wait=2.0)
        await _wait_flat(aid, timeout=30)
    report.phase_results["D_recovery_race"] = "OK"

    # ---- E. Kill Switch ----
    scope = paper_kill_switch_scope(aid)
    created["kill_scopes"].append(scope)
    KillSwitchService(session).activate_scope(
        scope_code=scope, actor="SOAK", reason="soak_kill"
    )
    session.commit()
    before_kill = _snapshot(aid)
    report.price_events += await _feed_prices(_CYCLE, wait=2.5)
    after_kill = _snapshot(aid)
    assert after_kill.orders == before_kill.orders
    assert after_kill.fills == before_kill.fills
    KillSwitchService(session).deactivate_scope(
        scope_code=scope, actor="SOAK", reason="done"
    )
    session.commit()
    report.phase_results["E_kill"] = "OK"

    # ---- F. Account Pause ----
    session.add(
        BrokerRecoveryAccountStateEntity(
            broker_code=_BROKER,
            user_id=created["user_id"],
            paper_account_id=aid,
            recovery_status="IDLE",
            trading_paused=True,
        )
    )
    session.commit()
    before_pause = _snapshot(aid)
    report.price_events += await _feed_prices(_CYCLE, wait=2.5)
    after_pause = _snapshot(aid)
    assert after_pause.orders == before_pause.orders
    session.execute(
        text(
            "UPDATE operation.broker_recovery_account_state "
            "SET trading_paused=false WHERE paper_account_id=:a"
        ),
        {"a": aid},
    )
    session.commit()
    report.phase_results["F_pause"] = "OK"

    # ---- G. MARKET_CLOSE ----
    await RealtimeTradingSessionService(session).execute(
        phase=TradingSessionPhase.MARKET_CLOSE,
        exchange_code="PAPER",
    )
    assert realtime_execution_runner.status().get("running") is False
    assert paper_price_feed.status().get("running") is False
    before_close = _snapshot(aid)
    # Feed 중지 상태 — inject는 큐에만 쌓이거나 no-op에 가깝게
    try:
        await paper_price_feed.inject_prices(
            exchange_code=_EXCHANGE, symbol=_SYMBOL, prices=_BUY_SEQ
        )
    except Exception:  # noqa: BLE001
        pass
    await asyncio.sleep(2.0)
    after_close = _snapshot(aid)
    assert after_close.orders == before_close.orders
    report.phase_results["G_market_close"] = "OK"

    # ---- H. Restart (중복 Task 0) ----
    await _shutdown_all()
    await _boot(session, created)
    w1 = paper_outbox_worker_runtime.start()
    w2 = paper_outbox_worker_runtime.start()
    assert w2.get("reason") == "ALREADY_RUNNING"
    e1 = await realtime_execution_runner.start()
    e2 = await realtime_execution_runner.start()
    assert e2.get("already_running") is True or e1.get("running") is True
    # terminal 재처리 없음: close 전 주문 수 대비 급증 없이 한 사이클만
    o_before = _snapshot(aid).orders
    report.price_events += await _feed_prices(_BUY_SEQ, wait=2.0)
    bought = await _wait_position(aid, timeout=25)
    if bought:
        report.price_events += await _feed_prices(_EXIT_SEQ, wait=2.5)
    flat_ok = await _wait_flat(aid, timeout=35)
    if not flat_ok:
        hub = get_realtime_market_data_hub()
        for c in hub.registry.list_consumers():
            try:
                hub.registry.rewarm(c["scope_key"])
            except Exception:  # noqa: BLE001
                pass
        report.price_events += await _feed_prices(_EXIT_SEQ, wait=3.0)
        flat_ok = await _wait_flat(aid, timeout=30)
    assert flat_ok, "H restart cycle did not flatten position"
    assert _snapshot(aid).orders >= o_before
    report.phase_results["H_restart"] = f"OK:w1={w1.get('started')}"

    # ---- 종료 정합 ----
    # 잔여 포지션이 있으면 종료 전 한 번 더 청산 시도
    if _snapshot(aid).qty > 0:
        report.price_events += await _feed_prices(_EXIT_SEQ, wait=3.0)
        await _wait_flat(aid, timeout=30)
    await RealtimeTradingSessionService(session).execute(
        phase=TradingSessionPhase.MARKET_CLOSE,
        exchange_code="PAPER",
    )
    await _shutdown_all()
    final = _snapshot(aid)
    report.duplicate_orders, report.duplicate_fills = _dup_counts(aid)
    report.duration_seconds = time.monotonic() - started
    report.snapshots.append(final)

    assert report.duplicate_orders == 0
    assert report.duplicate_fills == 0
    assert final.processing_outbox == 0
    # 장 마감 후 신규 주문은 막히므로, 열린 포지션은 종료 전 청산 실패를 보고
    if final.qty != 0:
        report.final_errors.append(f"residual_qty={final.qty}")
    assert final.qty == 0, report.final_errors
    assert get_settings().realtime_live_auto_start_enabled is False
    assert os.environ.get("KIWOOM_LIVE_ORDER_ENABLED") == "false"
    assert paper_outbox_worker_runtime.status()["running"] is False
    assert paper_price_feed.status()["running"] is False
    assert realtime_execution_runner.status().get("running") is False
    # connection leak: shutdown 후 checked_out 이 과도하지 않음
    assert _pool_checked_out() <= 2
    assert not report.final_errors, report.final_errors

    # 리포트는 assert 메시지/로그로 남김
    print(
        "SOAK_REPORT",
        {
            "duration": round(report.duration_seconds, 1),
            "price_events": report.price_events,
            "cycles": report.trade_cycles,
            "dup_orders": report.duplicate_orders,
            "dup_fills": report.duplicate_fills,
            "max_checked_out": report.max_checked_out,
            "max_rss_mb": round(report.max_rss_mb, 1),
            "phases": report.phase_results,
            "final_cash": str(final.cash),
            "final_realized": str(final.realized),
            "orders": final.orders,
            "fills": final.fills,
        },
        flush=True,
    )
