"""Prod AI Gate latency regression — model/reuse/debounce/shadow queue."""

from __future__ import annotations

import asyncio
import time
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from stock_platform.ai.market_analysis.autotrading_periodic import (
    _WARMUP_DEBOUNCE_SECONDS,
    _warmup_ollama,
    resolve_analysis_reuse_seconds,
    resolve_scanner_ai_reuse_seconds,
)
from stock_platform.operation.upbit_market_context import candidate_llm as cllm


def test_scanner_reuse_survives_interval():
    settings = SimpleNamespace(
        autotrading_ai_analysis_ttl_seconds=900.0,
        analysis_llm_cache_ttl_seconds=600.0,
        autotrading_ai_analysis_reuse_seconds=None,
    )
    reuse = resolve_scanner_ai_reuse_seconds(
        settings, scanner_interval_seconds=300.0
    )
    assert reuse >= 300.0
    assert reuse == 600.0  # max(interval, cache_ttl)
    # 주기 Job은 여전히 interval-grace (< interval)
    periodic = resolve_analysis_reuse_seconds(
        SimpleNamespace(
            autotrading_ai_analysis_interval_seconds=300.0,
            autotrading_ai_analysis_ttl_seconds=900.0,
            autotrading_ai_analysis_reuse_seconds=None,
        )
    )
    assert periodic < 300.0


def test_resolved_autotrading_model_prefers_analysis_role():
    from stock_platform.common.settings import Settings

    s = Settings(
        autotrading_ai_analysis_model="",
        analysis_llm_model="qwen3:1.7b",
        ollama_model="qwen3.5:4b",
    )
    assert s.resolved_autotrading_ai_analysis_model == "qwen3:1.7b"
    s2 = Settings(autotrading_ai_analysis_model="qwen3.5:4b")
    assert s2.resolved_autotrading_ai_analysis_model == "qwen3.5:4b"


@pytest.mark.asyncio
async def test_warmup_debounce_is_non_blocking_skip(monkeypatch):
    """debounce는 sleep/wait가 아니라 immediate skip."""

    import stock_platform.ai.market_analysis.autotrading_periodic as mod

    monkeypatch.setattr(mod, "_last_warmup_ok", True)
    monkeypatch.setattr(mod, "_last_warmup_monotonic", time.monotonic())
    settings = SimpleNamespace(
        ollama_base_url="http://127.0.0.1:11434",
        autotrading_ai_analysis_model="qwen3:1.7b",
        analysis_llm_model="qwen3:1.7b",
    )
    t0 = time.perf_counter()
    out = await _warmup_ollama(settings)
    elapsed = time.perf_counter() - t0
    assert out.get("skipped") is True
    assert out.get("skip_reason") == "WARMUP_DEBOUNCED"
    assert out.get("debounce_waited") is False
    assert elapsed < 0.5  # sleep(600) 절대 금지
    assert out.get("debounce_seconds") == _WARMUP_DEBOUNCE_SECONDS


def test_shadow_llm_schedule_dedup_and_bounded(monkeypatch):
    # worker가 실제로 Ollama를 치지 않도록 stub
    monkeypatch.setattr(
        cllm,
        "maybe_analyze_shadow_candidate",
        lambda *a, **k: {"ok": True, "skipped": True},
    )

    # reset module state
    with cllm._shadow_llm_lock:
        cllm._shadow_llm_pending.clear()
        cllm._shadow_llm_queue.clear()
        cllm._shadow_llm_worker_started = False

    # queue worker를 시작하지 않도록 Thread stub
    class _NoThread:
        def __init__(self, *a, **k):
            pass

        def start(self):
            return None

    monkeypatch.setattr(cllm.threading, "Thread", _NoThread)

    r1 = cllm.schedule_shadow_candidate_llm(101)
    assert r1.get("scheduled") is True
    r2 = cllm.schedule_shadow_candidate_llm(101)
    assert r2.get("reason") == "DEDUP_INFLIGHT"

    # fill to max
    with cllm._shadow_llm_lock:
        cllm._shadow_llm_pending.clear()
        cllm._shadow_llm_queue.clear()
        for i in range(cllm._SHADOW_LLM_MAX_QUEUE):
            cllm._shadow_llm_pending.add(1000 + i)
    full = cllm.schedule_shadow_candidate_llm(9999)
    assert full.get("reason") == "QUEUE_FULL"


@pytest.mark.asyncio
async def test_ai_gate_concurrency_and_recommendation_equality():
    """concurrency=2 동작 + recommendation semantics 불변(mock)."""

    from stock_platform.operation.upbit_opportunity_scanner.service import (
        UpbitOpportunityScannerService,
    )

    calls: list[str] = []
    inflight = 0
    max_inflight = 0
    lock = asyncio.Lock()

    async def ai_runner(symbol: str) -> dict:
        nonlocal inflight, max_inflight
        async with lock:
            inflight += 1
            max_inflight = max(max_inflight, inflight)
            calls.append(symbol)
        await asyncio.sleep(0.05)
        async with lock:
            inflight -= 1
        return {
            "ok": True,
            "recommendation": "HOLD" if symbol.endswith("A") else "ALLOW",
            "confidence": 0.8,
            "model": "qwen3:1.7b",
        }

    ranked = [
        {"symbol": f"KRW-T{i}", "score": 100 - i} for i in range(5)
    ]
    # KRW-T0 ends with 0 not A → ALLOW; make one A
    ranked[0]["symbol"] = "KRW-TA"
    svc = UpbitOpportunityScannerService(MagicMock(), ai_runner=ai_runner)
    result: dict = {"ai_calls": 0, "errors": [], "ai_failed_skipped": 0}
    selected = await svc._analyze_ranked(
        ranked,
        result,
        top_n=5,
        backfill=True,
        force=False,
        ai_concurrency=2,
        scanner_interval_seconds=300.0,
    )
    assert len(selected) == 5
    assert selected[0]["recommendation"] == "HOLD"  # KRW-TA
    assert selected[1]["recommendation"] == "ALLOW"
    assert result["ai_calls"] == 5
    assert result.get("ai_max_inflight", 0) >= 1
    assert max_inflight <= 2
    assert result.get("ai_reuse_seconds", 0) >= 300
