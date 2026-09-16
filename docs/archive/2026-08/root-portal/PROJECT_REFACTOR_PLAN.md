# PROJECT_REFACTOR_PLAN

> STEP55 분석 전용 계획서 (2026-07-20)  
> **이번 STEP에서는 삭제·대규모 리팩토링을 하지 않는다.**  
> 제거·복구는 후속 STEP에서 진행한다.

관련: `PROJECT_FINAL_AUDIT.md` · `README_STEP52`~`54` · `README_STEP55.md`

---

# Dead Code

## 제거 후보 (프로덕션 경로 미사용)

| 항목 | 경로 | 근거 |
|------|------|------|
| `market/` 패키지 | `src/stock_platform/market/` | 외부 프로덕션 import 0. `markets/`가 DB 시세 본선. step33 테스트만 참조 |
| `indicator/` 계산 스텁 | `src/stock_platform/indicator/` | 프로덕션 import 0. `indicators/`가 본선. unit/step34 테스트만 참조 |
| `strategies/` | `src/stock_platform/strategies/` | 빈 안내 패키지, import 0 |
| `strategy/base.py`, `momentum.py` | `src/stock_platform/strategy/` | 외부 호출 0 (deployment가 실사용) |
| `dashboard/` | `src/stock_platform/dashboard/` | 빈 `__init__`만 |
| deprecated indicator alias | `api/v1/indicator_router.py` | `/api/v1/indicator/*` health stub. 본선은 `/indicators` |
| InMemory Position 스택 | `position/repository.py`, `position/service.py`, `position/calculator.py`, `portfolio/service.py` | **step32_router 전용**. Paper/ExitMonitor는 ORM 경로 |
| InMemory Market | `market/repository.py` (`InMemoryMarketRepository`) | step33 테스트 전용 |

## 사용 중 (제거 금지 — 감사 문서 outdated)

| 항목 | 상태 |
|------|------|
| PositionExitMonitor + scheduler | STEP53 → Lifecycle 연결됨 |
| NotificationPublisher / Service / Telegram Ops | STEP54 연결됨 |
| AutomaticScheduler | `scheduler_admin`에서 사용 |
| RiskManagementEngine | ExitMonitor · OrderExecution · `/api/v1/risk` |

## 파손(Broken) — Dead보다 우선

| 항목 | 문제 |
|------|------|
| `risk/service.py` | step32용 `evaluate(RiskLimits)`만 남음. `risk_policies.py` · `allocation_service.py`는 `RiskService(RiskRepository)` + `create_policy` / `create_and_save_position_plan` 호출 → **런타임 AttributeError 위험** |

---

# Legacy Code

## step32 표면

| 파일 | 등록 | 분류 |
|------|------|------|
| `api/v1/step32_router.py` | ✅ `api/router.py` | **제거 후보** (FE 이전 후) |
| Endpoints | `POST /positions/executions`, `GET /positions`, `GET /portfolio/summary`, `POST /risk/check`, `GET /dashboard/summary` | 인메모리 |

## 의존 모듈

| 모듈 | 역할 | 비고 |
|------|------|------|
| `RiskService.evaluate` | 인메모리 한도 체크 | DB RiskService와 **이름 충돌** |
| `InMemoryPositionRepository` + `PositionService` | 인메모리 포지션 | PaperPosition과 이중 |
| `PortfolioService` | 인메모리 요약 | admin-summary / paper와 이중 |

## FE 잔존 의존 (삭제 전 필수 이전)

| 클라이언트 | 호출 |
|------------|------|
| `features/user/api/userApi.ts` | `GET /dashboard/summary`, (일부) step32 주석 |
| `features/admin/api/adminApi.ts` | `GET /portfolio/summary`, `GET /positions` |
| `admin/portfolio/page.tsx` | step32 명시 |

**대체:** `GET /paper-accounts/{id}/positions`, `GET /dashboard/admin-summary`, Paper valuation.

Alembic revision id `step32_*`는 **마이그레이션 이력** — 코드 레거시와 별개, 삭제 대상 아님.

---

# Duplicate Package

| 쌍 | A (본선/역할) | B (역할) | 통합 가능? |
|----|---------------|----------|------------|
| `broker/` vs `brokers/` | 주문·계좌·WS·paper/live | 시세 REST (Kiwoom/Upbit collectors) | 장기: `brokers` → `broker/quotation`. 단기: 문서화 |
| `market/` vs `markets/` | 인메모리/스텁 | DB Instrument/PriceDaily | **`market/` 삭제** 권장 |
| `indicator/` vs `indicators/` | SMA/EMA 헬퍼 스텁 | engine/pipeline/API | **`indicator/` 삭제** (테스트 이전 후) |
| `strategy/` vs `strategies/` vs `strategy_deployment/` | stub / 빈 안내 / **실사용** | — | stub·strategies 제거, deployment 유지 |
| `risk/` vs `risk_engine/` | sizing·exit·policy DB | kill-switch·daily-loss·guards | **병합보다 역할 문서화**. RiskService 복구 우선 |

---

# Duplicate API

## Positions / Portfolio

| Path | 백엔드 | 성격 |
|------|--------|------|
| `/api/v1/positions`, `/portfolio/summary`, `/dashboard/summary` | step32 | 인메모리 |
| `/api/v1/paper-accounts/{id}/positions` | paper_accounts | **DB** |
| `/api/v1/dashboard/admin-summary` | AdminDashboardSummary | **DB KPI** |

## Orders / Executions

| 영역 | Prefix들 |
|------|----------|
| Trading orders | `/orders`, `/order-execution`, `/order-outbox`, cancel/replace/states |
| Paper | `/paper-orders`, `/paper-executions` |
| Broker | `/broker/orders` |
| Realtime | `/realtime-execution` |

→ 기능 분리는 의도적이나 **네이밍·문서 혼동** 큼.

## Risk

| Path | 엔진 |
|------|------|
| `/api/v1/risk` | RiskManagementEngine |
| `/api/v1/risk/check` | step32 RiskService |
| `/api/v1/risk-policies` | **깨진** DB RiskService 기대 |
| `/risk/kill-switch`, `/daily-loss`, realtime-risk | risk_engine |

## Market / Indicators

| Path | 비고 |
|------|------|
| `/api/v1/market/*`, `/prices`, `/sync` | markets 본선 |
| `/api/v1/indicators` | 본선 |
| `/api/v1/indicator/*` | deprecated stub |

## AI / News / Strategy

- AI: `/ai-analysis`, `/ai/candidates`, `/ai-orchestration`, `/realtime-ai` (분산)
- Strategy: deployment / runtime / ranking / selector / performance (분산, prefix는 대체로 분리)
- News: `/news` + `/dart`

---

# Duplicate Repository

| 이중 경로 | A | B | 권장 |
|-----------|---|---|------|
| Position | `PaperPosition` + trading repo | InMemory `Position` | Paper만 유지, step32 제거 |
| Risk service | (유실된) DB RiskService | step32 evaluate | **DB 복구 + 이름 분리** |
| Price | `markets` PriceDaily | `market` InMemory candle | markets만 |
| Paper broker adapter | `broker/paper/adapter.py` | `broker/paper_adapter.py` | 단일화 후보 (후속) |
| Kiwoom client | `broker/kiwoom/*` (주문) | `brokers/kiwoom/*` (시세) | 의도적 분리 가능, 이름 혼란 |

Mapper/DTO: 도메인별 다수 공존 — 당장은 통합보다 **공개 API 표면 축소**가 우선.

---

# Broken Route

## 하드 404

| 경로 | 현재 (2026-07-20) | 감사(07-19) |
|------|-------------------|-------------|
| `/admin/logs` | ✅ `page.tsx` 존재 (감사 로그 UI) | 🔴 outdated |
| `/admin/data` | ✅ redirect → `/admin/monitoring` | 🔴 outdated (404는 해소) |

## Soft-broken (페이지는 있으나 제품 구멍)

| 경로 | 이슈 |
|------|------|
| `/admin/data` | 메뉴 "데이터 관리" ≠ monitoring 리다이렉트 (라벨 불일치) |
| `/admin/notifications` | 채널 CRUD Unimplemented |
| `/admin/telegram` | Telegram Ops (구 `/admin/openclaw` — OpenClaw 제외, STEP57-1) |
| `/admin/operations` | backup dump/restore · 앱 로그 테일 Unimplemented |
| User watchlist/preferences/inbox/equity-history/dart summarize | UnimplementedNotice |
| Admin portfolio | 여전히 step32 API 일부 호출 가능 |

## 메뉴 ↔ 라우트

- Admin/User `routes.ts` ↔ `menu.tsx` ↔ `page.tsx`: **하드 누락 없음**
- 호환 redirect: `/admin/market`→data→monitoring, `/admin/positions`→portfolio, `/admin/settings`→env-settings

---

# Architecture Debt

## 현재 구조 (요약)

```
src/stock_platform/   # 도메인 폴더 혼재 (중복 패키지 포함)
  api/v1/             # 라우터 다수 · step32 혼재
frontend/src/
  app/(admin|user)/   # App Router
  features/{admin,user,auth}/
```

## Layer / Clean / DDD 관점

| 관점 | 평가 | 개선점 |
|------|------|--------|
| Layered | FE는 양호. BE는 api↔service 경계 불균일 | Use-case 계층 명시 |
| Clean Architecture | Use-case 약함, 라우터가 진입점 | 도메인 서비스로 로직 집중 유지·문서화 |
| DDD | 폴더명 도메인 지향 | Bounded context 중복 (`broker`/`brokers` 등) 정리 |

## Import / 순환

| 이슈 | 상태 |
|------|------|
| `broker/__init__` ↔ `OrderExecutionService` | STEP53에서 OrderDispatcher eager import 제거로 완화 |
| 미사용 import | 전역 auto-clean은 후속 (ruff unused) — 이번 STEP 미실행 |
| README 위치 | 루트 `README_STEP42–54` vs archive 규칙 불일치 |

## 문서 부채

| 문서 | 이슈 |
|------|------|
| `PROJECT_FINAL_AUDIT.md` | Critical 1–5 중 다수가 STEP52–54로 완화 — **재스코어링 필요** |
| `README_STEP50` | Telegram 수신 “미구현” → STEP54로 **부분 outdated** |
| User account/profile 카피 | ownership “없음” 문구 vs `/paper-accounts/me` |
| 루트 STEP README | `docs/archive/steps` 이관 후보 |

---

# Refactoring Priority

## Critical

1. **`risk/service.py` DB API 복구** + step32 `evaluate`를 `InMemoryRiskGate` 등으로 분리  
   - `/risk-policies`, allocation 파이프라인 파손 위험
2. **FE step32 API 이전** (`/positions`, `/portfolio/summary`, `/dashboard/summary` → Paper/admin-summary)  
   - 이후 `step32_router` unregister

## High

3. `step32_router` 및 InMemory Position/Portfolio 제거 (FE 이전 완료 후)
4. Dead packages 제거: `market/`, `indicator/`(테스트 이전), `strategies/`, empty `dashboard/`, unused `strategy` stubs
5. `/admin/data` 메뉴 라벨 정리 또는 실 “데이터 관리” 페이지 복구
6. `PROJECT_FINAL_AUDIT.md` Critical 재검증·갱신

## Medium

7. deprecated `/api/v1/indicator` router 제거
8. Paper broker adapter 이중화 정리
9. `brokers/` → `broker/quotation` 이동 (점진적)
10. README_STEP42–54를 `docs/`로 이관 + STEP50 문구 갱신
11. User Unimplemented 카피 드리프트 정리 (account/profile)

## Low

12. AI/Strategy API prefix 문서 카탈로그화 (병합은 비권장)
13. ruff unused-import 일괄 정리
14. watchlist / inbox / backup — **신기능**이므로 본 리팩터 계획과 분리 (제품 백로그). OpenClaw는 STEP57-1에서 범위 제외.

---

## 후속 STEP 제안 (실행 시)

| STEP | 범위 |
|------|------|
| 56 | RiskService 복구 + step32 Risk 분리 |
| 57 | FE Paper 이전 + step32_router 제거 |
| 58 | Dead package 삭제 + 테스트 이전 |
| 59 | Admin 메뉴/문서/감사 동기화 |

**원칙:** 한 STEP에 한 축(파손 복구 → FE 이전 → 삭제). 자동매매 본선(`order`, `realtime`, `exit_monitor`, `notification`)은 건드리지 않는다.
