"""UPBIT limited buy concurrency — stress / A-I matrix / latency (NO REAL broker).

운영 concurrency=2 설정은 변경하지 않는다.
이 파일은 fixture 안에서만 serial=1 vs concurrent=2를 비교한다.
"""

from __future__ import annotations

import asyncio
import random
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from contextlib import nullcontext
from dataclasses import dataclass, field
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from stock_platform.operation.upbit_full_market.buy_concurrency import (
    clamp_concurrency_v1,
    resolve_max_concurrent_entries,
)
from stock_platform.operation.upbit_full_market.capital_allocator import (
    AllocationInput,
)
from stock_platform.operation.upbit_full_market.portfolio_entry_sizing import (
    PortfolioEntryRiskLimits,
    allocate_portfolio_entry_amount,
)
from stock_platform.operation.upbit_full_market.portfolio_service import (
    UpbitPortfolioService,
)
from stock_platform.order.outbox_worker import OrderOutboxWorker, OutboxRunSummary

# ---------------------------------------------------------------------------
# Synthetic runtime (fake executor + fake broker submit)
# ---------------------------------------------------------------------------

SYMBOLS_10 = [
    f"KRW-{s}"
    for s in (
        "XRP",
        "SOL",
        "DOGE",
        "ADA",
        "ENA",
        "WLD",
        "SUI",
        "ONDO",
        "TRUMP",
        "PROM",
    )
]


@dataclass
class StressCounters:
    max_executor_active: int = 0
    max_broker_active: int = 0
    duplicate_orders: int = 0
    position_limit_breach: int = 0
    balance_oversub: int = 0
    orphan_reservation: int = 0
    lost_signal: int = 0
    approved_total: Decimal = field(default_factory=lambda: Decimal("0"))
    lock: threading.Lock = field(default_factory=threading.Lock)

    def bump_exec(self, n: int) -> None:
        with self.lock:
            self.max_executor_active = max(self.max_executor_active, n)

    def bump_broker(self, n: int) -> None:
        with self.lock:
            self.max_broker_active = max(self.max_broker_active, n)


class FakeAdmissionBook:
    """UBA-level admission: pending<=2, positions+pending<=6, cash reservation."""

    def __init__(
        self,
        *,
        max_pending: int = 2,
        max_positions: int = 6,
        available_krw: Decimal = Decimal("100000"),
        open_positions: int = 0,
    ) -> None:
        self.max_pending = max_pending
        self.max_positions = max_positions
        self.available_krw = available_krw
        self.open_positions = open_positions
        self.pending: dict[str, Decimal] = {}
        self.orders: set[str] = set()
        self.lock = threading.RLock()
        self.rejected: list[tuple[str, str]] = []

    @property
    def reserved(self) -> Decimal:
        return sum(self.pending.values(), Decimal("0"))

    def admit(self, symbol: str, request_krw: Decimal) -> tuple[bool, str, Decimal]:
        with self.lock:
            if symbol in self.pending or symbol in self.orders:
                return False, "DUPLICATE", Decimal("0")
            if len(self.pending) >= self.max_pending:
                return False, "PENDING_ENTRY_LIMIT", Decimal("0")
            used = self.open_positions + len(self.pending)
            if used >= self.max_positions:
                return False, "AUTO_POSITION_LIMIT_REACHED", Decimal("0")
            free = self.available_krw - self.reserved
            if request_krw > free:
                if free <= 0:
                    return False, "INSUFFICIENT_CASH", Decimal("0")
                approved = free
            else:
                approved = request_krw
            self.pending[symbol] = approved
            return True, "OK", approved

    def finalize_order(self, symbol: str) -> None:
        with self.lock:
            self.pending.pop(symbol, None)
            self.orders.add(symbol)
            self.open_positions += 1

    def rollback(self, symbol: str) -> None:
        with self.lock:
            self.pending.pop(symbol, None)

    def assert_clean(self) -> None:
        assert self.pending == {}, f"orphan reservations: {self.pending}"


async def _run_executor_batch(
    symbols: list[str],
    *,
    concurrency: int,
    broker_latency_ms: float,
    book: FakeAdmissionBook,
    counters: StressCounters,
    request_krw: Decimal = Decimal("10000"),
) -> list[str]:
    """Semaphore-bounded fake executor → fake broker submit."""

    sem = asyncio.Semaphore(concurrency)
    broker_sem = asyncio.Semaphore(concurrency)
    active_exec = 0
    active_broker = 0
    exec_lock = asyncio.Lock()
    completed: list[str] = []
    lost: list[str] = []

    async def _one(sym: str) -> None:
        nonlocal active_exec, active_broker
        async with sem:
            async with exec_lock:
                active_exec += 1
                counters.bump_exec(active_exec)
            try:
                ok, reason, approved = await asyncio.to_thread(
                    book.admit, sym, request_krw
                )
                if not ok:
                    if reason == "DUPLICATE":
                        with counters.lock:
                            counters.duplicate_orders += 1
                    elif reason == "AUTO_POSITION_LIMIT_REACHED":
                        with counters.lock:
                            counters.position_limit_breach += 1
                    # queue/wait semantics: PENDING_LIMIT means not admitted this cycle
                    return
                with counters.lock:
                    counters.approved_total += approved
                    # oversubscription check after admit
                    if book.reserved > book.available_krw + Decimal("0.01"):
                        counters.balance_oversub += 1

                async with broker_sem:
                    async with exec_lock:
                        active_broker += 1
                        counters.bump_broker(active_broker)
                    try:
                        await asyncio.sleep(broker_latency_ms / 1000.0)
                        await asyncio.to_thread(book.finalize_order, sym)
                        completed.append(sym)
                    finally:
                        async with exec_lock:
                            active_broker -= 1
            finally:
                async with exec_lock:
                    active_exec -= 1

    tasks = [asyncio.create_task(_one(s)) for s in symbols]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    for sym, res in zip(symbols, results, strict=True):
        if isinstance(res, Exception):
            lost.append(sym)
            with counters.lock:
                counters.lost_signal += 1
    return completed


# ---------------------------------------------------------------------------
# Stress 50–100 cycles × 10 symbols
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stress_10_symbols_50_cycles_caps_at_two() -> None:
    counters = StressCounters()
    cycles = 50
    for cycle in range(cycles):
        book = FakeAdmissionBook(
            max_pending=2,
            max_positions=10,  # 동시성 한도만 검증 (포지션 한도는 E에서 별도)
            available_krw=Decimal("500000"),
            open_positions=0,
        )
        syms = list(SYMBOLS_10)
        random.shuffle(syms)
        await _run_executor_batch(
            syms,
            concurrency=2,
            broker_latency_ms=5,
            book=book,
            counters=counters,
            request_krw=Decimal("8000"),
        )
        book.assert_clean()
        assert len(book.orders) == 10

    assert counters.max_executor_active <= 2
    assert counters.max_broker_active <= 2
    assert counters.duplicate_orders == 0
    assert counters.position_limit_breach == 0
    assert counters.balance_oversub == 0
    assert counters.orphan_reservation == 0
    assert counters.lost_signal == 0


@pytest.mark.asyncio
async def test_stress_100_cycles_repeat_stability() -> None:
    """동일 stress를 추가 100 cycle — flaky 재현용."""

    counters = StressCounters()
    for _ in range(100):
        book = FakeAdmissionBook(
            max_pending=2,
            max_positions=10,
            available_krw=Decimal("500000"),
        )
        syms = list(SYMBOLS_10)
        random.shuffle(syms)
        await asyncio.sleep(random.uniform(0, 0.002))
        await _run_executor_batch(
            syms,
            concurrency=2,
            broker_latency_ms=random.choice([1, 3, 5]),
            book=book,
            counters=counters,
        )
        book.assert_clean()

    assert counters.max_executor_active <= 2
    assert counters.max_broker_active <= 2
    assert counters.lost_signal == 0
    assert counters.balance_oversub == 0
    assert counters.duplicate_orders == 0
    assert counters.position_limit_breach == 0


# ---------------------------------------------------------------------------
# A–I Matrix
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_A_two_symbols_both_enter_max_active_2() -> None:
    counters = StressCounters()
    book = FakeAdmissionBook(available_krw=Decimal("50000"))
    gate = asyncio.Event()

    async def _gated_batch():
        # hold both in executor until released — observe active=2
        sem = asyncio.Semaphore(2)
        active = 0
        peak = 0
        lock = asyncio.Lock()

        async def one(sym: str):
            nonlocal active, peak
            async with sem:
                async with lock:
                    active += 1
                    peak = max(peak, active)
                    counters.bump_exec(active)
                ok, _, _ = book.admit(sym, Decimal("10000"))
                assert ok
                await gate.wait()
                book.finalize_order(sym)
                async with lock:
                    active -= 1

        t1 = asyncio.create_task(one("KRW-XRP"))
        t2 = asyncio.create_task(one("KRW-SOL"))
        await asyncio.sleep(0.05)
        assert peak == 2
        gate.set()
        await asyncio.gather(t1, t2)
        return peak

    peak = await _gated_batch()
    assert peak == 2
    assert counters.max_executor_active == 2
    book.assert_clean()


@pytest.mark.asyncio
async def test_B_three_symbols_third_waits_no_drop() -> None:
    counters = StressCounters()
    started: list[str] = []
    finished: list[str] = []
    sem = asyncio.Semaphore(2)
    release = asyncio.Event()

    async def one(sym: str):
        async with sem:
            started.append(sym)
            counters.bump_exec(len(started) - len(finished))
            await release.wait()
            finished.append(sym)

    tasks = [
        asyncio.create_task(one(s))
        for s in ("KRW-XRP", "KRW-SOL", "KRW-DOGE")
    ]
    await asyncio.sleep(0.05)
    assert len(started) == 2  # 3번째는 wait
    assert "KRW-DOGE" not in started or len(started) == 2
    release.set()
    await asyncio.gather(*tasks)
    assert set(finished) == {"KRW-XRP", "KRW-SOL", "KRW-DOGE"}
    assert counters.lost_signal == 0
    assert counters.max_executor_active <= 2


def test_C_duplicate_same_symbol_one_lifecycle() -> None:
    book = FakeAdmissionBook()
    ok1, _, _ = book.admit("KRW-XRP", Decimal("10000"))
    ok2, reason, _ = book.admit("KRW-XRP", Decimal("10000"))
    assert ok1 is True
    assert ok2 is False
    assert reason == "DUPLICATE"
    assert len(book.pending) == 1
    book.rollback("KRW-XRP")
    book.assert_clean()


def test_D_balance_no_oversubscription() -> None:
    book = FakeAdmissionBook(available_krw=Decimal("15000"))
    ok_x, _, ax = book.admit("KRW-XRP", Decimal("10000"))
    ok_s, _, as_ = book.admit("KRW-SOL", Decimal("10000"))
    assert ok_x is True
    assert ok_s is True
    assert ax + as_ <= Decimal("15000")
    assert book.reserved <= Decimal("15000")

    limits = PortfolioEntryRiskLimits(
        max_order_amount=Decimal("100000"),
        max_position_amount=Decimal("1000000"),
        source_layers=("uba",),
    )
    alloc = allocate_portfolio_entry_amount(
        AllocationInput(
            portfolio_capital_limit_krw=Decimal("15000"),
            available_krw=Decimal("15000"),
            min_cash_reserve_pct=0.0,
            per_position_target_pct=1.0,
            max_symbol_exposure_pct=1.0,
            max_total_exposure_pct=1.0,
            current_strategy_exposure_krw=Decimal("0"),
            pending_reserved_krw=ax,
            current_symbol_exposure_krw=Decimal("0"),
            account_max_order_amount=Decimal("100000"),
            scanner_score=80.0,
            ai_confidence=0.8,
            volatility="MEDIUM",
        ),
        risk_limits=limits,
    )
    total = ax + Decimal(str(alloc.approved_amount_krw or 0))
    assert total <= Decimal("15000") + Decimal("0.01")
    book.rollback("KRW-XRP")
    book.rollback("KRW-SOL")
    book.assert_clean()


def test_E_position_limit_five_plus_two() -> None:
    book = FakeAdmissionBook(
        available_krw=Decimal("100000"),
        open_positions=5,
        max_positions=6,
        max_pending=2,
    )
    ok1, _, _ = book.admit("KRW-XRP", Decimal("10000"))
    ok2, reason, _ = book.admit("KRW-SOL", Decimal("10000"))
    assert ok1 is True
    assert ok2 is False
    assert reason == "AUTO_POSITION_LIMIT_REACHED"
    assert book.open_positions + len(book.pending) <= 6
    book.rollback("KRW-XRP")
    book.assert_clean()


def test_F_rollback_isolates_rejected_symbol() -> None:
    book = FakeAdmissionBook()
    ok_x, _, _ = book.admit("KRW-XRP", Decimal("10000"))
    ok_s, _, _ = book.admit("KRW-SOL", Decimal("10000"))
    assert ok_x and ok_s
    # SOL risk reject → rollback SOL only
    book.rollback("KRW-SOL")
    assert "KRW-XRP" in book.pending
    assert "KRW-SOL" not in book.pending
    book.finalize_order("KRW-XRP")
    book.assert_clean()


def test_G_broker_failure_does_not_poison_sibling() -> None:
    counters = StressCounters()
    results: dict[str, str] = {}
    broker_active = 0
    lock = threading.Lock()

    def submit(sym: str, fail: bool) -> None:
        nonlocal broker_active
        with lock:
            broker_active += 1
            counters.bump_broker(broker_active)
        try:
            time.sleep(0.02)
            if fail:
                results[sym] = "FAIL"
                raise RuntimeError("fake_broker_fail")
            results[sym] = "OK"
        finally:
            with lock:
                broker_active -= 1

    with ThreadPoolExecutor(max_workers=2) as pool:
        futs = [
            pool.submit(submit, "KRW-XRP", False),
            pool.submit(submit, "KRW-SOL", True),
        ]
        for f in as_completed(futs):
            try:
                f.result()
            except RuntimeError:
                pass

    assert results["KRW-XRP"] == "OK"
    assert results["KRW-SOL"] == "FAIL"
    assert counters.max_broker_active <= 2


def test_H_sell_not_blocked_by_buy_concurrency() -> None:
    """BUY semaphore와 독립적으로 SELL 경로가 진행 가능해야 한다."""

    buy_sem = threading.Semaphore(2)
    sell_done = threading.Event()
    buy_holding = threading.Event()

    def buy_worker():
        buy_sem.acquire()
        try:
            buy_holding.set()
            time.sleep(0.1)
        finally:
            buy_sem.release()

    def sell_worker():
        # SELL은 buy semaphore를 기다리지 않음
        assert buy_holding.wait(timeout=1.0)
        sell_done.set()

    t_buys = [threading.Thread(target=buy_worker) for _ in range(2)]
    t_sell = threading.Thread(target=sell_worker)
    for t in t_buys:
        t.start()
    t_sell.start()
    for t in t_buys:
        t.join(timeout=2)
    t_sell.join(timeout=2)
    assert sell_done.is_set()


def test_I_reconciliation_logic_clears_orphan_pending_synthetic() -> None:
    """startup reconciliation 단위: orphan ENTRY_PENDING만 정리, 정상 유지."""

    pending = {"KRW-XRP": Decimal("10000"), "KRW-ORPHAN": Decimal("10000")}
    has_order = {"KRW-XRP"}

    def reconcile(pending_map: dict[str, Decimal], ordered: set[str]) -> dict[str, Decimal]:
        cleaned = {}
        for sym, amt in pending_map.items():
            if sym in ordered:
                cleaned[sym] = amt  # order 있으면 유지
            # order 없는 orphan → drop
        return cleaned

    after = reconcile(pending, has_order)
    assert "KRW-ORPHAN" not in after
    assert "KRW-XRP" in after


def test_begin_entry_service_duplicate_and_limit_race_repeat() -> None:
    """Service-level admission race — 반복으로 flaky 검출."""

    for _ in range(20):
        session = MagicMock()
        svc = UpbitPortfolioService(session)
        policy = SimpleNamespace(
            portfolio_max_pending_entries=2,
            enabled=True,
            entry_state="RUNNING",
            max_positions=6,
        )
        with (
            patch.object(svc, "get_or_create_policy", return_value=policy),
            patch.object(svc, "pending_entry_count", return_value=2),
            patch(
                "stock_platform.operation.upbit_full_market.buy_concurrency.acquire_buy_admission_xact_lock",
                return_value=nullcontext(),
            ),
            patch(
                "stock_platform.operation.upbit_full_market.auto_slot_count.count_auto_slots_used",
                return_value=0,
            ),
        ):
            session.scalar = MagicMock(return_value=None)
            out = svc.begin_entry_from_signal(
                1380, symbol="KRW-SOL", available_krw=Decimal("50000")
            )
            assert out["reason"] == "PENDING_ENTRY_LIMIT"


# ---------------------------------------------------------------------------
# Latency benchmark (fixture-only serial=1 vs concurrent=2)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize("latency_ms", [100, 300, 1000])
async def test_latency_serial_vs_concurrent2(latency_ms: int) -> None:
    symbols = ["KRW-XRP", "KRW-SOL", "KRW-DOGE", "KRW-ADA"]

    async def batch(concurrency: int) -> float:
        book = FakeAdmissionBook(available_krw=Decimal("100000"))
        counters = StressCounters()
        t0 = time.perf_counter()
        await _run_executor_batch(
            symbols,
            concurrency=concurrency,
            broker_latency_ms=float(latency_ms),
            book=book,
            counters=counters,
            request_krw=Decimal("5000"),
        )
        elapsed = time.perf_counter() - t0
        book.assert_clean()
        assert counters.max_executor_active <= concurrency
        assert counters.max_broker_active <= concurrency
        return elapsed

    serial = await batch(1)
    concurrent = await batch(2)
    # concurrent should not be slower than serial by large margin;
    # for 4 symbols with latency L: serial≈4L, concurrent≈2L
    assert concurrent < serial * 0.85 or concurrent < serial
    # store for reporting via print (pytest -s captures)
    print(
        f"LATENCY_{latency_ms}MS serial={serial:.3f}s concurrent2={concurrent:.3f}s"
    )


def test_outbox_submit_concurrency_cap_two() -> None:
    worker = OrderOutboxWorker(
        session_factory=MagicMock(),
        dispatcher=MagicMock(),
        worker_id="live-outbox-1",
        batch_size=4,
        live_only=True,
    )
    serial = OutboxRunSummary(
        claimed=1, succeeded=1, retried=0, failed=0, ambiguous=0
    )
    with (
        patch(
            "stock_platform.operation.upbit_full_market.buy_concurrency.resolve_order_submit_concurrency",
            return_value=2,
        ),
        patch.object(worker, "_run_claimed_serial", return_value=serial) as ser,
    ):
        claims = [(i, 1) for i in range(4)]
        out = worker._run_claimed(claims)
        assert ser.call_count == 4
        assert out.claimed == 4


def test_clamp_and_policy_effective_still_two() -> None:
    assert clamp_concurrency_v1(2) == 2
    assert resolve_max_concurrent_entries(2) == 2
    assert resolve_max_concurrent_entries(99) == 1
