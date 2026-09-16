"""UPBIT BUY concurrency 2/3/4 fixture-only benchmark (NO REAL broker / NO ops change).

운영 canonical config(entry/executor/submit=2)는 절대 변경하지 않는다.
이 파일은 fixture 안에서만 PROFILE_2/3/4를 비교한다.

V1 production clamp(max=2)는 의도적으로 bypass — future 상한 후보 비교용.
"""

from __future__ import annotations

import asyncio
import json
import os
import random
import statistics
import threading
import time
import tracemalloc
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

try:
    import psutil
except ImportError:  # pragma: no cover
    psutil = None  # type: ignore[assignment]

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

WORK_ID = "WRK-20260830-UPBIT-BUY-CONCURRENCY-2-3-4-BENCHMARK-V1"
EVIDENCE_PATH = Path(".run/k_upbit_buy_concurrency_2_3_4_benchmark_v1.json")
AUTO_POSITION_LIMIT = 6
SEED = 20260830
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
PROFILES = (2, 3, 4)
LATENCIES_MS = (50, 100, 300, 500, 1000)
# 고 latency는 sleep 부하를 줄이기 위해 배치 수 축소 (안전성 100cycle은 별도)
LATENCY_BATCHES: dict[int, int] = {
    50: 40,
    100: 40,
    300: 20,
    500: 15,
    1000: 12,
}
SAFETY_CYCLES = 100
# Upbit private order 대략적 shared budget (초당) — RATE_LIMITED_BENCH용 fake
RATE_LIMIT_RPS = 8.0


# ---------------------------------------------------------------------------
# Metrics helpers
# ---------------------------------------------------------------------------


def _pct(sorted_vals: list[float], p: float) -> float:
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return float(sorted_vals[0])
    k = (len(sorted_vals) - 1) * (p / 100.0)
    f = int(k)
    c = min(f + 1, len(sorted_vals) - 1)
    if f == c:
        return float(sorted_vals[f])
    return float(sorted_vals[f] + (sorted_vals[c] - sorted_vals[f]) * (k - f))


def _summary(vals: list[float]) -> dict[str, float]:
    if not vals:
        return {"n": 0, "avg": 0.0, "p50": 0.0, "p95": 0.0, "max": 0.0}
    s = sorted(vals)
    return {
        "n": float(len(s)),
        "avg": float(statistics.fmean(s)),
        "p50": _pct(s, 50),
        "p95": _pct(s, 95),
        "max": float(s[-1]),
    }


@dataclass
class SafetyCounters:
    duplicate_orders: int = 0
    position_limit_breach: int = 0  # active+pending > AUTO limit
    balance_oversub: int = 0
    orphan_reservation: int = 0
    lost_signal: int = 0
    incorrect_rollback: int = 0
    rejected_pending_limit: int = 0
    rejected_cash: int = 0
    rejected_position: int = 0  # correct reject (not breach)
    approved_count: int = 0
    lock: threading.Lock = field(default_factory=threading.Lock)

    def as_dict(self) -> dict[str, int]:
        return {
            "DUPLICATE_ORDER_COUNT": self.duplicate_orders,
            "POSITION_LIMIT_BREACH": self.position_limit_breach,
            "BALANCE_OVERSUBSCRIPTION": self.balance_oversub,
            "ORPHAN_RESERVATION": self.orphan_reservation,
            "LOST_SIGNAL": self.lost_signal,
            "INCORRECT_ROLLBACK": self.incorrect_rollback,
            "rejected_pending_limit": self.rejected_pending_limit,
            "rejected_cash": self.rejected_cash,
            "rejected_position": self.rejected_position,
            "approved_count": self.approved_count,
        }

    def ok(self) -> bool:
        return (
            self.duplicate_orders == 0
            and self.position_limit_breach == 0
            and self.balance_oversub == 0
            and self.orphan_reservation == 0
            and self.lost_signal == 0
            and self.incorrect_rollback == 0
        )


@dataclass
class WaitSamples:
    admission_lock_ms: list[float] = field(default_factory=list)
    reservation_ms: list[float] = field(default_factory=list)
    executor_queue_ms: list[float] = field(default_factory=list)
    broker_submit_ms: list[float] = field(default_factory=list)
    outbox_queue_ms: list[float] = field(default_factory=list)
    sell_total_ms: list[float] = field(default_factory=list)
    sell_queue_ms: list[float] = field(default_factory=list)
    batch_ms: list[float] = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def add(self, name: str, value: float) -> None:
        with self.lock:
            getattr(self, name).append(float(value))

    def summaries(self) -> dict[str, dict[str, float]]:
        return {
            "admission_lock_ms": _summary(self.admission_lock_ms),
            "reservation_ms": _summary(self.reservation_ms),
            "executor_queue_ms": _summary(self.executor_queue_ms),
            "broker_submit_ms": _summary(self.broker_submit_ms),
            "outbox_queue_ms": _summary(self.outbox_queue_ms),
            "sell_total_ms": _summary(self.sell_total_ms),
            "sell_queue_ms": _summary(self.sell_queue_ms),
            "batch_ms": _summary(self.batch_ms),
        }


class FakeTokenBucket:
    """초당 RPS 제한 — RATE_LIMITED_BENCH용 (실 Upbit POST 없음)."""

    def __init__(self, rps: float) -> None:
        self.rps = float(rps)
        self.tokens = float(rps)
        self.updated = time.perf_counter()
        self.lock = threading.Lock()

    def acquire(self) -> float:
        """대기 ms 반환."""

        waited = 0.0
        while True:
            with self.lock:
                now = time.perf_counter()
                elapsed = now - self.updated
                self.updated = now
                self.tokens = min(self.rps, self.tokens + elapsed * self.rps)
                if self.tokens >= 1.0:
                    self.tokens -= 1.0
                    return waited * 1000.0
                need = (1.0 - self.tokens) / self.rps
            time.sleep(need)
            waited += need


class FakeAdmissionBook:
    """pending<=concurrency, positions+pending<=AUTO_LIMIT, cash reservation."""

    def __init__(
        self,
        *,
        max_pending: int,
        max_positions: int = AUTO_POSITION_LIMIT,
        available_krw: Decimal = Decimal("500000"),
        open_positions: int = 0,
        deduct_cash_on_finalize: bool = False,
    ) -> None:
        self.max_pending = max_pending
        self.max_positions = max_positions
        self.initial_available = available_krw
        self.available_krw = available_krw
        self.open_positions = open_positions
        self.deduct_cash_on_finalize = deduct_cash_on_finalize
        self.pending: dict[str, Decimal] = {}
        self.orders: set[str] = set()
        self.spent = Decimal("0")
        self.lock = threading.RLock()
        self.admission_lock = threading.RLock()  # advisory lock 시뮬레이션

    @property
    def reserved(self) -> Decimal:
        return sum(self.pending.values(), Decimal("0"))

    def admit(self, symbol: str, request_krw: Decimal) -> tuple[bool, str, Decimal, float]:
        t0 = time.perf_counter()
        with self.admission_lock:
            lock_ms = (time.perf_counter() - t0) * 1000.0
            with self.lock:
                if symbol in self.pending or symbol in self.orders:
                    return False, "DUPLICATE", Decimal("0"), lock_ms
                if len(self.pending) >= self.max_pending:
                    return False, "PENDING_ENTRY_LIMIT", Decimal("0"), lock_ms
                used = self.open_positions + len(self.pending)
                if used >= self.max_positions:
                    return False, "AUTO_POSITION_LIMIT_REACHED", Decimal("0"), lock_ms
                # 잠깐 critical section (DB FOR UPDATE 흉내)
                time.sleep(0.0002)
                free = self.available_krw - self.reserved
                if request_krw > free:
                    if free <= 0:
                        return False, "INSUFFICIENT_CASH", Decimal("0"), lock_ms
                    approved = free
                else:
                    approved = request_krw
                self.pending[symbol] = approved
                # peak check: reserved <= available
                if self.reserved > self.available_krw + Decimal("0.01"):
                    # 즉시 롤백 표시용 — 호출측에서 oversub 카운트
                    pass
                return True, "OK", approved, lock_ms

    def finalize_order(self, symbol: str) -> None:
        with self.lock:
            amt = self.pending.pop(symbol, Decimal("0"))
            self.orders.add(symbol)
            self.open_positions += 1
            if self.deduct_cash_on_finalize:
                self.available_krw -= amt
                self.spent += amt

    def rollback(self, symbol: str) -> None:
        with self.lock:
            self.pending.pop(symbol, None)

    def peak_slots(self) -> int:
        with self.lock:
            return self.open_positions + len(self.pending)

    def assert_clean(self) -> None:
        assert self.pending == {}, f"orphan reservations: {self.pending}"


@dataclass
class ResourceSample:
    cpu_avg: float = 0.0
    cpu_peak: float = 0.0
    memory_delta_mb: float = 0.0
    thread_peak: int = 0


def _resource_start() -> tuple[Any, int, float]:
    proc = psutil.Process(os.getpid()) if psutil else None
    threads0 = threading.active_count()
    mem0 = 0.0
    if proc is not None:
        mem0 = float(proc.memory_info().rss) / (1024 * 1024)
        proc.cpu_percent(interval=None)
    tracemalloc.start()
    return proc, threads0, mem0


def _resource_end(proc: Any, mem0: float, cpu_samples: list[float]) -> ResourceSample:
    peak_threads = threading.active_count()
    mem1 = mem0
    if proc is not None:
        mem1 = float(proc.memory_info().rss) / (1024 * 1024)
        cpu_samples.append(float(proc.cpu_percent(interval=0.05)))
    try:
        tracemalloc.stop()
    except Exception:  # noqa: BLE001
        pass
    return ResourceSample(
        cpu_avg=float(statistics.fmean(cpu_samples)) if cpu_samples else 0.0,
        cpu_peak=float(max(cpu_samples)) if cpu_samples else 0.0,
        memory_delta_mb=float(mem1 - mem0),
        thread_peak=peak_threads,
    )


async def _run_buy_batch(
    symbols: list[str],
    *,
    concurrency: int,
    broker_latency_ms: float,
    book: FakeAdmissionBook,
    safety: SafetyCounters,
    waits: WaitSamples,
    request_krw: Decimal = Decimal("10000"),
    rate_bucket: FakeTokenBucket | None = None,
    max_positions_cap: int = AUTO_POSITION_LIMIT,
) -> dict[str, Any]:
    """Semaphore-bounded fake executor → optional rate limit → fake broker."""

    sem = asyncio.Semaphore(concurrency)
    broker_sem = asyncio.Semaphore(concurrency)
    active_exec = 0
    active_broker = 0
    peak_exec = 0
    peak_broker = 0
    exec_lock = asyncio.Lock()
    completed: list[str] = []
    t_batch0 = time.perf_counter()
    enqueue_at = {s: time.perf_counter() for s in symbols}

    async def _one(sym: str) -> None:
        nonlocal active_exec, active_broker, peak_exec, peak_broker
        async with sem:
            q_ms = (time.perf_counter() - enqueue_at[sym]) * 1000.0
            waits.add("executor_queue_ms", q_ms)
            async with exec_lock:
                active_exec += 1
                peak_exec = max(peak_exec, active_exec)
            try:
                t_res0 = time.perf_counter()
                ok, reason, approved, lock_ms = await asyncio.to_thread(
                    book.admit, sym, request_krw
                )
                waits.add("admission_lock_ms", lock_ms)
                waits.add("reservation_ms", (time.perf_counter() - t_res0) * 1000.0)
                if not ok:
                    with safety.lock:
                        if reason == "DUPLICATE":
                            safety.duplicate_orders += 1
                        elif reason == "AUTO_POSITION_LIMIT_REACHED":
                            safety.rejected_position += 1
                        elif reason == "PENDING_ENTRY_LIMIT":
                            safety.rejected_pending_limit += 1
                        elif reason == "INSUFFICIENT_CASH":
                            safety.rejected_cash += 1
                    return
                with safety.lock:
                    safety.approved_count += 1
                    if book.reserved > book.available_krw + Decimal("0.01"):
                        safety.balance_oversub += 1
                    if book.peak_slots() > max_positions_cap:
                        safety.position_limit_breach += 1

                async with broker_sem:
                    async with exec_lock:
                        active_broker += 1
                        peak_broker = max(peak_broker, active_broker)
                    try:
                        outbox_wait = 0.0
                        if rate_bucket is not None:
                            outbox_wait = await asyncio.to_thread(rate_bucket.acquire)
                            waits.add("outbox_queue_ms", outbox_wait)
                        else:
                            waits.add("outbox_queue_ms", 0.0)
                        t_br0 = time.perf_counter()
                        await asyncio.sleep(broker_latency_ms / 1000.0)
                        waits.add(
                            "broker_submit_ms",
                            (time.perf_counter() - t_br0) * 1000.0,
                        )
                        await asyncio.to_thread(book.finalize_order, sym)
                        completed.append(sym)
                        with safety.lock:
                            if book.peak_slots() > max_positions_cap:
                                safety.position_limit_breach += 1
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
            with safety.lock:
                safety.lost_signal += 1
    batch_ms = (time.perf_counter() - t_batch0) * 1000.0
    waits.add("batch_ms", batch_ms)
    try:
        book.assert_clean()
    except AssertionError:
        with safety.lock:
            safety.orphan_reservation += 1
    return {
        "completed": len(completed),
        "batch_ms": batch_ms,
        "peak_exec": peak_exec,
        "peak_broker": peak_broker,
    }


async def _sell_under_buy_load(
    *,
    concurrency: int,
    broker_latency_ms: float,
    waits: WaitSamples,
) -> None:
    """BUY는 buy_sem에 묶이고 SELL은 독립 — SELL이 BUY에 막히면 FAIL."""

    buy_sem = asyncio.Semaphore(concurrency)
    buy_hold = asyncio.Event()
    buy_started = asyncio.Event()

    async def _buy_blocker(i: int) -> None:
        async with buy_sem:
            if i == 0:
                buy_started.set()
            await buy_hold.wait()
            await asyncio.sleep(broker_latency_ms / 1000.0)

    async def _sell() -> None:
        t0 = time.perf_counter()
        # SELL은 buy_sem을 기다리지 않음
        await buy_started.wait()
        q_ms = (time.perf_counter() - t0) * 1000.0
        waits.add("sell_queue_ms", q_ms)
        t1 = time.perf_counter()
        await asyncio.sleep(broker_latency_ms / 1000.0)
        waits.add("sell_total_ms", (time.perf_counter() - t1) * 1000.0 + q_ms)

    buys = [asyncio.create_task(_buy_blocker(i)) for i in range(concurrency)]
    sell = asyncio.create_task(_sell())
    await asyncio.sleep(0.02)
    # SELL이 buy_hold 전에 끝나야 함 (독립 경로)
    done, pending = await asyncio.wait({sell}, timeout=broker_latency_ms / 1000.0 + 0.5)
    assert sell in done, "SELL blocked by BUY concurrency — protection broken"
    buy_hold.set()
    await asyncio.gather(*buys)


def _symbol_order(cycle: int) -> list[str]:
    rng = random.Random(SEED + cycle)
    syms = list(SYMBOLS_10)
    rng.shuffle(syms)
    return syms


# ---------------------------------------------------------------------------
# Benchmark runner
# ---------------------------------------------------------------------------


async def run_benchmark() -> dict[str, Any]:
    report: dict[str, Any] = {
        "WORK_ID": WORK_ID,
        "SEED": SEED,
        "AUTO_POSITION_LIMIT": AUTO_POSITION_LIMIT,
        "NOTE": "Fixture-only. Operating concurrency remains 2/2/2. V1 clamp bypassed for C3/C4.",
        "profiles": {},
        "raw": {},
        "rate_limited": {},
        "cash": {},
        "position": {},
        "sell": {},
        "efficiency": {},
        "recommendation_inputs": {},
    }

    # --- Safety 100 cycles @ 50ms (positions room for all 10 completes) ---
    for c in PROFILES:
        safety = SafetyCounters()
        waits = WaitSamples()
        proc, _, mem0 = _resource_start()
        cpu_samples: list[float] = []
        peak_exec = 0
        peak_broker = 0
        t0 = time.perf_counter()
        for cycle in range(SAFETY_CYCLES):
            if cycle % 20 == 0 and proc is not None:
                cpu_samples.append(float(proc.cpu_percent(interval=None)))
            await asyncio.sleep(random.Random(SEED + cycle).uniform(0, 0.001))
            book = FakeAdmissionBook(
                max_pending=c,
                max_positions=10,  # 동시성 한도 검증 (AUTO=6은 position 섹션)
                available_krw=Decimal("500000"),
            )
            out = await _run_buy_batch(
                _symbol_order(cycle),
                concurrency=c,
                broker_latency_ms=50.0,
                book=book,
                safety=safety,
                waits=waits,
                max_positions_cap=10,
            )
            peak_exec = max(peak_exec, int(out["peak_exec"]))
            peak_broker = max(peak_broker, int(out["peak_broker"]))
            assert int(out["peak_exec"]) <= c
            assert int(out["peak_broker"]) <= c
            assert len(book.orders) == 10
        elapsed = time.perf_counter() - t0
        res = _resource_end(proc, mem0, cpu_samples)
        report["profiles"][str(c)] = {
            "safety": safety.as_dict(),
            "safety_ok": safety.ok(),
            "peak_exec": peak_exec,
            "peak_broker": peak_broker,
            "safety_elapsed_s": elapsed,
            "orders_per_sec": (SAFETY_CYCLES * 10) / elapsed if elapsed else 0.0,
            "resource": {
                "cpu_avg": res.cpu_avg,
                "cpu_peak": res.cpu_peak,
                "memory_delta_mb": res.memory_delta_mb,
                "thread_peak": res.thread_peak,
            },
            "waits": waits.summaries(),
        }

    # --- RAW latency matrix ---
    for lat in LATENCIES_MS:
        report["raw"][str(lat)] = {}
        n_batches = LATENCY_BATCHES[lat]
        for c in PROFILES:
            safety = SafetyCounters()
            waits = WaitSamples()
            peak_exec = 0
            t0 = time.perf_counter()
            completed_orders = 0
            for cycle in range(n_batches):
                book = FakeAdmissionBook(max_pending=c, max_positions=10)
                out = await _run_buy_batch(
                    _symbol_order(cycle),
                    concurrency=c,
                    broker_latency_ms=float(lat),
                    book=book,
                    safety=safety,
                    waits=waits,
                    max_positions_cap=10,
                )
                peak_exec = max(peak_exec, int(out["peak_exec"]))
                completed_orders += int(out["completed"])
            elapsed = time.perf_counter() - t0
            report["raw"][str(lat)][str(c)] = {
                "batches": n_batches,
                "batch_ms": waits.summaries()["batch_ms"],
                "admission_lock_ms": waits.summaries()["admission_lock_ms"],
                "executor_queue_ms": waits.summaries()["executor_queue_ms"],
                "broker_submit_ms": waits.summaries()["broker_submit_ms"],
                "outbox_queue_ms": waits.summaries()["outbox_queue_ms"],
                "safety_ok": safety.ok(),
                "safety": safety.as_dict(),
                "peak_exec": peak_exec,
                "throughput_orders_per_sec": completed_orders / elapsed if elapsed else 0.0,
                "batch_per_sec": n_batches / elapsed if elapsed else 0.0,
            }

    # --- RATE_LIMITED latency matrix (100/300/1000 representative) ---
    for lat in (100, 300, 1000):
        report["rate_limited"][str(lat)] = {}
        n_batches = max(8, LATENCY_BATCHES[lat] // 2)
        for c in PROFILES:
            safety = SafetyCounters()
            waits = WaitSamples()
            bucket = FakeTokenBucket(RATE_LIMIT_RPS)
            t0 = time.perf_counter()
            completed_orders = 0
            for cycle in range(n_batches):
                book = FakeAdmissionBook(max_pending=c, max_positions=10)
                out = await _run_buy_batch(
                    _symbol_order(cycle),
                    concurrency=c,
                    broker_latency_ms=float(lat),
                    book=book,
                    safety=safety,
                    waits=waits,
                    rate_bucket=bucket,
                    max_positions_cap=10,
                )
                completed_orders += int(out["completed"])
            elapsed = time.perf_counter() - t0
            report["rate_limited"][str(lat)][str(c)] = {
                "batches": n_batches,
                "batch_ms": waits.summaries()["batch_ms"],
                "outbox_queue_ms": waits.summaries()["outbox_queue_ms"],
                "safety_ok": safety.ok(),
                "throughput_orders_per_sec": completed_orders / elapsed if elapsed else 0.0,
            }

    # --- Cash races ---
    for cash_label, cash in (("30k", Decimal("30000")), ("15k", Decimal("15000"))):
        report["cash"][cash_label] = {}
        for c in PROFILES:
            safety = SafetyCounters()
            waits = WaitSamples()
            peak_reserved = Decimal("0")
            approved_sum = Decimal("0")
            for cycle in range(30):
                book = FakeAdmissionBook(
                    max_pending=c,
                    max_positions=10,
                    available_krw=cash,
                    deduct_cash_on_finalize=True,
                )
                await _run_buy_batch(
                    _symbol_order(cycle),
                    concurrency=c,
                    broker_latency_ms=20.0,
                    book=book,
                    safety=safety,
                    waits=waits,
                    request_krw=Decimal("10000"),
                    max_positions_cap=10,
                )
                # spent + remaining reserved never exceed initial
                with book.lock:
                    peak_reserved = max(peak_reserved, book.spent + book.reserved)
                    approved_sum += book.spent
                if book.spent > cash + Decimal("0.01"):
                    safety.balance_oversub += 1
            report["cash"][cash_label][str(c)] = {
                "safety_ok": safety.ok(),
                "safety": safety.as_dict(),
                "peak_reserved_or_spent": float(peak_reserved),
                "available": float(cash),
                "approved_count": safety.approved_count,
                "rejected_cash": safety.rejected_cash,
            }

    # --- Position races (AUTO=6) ---
    for open_pos in (0, 3, 5):
        report["position"][str(open_pos)] = {}
        for c in PROFILES:
            safety = SafetyCounters()
            waits = WaitSamples()
            max_slots_seen = 0
            for cycle in range(40):
                book = FakeAdmissionBook(
                    max_pending=c,
                    max_positions=AUTO_POSITION_LIMIT,
                    open_positions=open_pos,
                    available_krw=Decimal("500000"),
                )
                await _run_buy_batch(
                    _symbol_order(cycle),
                    concurrency=c,
                    broker_latency_ms=15.0,
                    book=book,
                    safety=safety,
                    waits=waits,
                    max_positions_cap=AUTO_POSITION_LIMIT,
                )
                max_slots_seen = max(max_slots_seen, book.open_positions)
                assert book.open_positions <= AUTO_POSITION_LIMIT
            report["position"][str(open_pos)][str(c)] = {
                "safety_ok": safety.ok(),
                "safety": safety.as_dict(),
                "max_open_after": max_slots_seen,
                "auto_limit": AUTO_POSITION_LIMIT,
                "rejected_position": safety.rejected_position,
            }

    # --- SELL under BUY saturation ---
    for c in PROFILES:
        waits = WaitSamples()
        for _ in range(25):
            await _sell_under_buy_load(
                concurrency=c, broker_latency_ms=100.0, waits=waits
            )
        report["sell"][str(c)] = waits.summaries()

    # --- Efficiency (prefer RAW 300ms batch p50 as representative) ---
    def _batch_p50(lat: int, c: int) -> float:
        return float(report["raw"][str(lat)][str(c)]["batch_ms"]["p50"])

    c2_300 = _batch_p50(300, 2)
    c3_300 = _batch_p50(300, 3)
    c4_300 = _batch_p50(300, 4)
    c3_speedup = (c2_300 / c3_300) if c3_300 else 0.0
    c4_speedup = (c2_300 / c4_300) if c4_300 else 0.0
    # incremental: improvement fraction from previous
    c3_inc = (c2_300 - c3_300) / c2_300 if c2_300 else 0.0
    c4_inc = (c3_300 - c4_300) / c3_300 if c3_300 else 0.0

    rl_c2 = float(report["rate_limited"]["300"]["2"]["batch_ms"]["p50"])
    rl_c3 = float(report["rate_limited"]["300"]["3"]["batch_ms"]["p50"])
    rl_c4 = float(report["rate_limited"]["300"]["4"]["batch_ms"]["p50"])
    rl_c3_speedup = (rl_c2 / rl_c3) if rl_c3 else 0.0
    rl_c4_speedup = (rl_c2 / rl_c4) if rl_c4 else 0.0
    rl_c3_inc = (rl_c2 - rl_c3) / rl_c2 if rl_c2 else 0.0
    rl_c4_inc = (rl_c3 - rl_c4) / rl_c3 if rl_c3 else 0.0

    all_safe = all(report["profiles"][str(c)]["safety_ok"] for c in PROFILES)
    for lat in LATENCIES_MS:
        for c in PROFILES:
            all_safe = all_safe and bool(report["raw"][str(lat)][str(c)]["safety_ok"])

    sell_p95 = {c: report["sell"][str(c)]["sell_total_ms"]["p95"] for c in PROFILES}
    sell_regressed = sell_p95[4] > sell_p95[2] * 1.25 or sell_p95[3] > sell_p95[2] * 1.25

    adm_p95 = {
        c: report["profiles"][str(c)]["waits"]["admission_lock_ms"]["p95"] for c in PROFILES
    }
    lock_contention_up = adm_p95[4] > adm_p95[2] * 2.0

    cpu_peak = {
        c: report["profiles"][str(c)]["resource"]["cpu_peak"] for c in PROFILES
    }
    mem_delta = {
        c: report["profiles"][str(c)]["resource"]["memory_delta_mb"] for c in PROFILES
    }

    # Recommendation logic (rate-limited weighted)
    recommendation = "KEEP_CONCURRENCY_2"
    if not all_safe or sell_regressed:
        recommendation = "DO_NOT_INCREASE_CONCURRENCY"
    elif rl_c3_inc >= 0.10 and not sell_regressed:
        if rl_c4_inc >= 0.10 and not lock_contention_up:
            recommendation = "RECOMMEND_CONCURRENCY_4_FOR_FUTURE"
        else:
            recommendation = "RECOMMEND_CONCURRENCY_3_FOR_FUTURE"
    elif rl_c3_inc < 0.10 and rl_c4_inc < 0.10:
        recommendation = "KEEP_CONCURRENCY_2"

    # Natural trade frequency note (from prior audit: multi-symbol same-second rare)
    natural_need = False

    report["efficiency"] = {
        "RAW_300MS": {
            "C2_BATCH_P50": c2_300,
            "C3_BATCH_P50": c3_300,
            "C4_BATCH_P50": c4_300,
            "C3_SPEEDUP_VS_C2": c3_speedup,
            "C4_SPEEDUP_VS_C2": c4_speedup,
            "C3_INCREMENTAL_GAIN": c3_inc,
            "C4_INCREMENTAL_GAIN": c4_inc,
        },
        "RATE_LIMITED_300MS": {
            "C2_BATCH_P50": rl_c2,
            "C3_BATCH_P50": rl_c3,
            "C4_BATCH_P50": rl_c4,
            "C3_SPEEDUP_VS_C2": rl_c3_speedup,
            "C4_SPEEDUP_VS_C2": rl_c4_speedup,
            "C3_INCREMENTAL_GAIN": rl_c3_inc,
            "C4_INCREMENTAL_GAIN": rl_c4_inc,
        },
    }
    report["recommendation_inputs"] = {
        "all_safe": all_safe,
        "sell_regressed": sell_regressed,
        "lock_contention_up": lock_contention_up,
        "natural_multi_symbol_concurrent_need": natural_need,
        "RECOMMENDATION": recommendation,
        "BEST_RAW_PERFORMANCE": 4 if c4_300 <= c3_300 <= c2_300 else 3,
        "BEST_RATE_LIMITED_PERFORMANCE": (
            4 if rl_c4 <= rl_c3 <= rl_c2 else (3 if rl_c3 <= rl_c2 else 2)
        ),
        "BEST_SAFETY_PERFORMANCE": 2,  # V1 clamp / least complexity
        "BEST_OVERALL": recommendation,
    }
    return report


# ---------------------------------------------------------------------------
# Pytest entry
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_concurrency_2_3_4_benchmark_v1() -> None:
    report = await run_benchmark()
    EVIDENCE_PATH.parent.mkdir(parents=True, exist_ok=True)
    EVIDENCE_PATH.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, default=str),
        encoding="utf-8",
    )

    for c in PROFILES:
        assert report["profiles"][str(c)]["safety_ok"] is True
        assert report["profiles"][str(c)]["peak_exec"] <= c
        assert report["sell"][str(c)]["sell_total_ms"]["p95"] > 0

    for open_pos in ("0", "3", "5"):
        for c in PROFILES:
            assert report["position"][open_pos][str(c)]["safety_ok"] is True
            assert report["position"][open_pos][str(c)]["max_open_after"] <= 6

    for cash_label in ("30k", "15k"):
        for c in PROFILES:
            assert report["cash"][cash_label][str(c)]["safety_ok"] is True
            assert (
                report["cash"][cash_label][str(c)]["peak_reserved_or_spent"]
                <= report["cash"][cash_label][str(c)]["available"] + 0.01
            )

    # SELL must not regress badly vs C2
    s2 = report["sell"]["2"]["sell_total_ms"]["p95"]
    s4 = report["sell"]["4"]["sell_total_ms"]["p95"]
    assert s4 <= s2 * 1.5, f"SELL p95 regressed too much: C2={s2} C4={s4}"


def test_operating_clamp_still_two() -> None:
    """운영 V1 clamp는 여전히 2 — 벤치 C3/C4는 fixture 전용."""

    from stock_platform.operation.upbit_full_market.buy_concurrency import (
        clamp_concurrency_v1,
        resolve_max_concurrent_entries,
    )

    assert clamp_concurrency_v1(2) == 2
    assert resolve_max_concurrent_entries(3) == 1  # >2 → fail-closed 1
    assert resolve_max_concurrent_entries(4) == 1
    assert resolve_max_concurrent_entries(2) == 2
