# 운영 Runbook — stock-platform

## 일일 점검 순서

첫날이면 [PAPER_DAY1_CHECKLIST.md](PAPER_DAY1_CHECKLIST.md)를 먼저 보세요.  
문서 목차: [README.md](README.md)

1. `GET /health` — 전체 컴포넌트 상태 확인
2. `GET /api/v1/system/dashboard` — 후보/AI/포지션/리스크 통합 확인
3. `POST /api/v1/broker/kiwoom/account-state/sync` — 계좌·미체결 동기화
4. Outbox / Job 실패 여부 확인 (`dashboard.recent_errors`)
5. Kill Switch / 실전 전환 상태 확인

## 핵심 엔드포인트

| 목적 | Method | Path |
|------|--------|------|
| Health | GET | `/health` |
| 운영 대시보드 | GET | `/api/v1/system/dashboard` |
| 일일 리포트 생성 | POST | `/api/v1/daily-reports` |
| 감사 로그 | GET | `/api/v1/audit/events` |
| Scheduler 즉시 실행 | POST | `/api/v1/scheduler-admin/run-now/{job_name}` |
| Kill Switch | POST | `/api/v1/risk/kill-switch/activate\|deactivate` |

## 관리 API 인증

민감 API는 헤더 `X-Admin-API-Key`가 필요합니다.

- 설정: `ADMIN_API_KEY` (`stock-platform.env`)
- 키가 비어 있으면 로컬 개발 모드로 통과합니다. 운영에서는 반드시 설정하세요.

## 알림

- Telegram / Slack / Discord webhook 지원
- 중복 억제(TTL) + 재시도가 기본 적용됩니다.
- 설정: `TELEGRAM_*`, `SLACK_*`, `DISCORD_*`

## 재시작 후 확인

1. DB 연결 (`/health.components.database`)
2. Scheduler enabled
3. Outbox PENDING 적체
4. 실시간 시세 freshness
5. Kill Switch 비활성(의도된 경우)
