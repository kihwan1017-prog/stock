# Architecture — stock-platform

현재 실행 구조의 진입점이다. 과거 설계안·폐기 구조는 [archive](archive/)에 둔다.

## 스택

| 계층 | 경로 / 기술 |
|------|-------------|
| Frontend | `frontend/` — Next.js App Router (ADMIN/USER) |
| Backend | `src/stock_platform/` — FastAPI |
| DB | PostgreSQL + `database/alembic/` (유일한 migration 체인) |
| Broker | Kiwoom REST, Upbit, Paper |
| AI | Provider 추상화 (Mock 기본) |

## 도메인 맵

- Order / Execution / Outbox
- Risk / Kill Switch / Account Pause
- Realtime Runtime / Scheduler / Feed
- Upbit Full-Market Portfolio / Slots
- Kiwoom Session / Feed
- Research / Shadow (H2/H3, Exit Strategy Shadow, Trailing, MA Exit)
- Observability / Daily Report / Process Map
- Recovery / Startup Reconciliation

## 상세 문서

- [AI_ARCHITECTURE.md](AI_ARCHITECTURE.md) — 실행 흐름·GAP
- [architecture/](architecture/) — 도메인별 설계
- [architecture/STRATEGY_LIFECYCLE_STEP12.md](architecture/STRATEGY_LIFECYCLE_STEP12.md)
- 루트 SoT: [../AGENTS.md](../AGENTS.md)

## 운영 상태 SoT

런타임 상태 판단은 **HTTP** `/api/v1/admin/autotrading/uba/{id}/ops-status` 를 사용한다.  
CLI/in-process singleton probe로 RUNNING/STOPPED를 판정하지 않는다.
