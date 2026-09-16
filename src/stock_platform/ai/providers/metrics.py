"""STEP 11-2 — Provider Metrics (프로세스 로컬, 재시작 시 초기화)."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class ProviderMetrics:
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    timeout_count: int = 0
    rate_limit_count: int = 0
    circuit_open_count: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    total_latency_ms: float = 0.0
    latencies: list[float] = field(default_factory=list)
    last_error: str | None = None
    last_request_at: datetime | None = None
    last_success_at: datetime | None = None
    last_failure_at: datetime | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    # 하위 호환 alias
    @property
    def calls(self) -> int:
        return self.total_requests

    @property
    def successes(self) -> int:
        return self.successful_requests

    @property
    def failures(self) -> int:
        return self.failed_requests

    @property
    def timeouts(self) -> int:
        return self.timeout_count

    def record(
        self,
        *,
        ok: bool,
        latency_ms: float,
        timeout: bool = False,
        rate_limited: bool = False,
        circuit_open: bool = False,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        error_code: str | None = None,
    ) -> None:
        now = datetime.now(timezone.utc)
        with self._lock:
            self.total_requests += 1
            self.total_latency_ms += latency_ms
            self.latencies.append(latency_ms)
            if len(self.latencies) > 200:
                self.latencies = self.latencies[-200:]
            self.last_request_at = now
            self.input_tokens += max(0, prompt_tokens)
            self.output_tokens += max(0, completion_tokens)
            self.total_tokens += max(0, prompt_tokens + completion_tokens)
            if circuit_open:
                self.circuit_open_count += 1
                self.failed_requests += 1
                self.last_failure_at = now
                self.last_error = error_code or "CIRCUIT_OPEN"
            elif timeout:
                self.timeout_count += 1
                self.failed_requests += 1
                self.last_failure_at = now
                self.last_error = error_code or "TIMEOUT"
            elif rate_limited:
                self.rate_limit_count += 1
                self.failed_requests += 1
                self.last_failure_at = now
                self.last_error = error_code or "RATE_LIMITED"
            elif ok:
                self.successful_requests += 1
                self.last_success_at = now
            else:
                self.failed_requests += 1
                self.last_failure_at = now
                self.last_error = error_code or "ERROR"

    def to_dict(self) -> dict[str, Any]:
        with self._lock:
            avg = (
                self.total_latency_ms / self.total_requests
                if self.total_requests
                else 0.0
            )
            p95 = None
            if self.latencies:
                ordered = sorted(self.latencies)
                idx = min(len(ordered) - 1, int(len(ordered) * 0.95))
                p95 = round(ordered[idx], 3)
            return {
                "total_requests": self.total_requests,
                "successful_requests": self.successful_requests,
                "failed_requests": self.failed_requests,
                "timeout_count": self.timeout_count,
                "rate_limit_count": self.rate_limit_count,
                "circuit_open_count": self.circuit_open_count,
                "input_tokens": self.input_tokens,
                "output_tokens": self.output_tokens,
                "total_tokens": self.total_tokens,
                "average_latency_ms": round(avg, 3),
                "avg_latency_ms": round(avg, 3),
                "p95_latency_ms": p95,
                "last_error": self.last_error,
                "last_request_at": (
                    self.last_request_at.isoformat()
                    if self.last_request_at
                    else None
                ),
                "last_success_at": (
                    self.last_success_at.isoformat()
                    if self.last_success_at
                    else None
                ),
                "last_failure_at": (
                    self.last_failure_at.isoformat()
                    if self.last_failure_at
                    else None
                ),
                # aliases
                "calls": self.total_requests,
                "successes": self.successful_requests,
                "failures": self.failed_requests,
                "timeouts": self.timeout_count,
            }


class HealthCache:
    """Health 결과 단기 캐시 — Dashboard 외부 호출 방지."""

    def __init__(self, ttl_seconds: float = 30.0) -> None:
        self._ttl = ttl_seconds
        self._items: dict[str, tuple[float, dict[str, Any]]] = {}
        self._lock = threading.Lock()

    def get(self, provider_id: str) -> dict[str, Any] | None:
        now = time.monotonic()
        with self._lock:
            row = self._items.get(provider_id)
            if not row:
                return None
            ts, payload = row
            if now - ts > self._ttl:
                self._items.pop(provider_id, None)
                return None
            return dict(payload)

    def set(self, provider_id: str, payload: dict[str, Any]) -> None:
        with self._lock:
            self._items[provider_id] = (time.monotonic(), dict(payload))

    def clear(self) -> None:
        with self._lock:
            self._items.clear()
