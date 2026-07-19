"""STEP58 — 성능 스모크 벤치마크 (기능 변경 없음).

측정:
  - Settings/Engine import
  - DB SELECT 1
  - Connection Pool 파라미터
  - TTL cache hit
  - FastAPI TestClient health (가능 시)

사용:
  python scripts/benchmark_step58.py
"""

from __future__ import annotations

import statistics
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = PROJECT_ROOT / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))


def _ms(started: float) -> float:
    return (time.perf_counter() - started) * 1000.0


def _repeat(label: str, times: int, fn) -> dict:
    samples: list[float] = []
    for _ in range(times):
        started = time.perf_counter()
        fn()
        samples.append(_ms(started))
    return {
        "label": label,
        "n": times,
        "avg_ms": round(statistics.mean(samples), 2),
        "p50_ms": round(statistics.median(samples), 2),
        "max_ms": round(max(samples), 2),
    }


def main() -> int:
    results: list[dict] = []

    started = time.perf_counter()
    from stock_platform.common.settings import get_settings
    from stock_platform.database.engine import create_database_engine
    from stock_platform.database.session import get_engine, get_session_factory
    from stock_platform.common.ttl_cache import process_ttl_cache

    import_ms = _ms(started)
    print(f"[OK] import core modules: {import_ms:.1f} ms")

    settings = get_settings()
    engine = get_engine()
    pool = engine.pool
    pool_info = {
        "pool_size": getattr(pool, "size", lambda: None)(),
        "checkedin": getattr(pool, "checkedin", lambda: None)(),
        "overflow": getattr(pool, "overflow", lambda: None)(),
        "settings_pool_size": settings.db_pool_size,
        "settings_max_overflow": settings.db_max_overflow,
        "settings_pool_timeout": settings.db_pool_timeout,
        "settings_pool_recycle": settings.db_pool_recycle,
        "settings_pool_pre_ping": settings.db_pool_pre_ping,
    }
    print(f"[OK] pool settings: {pool_info}")

    from sqlalchemy import text

    def ping_db() -> None:
        with get_session_factory()() as session:
            session.execute(text("SELECT 1"))

    results.append(_repeat("db_select_1", 20, ping_db))

    counter = {"n": 0}

    def factory() -> int:
        counter["n"] += 1
        time.sleep(0.01)
        return counter["n"]

    process_ttl_cache.clear()
    process_ttl_cache.get_or_set("bench", factory, ttl_seconds=30)
    hit = process_ttl_cache.get_or_set("bench", factory, ttl_seconds=30)
    cache_ok = hit == 1 and counter["n"] == 1
    print(f"[{'OK' if cache_ok else 'FAIL'}] ttl_cache hit (factory calls={counter['n']})")

    # FastAPI health (앱 기동 없이 TestClient)
    try:
        from fastapi.testclient import TestClient
        from stock_platform.api.main import app

        client = TestClient(app)

        def call_health() -> None:
            response = client.get("/health")
            assert response.status_code in {200, 503}

        results.append(_repeat("api_health", 10, call_health))

        for path in (
            "/api/v1/version",
            "/version",
        ):
            def call_path(p=path) -> None:
                response = client.get(p)
                # 경로 존재 여부만 — 인증/404는 허용
                assert response.status_code < 500

            try:
                results.append(
                    _repeat(f"api_get:{path}", 5, call_path)
                )
            except Exception as exc:
                print(f"[WARN] skip {path}: {exc}")
    except Exception as exc:
        print(f"[WARN] TestClient benchmark skipped: {exc}")

    print("\n=== Benchmark summary ===")
    for row in results:
        print(
            f"{row['label']}: avg={row['avg_ms']}ms "
            f"p50={row['p50_ms']}ms max={row['max_ms']}ms n={row['n']}"
        )

    # create_database_engine 재호출은 새 엔진 — 의도적으로 측정만
    _ = create_database_engine
    print("\nBenchmark complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
