# README_STEP58 — Performance Optimization

## 목적

운영 환경에서 자동매매 시스템을 안정적으로 쓰기 위한 **성능 최적화**.

- 신규 기능 없음
- API 계약 변경 없음
- DB Schema 변경 없음

---

## 분석 결과 (우선순위)

| 순위 | 병목 | 계층 | 영향 |
|------|------|------|------|
| 1 | Exit Monitor 5초 폴링이 **이벤트 루프 블로킹** + INFO 스팸 | Scheduler | API 지연 |
| 2 | DB Pool `pool_size` 등 **미명시**(기본 5) | Database | 동시성 |
| 3 | Notification INFO/CRITICAL 과다 | Notification | I/O·디스크 |
| 4 | Ollama `/api/tags` 반복 호출 · `keep_alive` 미전달 | AI | 지연 |
| 5 | Lifecycle 알림 await가 Startup/Shutdown 지연 | Lifecycle | 기동/종료 |
| 6 | News `NOT IN` 서브쿼리 | Database | 뉴스 요약 |
| 7 | Screener/Quality 종목당 쿼리 · Realtime upsert commit | Batch/Realtime | 후속 |

---

## 적용 내용

### Database / SQLAlchemy
- Connection Pool 명시: `DB_POOL_SIZE=10`, `MAX_OVERFLOW=20`, `TIMEOUT=30`, `RECYCLE=1800`, `PRE_PING=true`
- Session 유지: `autoflush=False`, `expire_on_commit=False` (기존 양호)
- News `list_unsummarized`: `NOT IN` → **anti-join** (`OUTER JOIN … IS NULL`)

### Scheduler / Async
- Position Exit Monitor: `asyncio.to_thread`로 동기 ORM을 루프 밖으로 이동
- Exit Monitor scheduler shutdown: `wait=False` (종료 지연 완화)
- Lifecycle `SYSTEM_START`/`STOP` 알림: **3초 timeout**

### Cache
- `common/ttl_cache.py` 추가
- Ollama `/api/tags` **TTL 45s** 프로세스 캐시 (`/models`, `/status`)

### AI
- `generate` / `chat_structured` payload에 `keep_alive` 전달 (설정값 기존 `ollama_keep_alive`)

### Logging
- Exit Monitor tick/inspect → `debug`
- Notification publish/dispatch/skip → `debug`
- LoggingNotificationSender `critical` → `info` (detail 축약)

### Telegram
- 송신 경로·API 유지 (블로킹 제거 대상은 lifecycle await timeout으로 완화)
- Ops poll interval은 설정으로 조정 가능 (`TELEGRAM_OPS_POLL_INTERVAL_SECONDS`)

---

## Benchmark (로컬)

`python scripts/benchmark_step58.py`

| 항목 | 결과 (샘플) |
|------|-------------|
| Core import | ~496 ms |
| Pool size (설정) | **10** (이전 기본 5) |
| `SELECT 1` avg | **3.69 ms** (p50 0.69 ms) |
| TTL cache hit | factory 1회만 호출 |
| `GET /health` avg | ~495 ms (헬스 내부 Ollama 등 외부 체크 포함 — 남은 병목) |
| `GET /version` avg | ~3 ms |

> `/health`가 100ms를 넘는 주원인은 외부 의존(Ollama/Broker) 동기 점검. API 계약 유지 하에 후속에서 병렬화·캐시 가능.

---

## 남은 병목 / 권장사항

1. **Screener / Quality / Exit price**: 종목 배치 조회 (N+1 제거)
2. **Realtime quote upsert**: 호출자 일괄 commit / 버퍼링
3. **Outbox worker**: 이벤트당 세션 → 배치 세션 재사용
4. **Telegram Ops**: long-poll 또는 interval 상향 + shared `httpx.AsyncClient`
5. **Ollama**: 동시 호출 Semaphore(1~2)
6. **단일 Shared AsyncIOScheduler** (리팩터 범위 큼 — 후속)
7. 기타 APScheduler `shutdown(wait=True)` — 안정성 우선으로 유지, 필요 시 선택적 `wait=False`

---

## 검증

```bash
python scripts/benchmark_step58.py
pytest
# frontend: lint / typecheck / test / build
```

---

## 변경 파일 (요약)

- `common/settings.py`, `database/engine.py`, `common/ttl_cache.py`
- `position/exit_monitor*.py`
- `notification/publisher.py`, `service.py`, `logging_sender.py`
- `ai/ollama_client.py`, `api/v1/settings.py`, `api/lifecycle.py`
- `news/repository.py`
- `.env.example`, `scripts/benchmark_step58.py`, `README_STEP58.md`
