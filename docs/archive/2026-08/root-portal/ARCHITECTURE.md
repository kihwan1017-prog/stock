# ARCHITECTURE.md — stock-platform v1.0.0

상세: [docs/architecture/ARCHITECTURE.md](docs/architecture/ARCHITECTURE.md)

---

## 1. 시스템 개요

Windows 단일 호스트에서 FastAPI + Next.js Admin + PostgreSQL + (선택) Ollama를 운영합니다.  
Docker/Kubernetes는 범위에 없습니다.

```text
┌─────────────┐     ┌──────────────────┐     ┌────────────┐
│ Admin Web   │────►│ FastAPI (8000)   │────►│ PostgreSQL │
│ Next.js     │     │ lifecycle+jobs   │     └────────────┘
└─────────────┘     │ OrderExecution   │
                    │ Outbox → Broker  │────► Kiwoom / Upbit
                    │ Risk / Kill      │
                    │ AI (Ollama)      │────► localhost:11434
                    └──────────────────┘
                              │
                              ▼
                         Telegram / Slack
```

---

## 2. 레이어

| 레이어 | 위치 | 역할 |
|--------|------|------|
| API | `api/v1/*` | HTTP · 인증 · DTO |
| Application | `*/service.py` | 유스케이스 |
| Domain | `order`, `risk*`, `position` | 규칙 |
| Infrastructure | `broker`, `database`, `notification` | 외부 I/O |
| UI | `frontend/` | Admin/User |

원칙: 주문은 `OrderExecutionService` 단일 진입점 → Outbox → BrokerAdapter.

---

## 3. 런타임 구성 (lifecycle)

`api/lifecycle.py`가 기동 시 스케줄러·모니터를 시작합니다.

- Order Outbox Worker  
- Position Exit Monitor  
- Session / Strategy / Execution runners (realtime)  
- Telegram ops (설정 시)  
- Jobs (APScheduler)

Known Issue: 스케줄러 인스턴스가 다수 분리되어 관측·중복 위험이 있습니다.  
운영은 **단일 Windows 프로세스** 전제입니다.

---

## 4. 데이터

- Canonical migrations: `database/alembic/versions/`  
- 스키마 개요: [DB_SCHEMA.md](DB_SCHEMA.md) · [docs/database/ERD.md](docs/database/ERD.md)  
- Overlay 파일은 참고용 — 실행 금지

---

## 5. 보안 경계

- 네트워크: VPN/사설망  
- Auth: JWT + Admin Key + DB RBAC  
- Live: env + DB transition  
상세: [SECURITY.md](SECURITY.md)
