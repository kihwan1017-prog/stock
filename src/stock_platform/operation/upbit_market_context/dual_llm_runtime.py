"""Dual Ollama LLM role runtime — ANALYSIS vs TRADING SHADOW.

TRADING priority > ANALYSIS. REAL order/LIVE/ARM/Risk 경로에 연결하지 않는다.
보호성 SELL / Kill Switch / Risk Gate는 이 모듈을 기다리지 않는다.
"""

from __future__ import annotations

import json
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from heapq import heappop, heappush
from typing import Any, Callable, TypeVar

import httpx

from stock_platform.common.logger import logger
from stock_platform.common.settings import get_settings

ROLE_ANALYSIS = "ANALYSIS"
ROLE_TRADING = "TRADING"
ROLE_TEACHER = "TEACHER"
# TRADING > ANALYSIS > TEACHER (숫자 작을수록 우선)
PRIORITY_TRADING = 0
PRIORITY_ANALYSIS = 10
PRIORITY_TEACHER = 100

T = TypeVar("T")

_seq = 0
_seq_lock = threading.Lock()
_gate_cv = threading.Condition()
_busy = False
_pending: list[tuple[int, int, threading.Event]] = []


def _priority_for(role: str) -> int:
    if role == ROLE_TRADING:
        return PRIORITY_TRADING
    if role == ROLE_TEACHER:
        return PRIORITY_TEACHER
    return PRIORITY_ANALYSIS


def _next_seq() -> int:
    global _seq
    with _seq_lock:
        _seq += 1
        return _seq


def run_with_role_priority(role: str, fn: Callable[[], T]) -> T:
    """단일 Ollama 슬롯 — TRADING > ANALYSIS > TEACHER."""

    global _busy
    priority = _priority_for(role)
    ready = threading.Event()
    ticket = (priority, _next_seq(), ready)
    with _gate_cv:
        heappush(_pending, ticket)
        _gate_cv.notify_all()
        while True:
            if not _busy and _pending and _pending[0][2] is ready:
                heappop(_pending)
                _busy = True
                break
            _gate_cv.wait(timeout=0.5)
    try:
        return fn()
    finally:
        with _gate_cv:
            _busy = False
            _gate_cv.notify_all()


@dataclass(frozen=True)
class RoleLlmConfig:
    role: str
    model: str
    timeout_seconds: float
    temperature: float
    max_tokens: int
    base_url: str
    keep_alive: str


def analysis_config() -> RoleLlmConfig:
    s = get_settings()
    return RoleLlmConfig(
        role=ROLE_ANALYSIS,
        model=s.resolved_analysis_llm_model,
        timeout_seconds=float(s.analysis_llm_timeout_seconds),
        temperature=float(s.analysis_llm_temperature),
        max_tokens=int(s.analysis_llm_max_tokens),
        base_url=str(s.ollama_base_url).rstrip("/"),
        keep_alive=str(s.ollama_keep_alive),
    )


def trading_config() -> RoleLlmConfig:
    s = get_settings()
    return RoleLlmConfig(
        role=ROLE_TRADING,
        model=s.resolved_trading_llm_model,
        timeout_seconds=float(s.trading_llm_timeout_seconds),
        temperature=float(s.trading_llm_temperature),
        max_tokens=int(s.trading_llm_max_tokens),
        base_url=str(s.ollama_base_url).rstrip("/"),
        keep_alive=str(s.ollama_keep_alive),
    )


def teacher_config() -> RoleLlmConfig:
    """TEACHER — ollama_model(qwen3.5:4b) reference. Trading보다 낮은 우선순위."""

    s = get_settings()
    model = (getattr(s, "teacher_llm_model", None) or "").strip() or s.ollama_model
    return RoleLlmConfig(
        role=ROLE_TEACHER,
        model=model,
        timeout_seconds=float(
            getattr(s, "teacher_llm_timeout_seconds", 120.0) or 120.0
        ),
        temperature=float(getattr(s, "teacher_llm_temperature", 0.2) or 0.2),
        max_tokens=int(getattr(s, "teacher_llm_max_tokens", 512) or 512),
        base_url=str(s.ollama_base_url).rstrip("/"),
        keep_alive=str(s.ollama_keep_alive),
    )


def chat_json_sync(
    *,
    config: RoleLlmConfig,
    system_prompt: str,
    user_prompt: str,
    response_schema: dict[str, Any],
) -> dict[str, Any]:
    """동기 Ollama /api/chat — 기존 OllamaClient와 동일 계약(think=False)."""

    payload: dict[str, Any] = {
        "model": config.model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": (
                    f"{user_prompt}\n\n"
                    "반드시 아래 JSON Schema에 맞는 JSON 객체만 반환하세요.\n"
                    + json.dumps(response_schema, ensure_ascii=False)
                ),
            },
        ],
        "stream": False,
        "format": response_schema,
        "think": False,
        "keep_alive": config.keep_alive,
        "options": {
            "temperature": config.temperature,
            "num_predict": config.max_tokens,
        },
    }

    def _call() -> dict[str, Any]:
        t0 = time.perf_counter()
        try:
            with httpx.Client(timeout=config.timeout_seconds) as client:
                res = client.post(f"{config.base_url}/api/chat", json=payload)
                res.raise_for_status()
                body = res.json()
        except httpx.TimeoutException as exc:
            return {
                "ok": False,
                "timeout": True,
                "error": f"TIMEOUT:{exc}",
                "latency_ms": round((time.perf_counter() - t0) * 1000, 1),
                "model": config.model,
                "model_role": config.role,
                "parsed": None,
            }
        except Exception as exc:  # noqa: BLE001
            return {
                "ok": False,
                "timeout": False,
                "error": f"{type(exc).__name__}:{exc}"[:240],
                "latency_ms": round((time.perf_counter() - t0) * 1000, 1),
                "model": config.model,
                "model_role": config.role,
                "parsed": None,
            }

        content = ""
        msg = body.get("message") if isinstance(body, dict) else None
        if isinstance(msg, dict):
            content = str(msg.get("content") or "")
            if not content.strip():
                thinking = str(msg.get("thinking") or "")
                if thinking.strip().startswith("{"):
                    content = thinking
        parsed: dict[str, Any] | None = None
        err = None
        if content.strip():
            try:
                obj = json.loads(content)
                parsed = obj if isinstance(obj, dict) else None
                if parsed is None:
                    err = "JSON_NOT_OBJECT"
            except json.JSONDecodeError as exc:
                err = f"JSONDecodeError:{exc}"
        else:
            err = "EMPTY_CONTENT"
        return {
            "ok": parsed is not None,
            "timeout": False,
            "error": err,
            "latency_ms": round((time.perf_counter() - t0) * 1000, 1),
            "model": config.model,
            "model_role": config.role,
            "parsed": parsed,
            "prompt_tokens": body.get("prompt_eval_count") if isinstance(body, dict) else None,
            "output_tokens": body.get("eval_count") if isinstance(body, dict) else None,
        }

    return run_with_role_priority(config.role, _call)


class AnalysisSummaryCache:
    """시장/뉴스 요약 캐시 — Trading이 원문 뉴스를 재투입하지 않도록."""

    def __init__(self, max_items: int = 64) -> None:
        self._max = max_items
        self._lock = threading.Lock()
        self._data: OrderedDict[str, tuple[float, dict[str, Any]]] = OrderedDict()

    def get(self, key: str) -> dict[str, Any] | None:
        now = time.time()
        with self._lock:
            item = self._data.get(key)
            if item is None:
                return None
            expires, payload = item
            if expires < now:
                self._data.pop(key, None)
                return None
            self._data.move_to_end(key)
            return dict(payload)

    def put(self, key: str, payload: dict[str, Any], *, ttl_seconds: float) -> None:
        with self._lock:
            self._data[key] = (time.time() + max(30.0, ttl_seconds), dict(payload))
            self._data.move_to_end(key)
            while len(self._data) > self._max:
                self._data.popitem(last=False)


analysis_cache = AnalysisSummaryCache()


# 런타임 카운터 (프로세스 로컬 — UI 상태용)
_stats_lock = threading.Lock()
_stats: dict[str, Any] = {
    "analysis_calls": 0,
    "analysis_ok": 0,
    "analysis_timeout": 0,
    "analysis_error": 0,
    "analysis_cache_hit": 0,
    "trading_shadow_calls": 0,
    "trading_shadow_ok": 0,
    "trading_shadow_timeout": 0,
    "trading_shadow_error": 0,
    "teacher_calls": 0,
    "teacher_ok": 0,
    "teacher_timeout": 0,
    "teacher_error": 0,
    "rag_cache_hit": 0,
    "analysis_latencies_ms": [],
    "trading_latencies_ms": [],
    "teacher_latencies_ms": [],
}


def record_stat(kind: str, *, ok: bool, timeout: bool, latency_ms: float | None) -> None:
    with _stats_lock:
        if kind == ROLE_ANALYSIS:
            prefix = "analysis"
        elif kind == ROLE_TEACHER:
            prefix = "teacher"
        else:
            prefix = "trading_shadow"
        _stats[f"{prefix}_calls"] += 1
        if timeout:
            _stats[f"{prefix}_timeout"] += 1
        elif ok:
            _stats[f"{prefix}_ok"] += 1
        else:
            _stats[f"{prefix}_error"] += 1
        lat_key = {
            "analysis": "analysis_latencies_ms",
            "teacher": "teacher_latencies_ms",
            "trading_shadow": "trading_latencies_ms",
        }[prefix]
        if latency_ms is not None:
            _stats[lat_key].append(float(latency_ms))
            _stats[lat_key] = _stats[lat_key][-100:]


def record_cache_hit() -> None:
    with _stats_lock:
        _stats["analysis_cache_hit"] += 1


def record_rag_cache_hit() -> None:
    with _stats_lock:
        _stats["rag_cache_hit"] += 1


def runtime_stats() -> dict[str, Any]:
    with _stats_lock:
        a_lat = list(_stats["analysis_latencies_ms"])
        t_lat = list(_stats["trading_latencies_ms"])
        te_lat = list(_stats["teacher_latencies_ms"])

        def _med(vals: list[float]) -> float | None:
            if not vals:
                return None
            s = sorted(vals)
            return float(s[len(s) // 2])

        return {
            "analysis_calls": _stats["analysis_calls"],
            "analysis_ok": _stats["analysis_ok"],
            "analysis_timeout": _stats["analysis_timeout"],
            "analysis_error": _stats["analysis_error"],
            "analysis_cache_hit": _stats["analysis_cache_hit"],
            "analysis_median_latency_ms": _med(a_lat),
            "trading_shadow_calls": _stats["trading_shadow_calls"],
            "trading_shadow_ok": _stats["trading_shadow_ok"],
            "trading_shadow_timeout": _stats["trading_shadow_timeout"],
            "trading_shadow_error": _stats["trading_shadow_error"],
            "trading_median_latency_ms": _med(t_lat),
            "teacher_calls": _stats["teacher_calls"],
            "teacher_ok": _stats["teacher_ok"],
            "teacher_timeout": _stats["teacher_timeout"],
            "teacher_error": _stats["teacher_error"],
            "teacher_median_latency_ms": _med(te_lat),
            "rag_cache_hit": _stats["rag_cache_hit"],
            "priority": "TRADING > ANALYSIS > TEACHER",
            "protective_exit_llm_dependency": False,
            "trading_starvation": False,
        }


def dual_llm_enabled() -> bool:
    s = get_settings()
    return bool(getattr(s, "dual_llm_ollama_enabled", True))


def trading_shadow_enabled() -> bool:
    s = get_settings()
    return bool(getattr(s, "trading_llm_shadow_enabled", True))


def teacher_enabled() -> bool:
    s = get_settings()
    return bool(getattr(s, "teacher_llm_enabled", True)) and dual_llm_enabled()


__all__ = [
    "ROLE_ANALYSIS",
    "ROLE_TRADING",
    "ROLE_TEACHER",
    "analysis_config",
    "trading_config",
    "teacher_config",
    "chat_json_sync",
    "analysis_cache",
    "run_with_role_priority",
    "record_stat",
    "record_cache_hit",
    "record_rag_cache_hit",
    "runtime_stats",
    "dual_llm_enabled",
    "trading_shadow_enabled",
    "teacher_enabled",
    "logger",
]
