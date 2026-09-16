# SOURCE COMPONENT INVENTORY — 2026-07-31

읽기 전용 인벤토리. `router.py` 등록 ≈ HTTP 진입 증거.

---

## 1. Entrypoints

| 구성요소 | 경로 | 비고 |
|----------|------|------|
| ASGI | `api/main.py` `create_app()` | lifespan → `api_router` |
| Lifecycle | `api/lifecycle.py` | recovery, runtime, schedulers |
| Router | `api/router.py` | ~167 include_router |
| Settings | `common/settings.py` | get_settings |
| FE | `frontend/src/app/**/page.tsx` | 99 pages |

---

## 2. Backend 패키지 ↔ Router

| 영역 | 패키지 | Router 연결 |
|------|--------|-------------|
| Auth/RBAC | `auth/` | auth, users, roles, audit |
| Accounts/UBA/Vault | `trading/`, `broker/credential_*` | user_accounts, admin_broker_*, credentials |
| Market | `collectors/`, `markets/`, `realtime/` | sync, upbit, market_data, prices, realtime hub |
| Screener | `screener/` | candidates, candidate_runs |
| AI | `ai/*` (15+ subpackages) | admin_ai_*, strategy_request/draft*, user_ai |
| Strategy deploy | `strategy_deployment/` | strategy_*, runtimes, pipeline |
| Backtest | `backtest/`, `performance/` | backtest_* |
| Order | `order/` | orders, outbox, execution, cancel/replace |
| Risk | `risk_engine/`, `risk/`(legacy) | kill_switch, daily_loss, risk_* |
| Position | `position/` | position_*, exit monitor (lifecycle) |
| Settlement | `settlement/` | admin/user settlements |
| Ops | `operation/`, `notification/` | health, monitoring, dashboards, telegram, jobs |
| Internal only | `database/`, `operations/`(rehearsal), `brokers/`(deprecated wrapper) | no/minimal HTTP |

---

## 3. Runtime / Scheduler 이중성

| 이름 | 경로 | 역할 |
|------|------|------|
| Dynamic scoped runtime manager | `strategy_deployment/runtime_manager.py` | 실제 bootstrap/pause |
| DB strategy_runtime_registry | STEP12 registration entities | 커밋 기록, 기본 disabled |
| Strategy factory registry | `strategy_deployment/registry.py` | 클래스 팩토리 |
| Deprecated realtime runners | `realtime/runtime.py`, `strategy_runner.py` | 레거시 |
| Trading session scheduler | `realtime/session_scheduler.py` | KRX session |
| Order outbox scheduler | `order/outbox_runtime.py` | 주문 전송 |
| Recovery scheduler | `broker/recovery_scheduler.py` | 조회/reconcile |
| AutomaticScheduler | `scripts/run_scheduler.py` | 후보 스크리닝 등 **별도 프로세스** |

---

## 4. Frontend 도메인 맵

| Domain | Admin route | User route | API |
|--------|-------------|------------|-----|
| Accounts | `/admin/accounts` | `/user/accounts/*` | Live |
| Trading | `/admin/trading` | `/user/trading` | Live (+SSE stub) |
| Risk | `/admin/risk` | `/user/risk` | Live |
| Strategies | `/admin/strategies` | `/user/strategies` | Live |
| Strategy Request/Draft | `/admin/strategy-*` | `/user/strategy-*` | Live (WIP) |
| Scheduler | `/admin/scheduler` | — | Live |
| Recovery | `/admin/recovery` | — | Live |
| AI | `/admin/ai/*` | `/user/ai` | Live |
| Runtime | panel in trading | scoped counts | Live |

Stub/TODO: portfolio-optimize DELETE, auto-trading schedules, indicator CRUD, backup restore, SSE quotes.

---

## 5. Legacy / Duplicate 후보

| 항목 | 조치 제안 |
|------|-----------|
| 루트 `alembic/versions` | ARCHIVE |
| `api/v1/step32_router.py` tombstone | KEEP (등록 금지) |
| `risk/legacy_gate.py` | DEPRECATE |
| `brokers/` re-export | DEPRECATE |
| Multiple dashboard routers | CONSOLIDATE later / KEEP+문서 |
| STEP12 registry vs runtime manager | ADAPT (정합 설계) |
| Realtime deprecated runners | REMOVE_LATER after 확인 |
| Root FINAL_/README_AUDIT_* | ARCHIVE_CANDIDATE |

---

## 6. Security 스냅샷

- Public: `/`, `/health*`, `/version`, auth login/refresh, telegram webhook (secret header)
- Admin: router-level `require_admin` 다수
- LIVE: startup force OFF, pause runtimes, UBA required, vault, ARM, kill switch fail-closed
- Review: `/version` 정보 노출 (LOW); orders는 permission+ownership 의존
