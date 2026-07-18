# 트러블슈팅 — stock-platform v1.0

## `/health` DEGRADED

1. `components.database` DOWN → PostgreSQL 서비스/접속정보 확인
2. `ollama` DOWN → Ollama 실행 및 `OLLAMA_BASE_URL`
3. `queue` failed → 시세 영속화 워커 로그 확인
4. `live_trading.ENABLED`인데 의도치 않음 → `KIWOOM_LIVE_ORDER_ENABLED=false`

## 주문이 안 나간다

1. Kill Switch 활성 여부
2. Outbox PENDING/FAILED
3. `OrderTimeoutService`로 PENDING/SENT 정리 여부
4. LIVE면 승인 이력(`live-transition/active`) 확인

## 관리 API 401

- `ADMIN_API_KEY` 설정과 `X-Admin-API-Key` 헤더 일치 여부

## Alembic

```powershell
.\.venv\Scripts\python.exe -m alembic current
.\.venv\Scripts\python.exe -m alembic heads
.\scripts\verify_alembic.ps1
```

multiple heads가 있으면 migration chain을 먼저 정리합니다.

## 알림 미수신

- Telegram/Slack/Discord enabled + credential
- 중복 억제(TTL)로 SKIPPED 되었는지 sender status 확인
