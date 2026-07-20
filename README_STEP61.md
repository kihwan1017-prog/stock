# README_STEP61 — Monitoring & Observability

## 목적

운영 중 시스템 상태를 조기에 확인하고 Alert를 남깁니다.  
**자동매매 로직은 변경하지 않습니다.**

---

## Monitoring 구조

```
/health/live          프로세스 liveness (경량)
/health/ready         DB readiness (경량, 실패 시 503)
/health               상세 컴포넌트 헬스 (기존)
/version              version · build · git · uptime

/api/v1/monitoring/overview   통합 스냅샷 (Admin, TTL ~8s)
/api/v1/monitoring/alerts     Audit 알림 이력
/api/v1/monitoring/alerts/evaluate  즉시 규칙 평가
```

백엔드 모듈:

| 모듈 | 역할 |
|------|------|
| `operation/runtime_info.py` | uptime · env · git |
| `operation/db_pool_monitor.py` | pool · latency · pg_stat |
| `operation/resource_monitor.py` | CPU/Mem/Disk (psutil 선택) |
| `operation/exception_rate.py` | 미처리 예외율 |
| `operation/monitoring_snapshot.py` | 스냅샷 + Alert 규칙 |

FE: Admin → **시스템 모니터링** (`/admin/monitoring`)

---

## Dashboard 표시 항목

- System: Server / Uptime / Version / Environment / Build / Git
- Database: Pool · Active Session · Slow Query · Rollback · 응답시간
- Broker: Connected · Heartbeat · Login · Order/Market API
- Scheduler: Running · Last/Next · Duration · Failure
- AI: Model · 응답시간 · Timeout · 최근 오류
- Telegram: Bot · 마지막 송신/실패 · Retry
- Orders: 오늘 주문·체결·미체결·거부·취소 · 평균 체결시간
- Positions: 종목수 · cost basis (PnL 상세는 risk dashboard)
- Risk: Kill Switch · Daily Loss · SL/TP/Trailing 카운트
- Resources: CPU · Memory · Disk · Network

---

## Alert Rules

| Rule ID | 조건 | 채널/감사 |
|---------|------|-----------|
| DB_DOWN | DB status DOWN | Audit + Notification |
| BROKER_DISCONNECT | live broker DOWN | Audit + Notification |
| SCHEDULER_FAILURE | failure_count > 0 | Audit + Notification |
| AI_TIMEOUT | Ollama DOWN / timeout 초과 | Audit + Notification |
| TELEGRAM_FAILURE | enabled + DEGRADED | Audit + Notification |
| DAILY_LOSS_TRIGGER | daily loss triggered | Audit + Notification |
| KILL_SWITCH_ACTIVATED | kill switch ACTIVE | Audit + Notification |
| EXCEPTION_RATE_HIGH | ≥5 /min (5분 창) | Audit + Notification |

- Dedup: 규칙당 **300초**
- Audit `event_type`: `MONITORING_ALERT:<RULE_ID>`

---

## Health API

| 경로 | 용도 | 실패 |
|------|------|------|
| `GET /health/live` | 프로세스 생존 | 거의 항상 200 |
| `GET /health/ready` | DB 준비 | **503** |
| `GET /health` | 상세 (기존) | 200 + DEGRADED |

Ops: `ops\health_check.bat` 는 `/health` 유지.  
로드밸런서에는 `/health/live` · `/health/ready` 권장.

---

## 운영 방법

1. Admin 로그인 → 시스템 모니터링 (15초 폴링)
2. 장애 의심 시 `POST /api/v1/monitoring/alerts/evaluate`
3. Audit: `GET /api/v1/monitoring/alerts` 또는 `/api/v1/audit/events`
4. Windows: `ops\health_check.bat` / `deploy_check.bat`

성능:

- overview TTL 8초
- live/ready는 외부 HTTP 미호출
- Position PnL 시세 조회 생략 (경량)

---

## 검증 (2026-07-20)

| 검사 | 결과 |
|------|------|
| `pytest` | **344 passed**, 3 skipped |
| `tests/test_monitoring_step61.py` | PASS |
| frontend lint / typecheck / test / build | PASS |

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_monitoring_step61.py -q
.\.venv\Scripts\python.exe -m pytest -q
cd frontend
npm run lint; npm run typecheck; npm run test; npm run build
```
