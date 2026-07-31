# PROJECT FOUNDATION AUDIT — 2026-07-31

- **모드:** PHASE 1 읽기 전용 (소스·기존 MD·Migration 미수정)
- **경로:** `D:\Projects\stock-platform`
- **판정 요약:** `READY_WITH_LIMITATIONS_FOR_DOCUMENTATION_STANDARDIZATION`
- **원칙:** 문서보다 실제 호출되는 소스·Migration·테스트·설정을 우선

---

## 1. Git / 환경 기준선 (감사 시작 시점)

| 항목 | 값 |
|------|-----|
| Branch | `release/v1.1.0` |
| HEAD | `3554ef8` — `STEP11 completed` (tracks `origin/release/v1.1.0`) |
| Working tree | **더티** — 수정 ~70+, 미추적 STEP12/UBA FK/감사 문서 다수 (~135 status lines) |
| Python | 3.12.10 |
| Node / npm | v24.18.0 / 11.16.0 |
| Backend 진입 | `src/stock_platform/api/main.py` → `lifecycle.py` → `router.py` |
| Frontend 진입 | `frontend/` Next.js App Router (`app/(admin|user|auth)`) |
| Alembic | `alembic.ini` → `database/alembic` |
| Working-tree Alembic head | **단일** `a7f3e91c4d28` (operation_readiness) — *미커밋 STEP12 migration 포함* |
| Committed baseline | `3554ef8` 기준 STEP11 lifecycle `ae5f6a7b8c9d`까지 포함; STEP12 체인 미커밋 |
| Migration 파일 수 | `database/alembic/versions` **130** |
| Deprecated overlay | 루트 `alembic/versions/` (5) — 적용 금지 |
| Backend tests | `tests/test_*.py` **276** 파일 |
| Frontend | page.tsx **99**, vitest **40** |
| Markdown | 루트 ~53 + `docs/**` ~296 |

**중요:** 본 감사는 **워킹트리 현재 상태**(미커밋 STEP12 포함)와 **마지막 커밋 `3554ef8`**를 구분한다. 구현률·연결 판정은 워킹트리 코드 기준이다.

---

## 2. 프로젝트 성격 (전제 정정)

이 저장소는 “초기 STEP11”이 아니라:

1. **메인 빌드 시퀀스** (archive STEP16–75, v1.0.0 / v1.1.0 릴리스)
2. **감사 21단계** (`docs/audit/STEP01–21`)
3. **서브시리즈** (STEP8 브로커격리, STEP10 운영, STEP11 AI, **STEP12 Strategy Draft**)

이 혼재한다. 상세는 `STEP_NUMBER_MAPPING_20260731.md`.

---

## 3. 구현률 (규칙 §8 — 파일 수 금지)

| 영역 | 점수 | 근거 요약 |
|------|------|-----------|
| 공통 플랫폼 | **88%** | startup/lifecycle, settings, middleware, fail-closed LIVE |
| 회원·권한 | **90%** | JWT+RBAC+ownership, 테스트 다수 |
| 계좌 | **85%** | UBA+Paper+Vault; soft-delete/FK 보강 진행중(미커밋) |
| Market Data | **70%** | Upbit WS·일봉 수집; **Kiwoom 실시간 시세 없음** |
| Candidate | **80%** | Screener+STEP11 lifecycle 연결(수동 promotion) |
| AI | **78%** | Provider~Lifecycle 구현; LIVE AI 기본 차단 |
| Strategy Lifecycle | **72%** | STEP12 Request→…→Registration **워크플로 검증**; Runtime 자동 기동 **없음** |
| Backtest | **80%** | Engine+STEP12 backtest path; Runtime 미연동 |
| Risk | **88%** | kill switch, guards, policies; realtime 이중검증 일부 skip |
| Runtime | **65%** | Scoped runtime 존재; STEP12 registry와 **상태 불일치** |
| Scheduler | **68%** | Session/outbox/recovery; MARKET_OPEN≠runner start |
| Kiwoom MOCK | **75%** | Mock REST 경로 |
| Kiwoom LIVE | **45%** | 주문 REST+게이트; **Fill→Position 단절**, 실시간 시세 없음 |
| Upbit LIVE | **62%** | Fill sync·reconcile 양호; realtime executor **broker_code=KIWOOM 하드코딩** |
| Stock Paper | **78%** | 주문/계좌; Outbox→auto-fill 약함 |
| Crypto Paper | **72%** | Upbit paper/mock |
| Order | **85%** | Outbox SKIP LOCKED |
| Execution/Fill | **60%** | Upbit 강함 / Kiwoom·Paper outbox 약함 |
| Position | **65%** | Paper apply_fill; Live Kiwoom 약함 |
| Balance/PnL | **60%** | Settlement 배치; intraday 약함 |
| Recovery/Recon | **75%** | Startup+periodic; Kiwoom TradingOrder 통합 미완 |
| Frontend | **80%** | 99 pages, 다수 API 연결; 일부 stub |
| Security | **82%** | fail-closed, ownership; /version 공개 등 LOW |
| Operations | **78%** | health, telegram RO, dashboards |
| Tests | **80%** | 기본 suite 풍부; full E2E autotrading 부재 |
| Documentation | **45%** | Canonical 분산·루트 중복·STEP12 docs 부재 |

### 전체 3지표 (합치지 않음)

| 지표 | 점수 | 의미 |
|------|------|------|
| **개발 구현률** | **~76%** | 플랫폼·워크플로·API·테스트 가중 |
| **Paper 자동매매 준비도** | **~72%** | Paper 주문·계좌·리스크는 가능; 무인 E2E·fill 자동화 미완 |
| **LIVE 자동매매 준비도** | **~48%** | 안전 게이트는 강함; Fill/Signal/STEP12→Runtime 갭으로 LIVE 완성 미달 |

---

## 4. Critical / High 이슈 (요약)

1. **STEP12 → Runtime 자동 연결 없음** (의도적 docstring) — Registration `running=false`, link `is_active=false`, Deployment `READY_TO_START` vs loader `ACTIVE` only  
2. **Realtime executor `broker_code="KIWOOM"` 하드코딩** — Upbit scope 신호 실행 경로 오류  
3. **Kiwoom LIVE Fill → TradingOrder/Position 미연결** (pending table만)  
4. **Kiwoom 실시간 Market Data 없음**  
5. **PAPER Outbox ACCEPT ≠ PaperExecutionService fill**  
6. **워킹트리 미커밋 STEP12 + FE Form 수정** — 문서 표준화 전 커밋 경계 정리 필요  

---

## 5. 산출물 인덱스

| 문서 | 내용 |
|------|------|
| `AUTOTRADING_EXECUTION_FLOW_AUDIT_20260731.md` | Hop 판정 |
| `PROJECT_IMPLEMENTATION_STATUS_DRAFT_20260731.md` | 영역별 현황 |
| `PROJECT_REMAINING_WORK_20260731.md` | P0–P5 |
| `SOURCE_COMPONENT_INVENTORY_20260731.md` | 패키지·라우터 |
| `DATABASE_MIGRATION_AUDIT_20260731.md` | DB/Alembic |
| `TEST_COVERAGE_AUDIT_20260731.md` | 테스트 |
| `MARKDOWN_DOCUMENT_AUDIT_20260731.md` | MD 분류 |
| `STEP_NUMBER_MAPPING_20260731.md` | STEP 충돌 |
| `AI_DOCUMENTATION_STANDARDIZATION_PLAN_20260731.md` | PHASE 2+ 설계 |

---

## 6. STOP GATE

PHASE 1만 완료. AGENTS/CLAUDE/Rules 생성, 문서 이동·삭제, 소스 정리, 다음 STEP 구현은 **사용자 승인 후**.
