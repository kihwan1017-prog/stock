# PROJECT REMAINING WORK — 2026-07-31

자동매매 완성용 잔여 작업. **구현하지 않음** — 계획만.

권장 STEP 번호는 `STEP_NUMBER_MAPPING_20260731.md`의 Canonical 규칙 준수 (번호 충돌 금지).

---

## P0 — LIVE 안전 차단 요소

| ID | 제목 | 시장 | 선행 | 완료 조건 | 테스트 | 위험 | 권장 STEP |
|----|------|------|------|-----------|--------|------|-----------|
| P0-1 | Realtime executor broker_code 하드코딩 제거 | Upbit/Kiwoom | — | Scope의 broker_code로 Outbox enqueue | unit + scope integration | 잘못된 브로커로 LIVE 주문 | STEP8-RT-1 또는 STEP13-1 (신규 네임스페이스 명시) |
| P0-2 | LIVE 기본 fail-closed 회귀 고정 | ALL | — | startup policy + settings validate 테스트 유지 | `startup_runtime_policy` tests | 기본 LIVE ON | 기존 STEP8/10 보강 |
| P0-3 | Kiwoom Fill → TradingOrder/Position 연결 설계 | Kiwoom LIVE | P0-1 | WS event → order state → position 경로 문서+코드 | mock WS + DB | 이중장부 | STEP13-KRX-FILL |
| P0-4 | 워킹트리 커밋 경계 / head 동기화 | — | — | STEP12 vs FE fix 분리 커밋; alembic head 일치 | migration tests | 배포 불일치 | chore |

---

## P1 — 자동매매 실행 연결

| ID | 제목 | 시장 | 선행 | 완료 조건 | 테스트 | 권장 STEP |
|----|------|------|------|-----------|--------|-----------|
| P1-1 | STEP12 Deployment READY_TO_START ↔ loader ACTIVE 정합 | ALL | P0-4 | 명시적 Promote-to-ACTIVE 게이트 또는 loader 확장 | step12-19/18 | STEP12-21 (신규, 12 계열 유지) |
| P1-2 | Runtime Registration → active AccountStrategyLink 승인 게이트 | ALL | P1-1 | 이중승인 후 is_active=true 가능 | step12-18 | STEP12-21 |
| P1-3 | Session OPEN ↔ Runner start 정책화 | ALL | P1-2 | 설정 플래그로만 자동 start (기본 OFF) | session scheduler | STEP9-EXT |
| P1-4 | Signal → Order E2E (Paper) | Paper | P0-1,P1-2 | Hub inject → outbox → paper fill → position | new E2E | STEP12-22 / PAPER-E2E |
| P1-5 | Kiwoom realtime market data 또는 배치 신호 경로 명확화 | KRX | — | 제품 결정: RT 도입 vs 일봉만 | — | STEP13-KRX-MD |

---

## P2 — 계좌·잔고·포지션 일관성

| ID | 제목 | 선행 | 완료 조건 | 권장 STEP |
|----|------|------|-----------|-----------|
| P2-1 | Paper Outbox ACCEPT → optional auto-fill policy | P1-4 | 명시 플래그로 PaperExecution 연결 | PAPER-FILL |
| P2-2 | Kiwoom pending ↔ TradingOrder reconcile | P0-3 | conflict UI+서비스 | STEP8-5-x 연장 |
| P2-3 | Settlement/Ledger UBA·Paper FK 완성 | WIP migrations | migration+tests green | 2.5.x 완료 |
| P2-4 | Intraday PnL snapshot | P2-1 | API+dashboard | OPS-PNL |

---

## P3 — 전략 검증

| ID | 제목 | 완료 조건 | 권장 STEP |
|----|------|-----------|-----------|
| P3-1 | STEP12 docs under `docs/ai/` or `docs/development/` | Canonical MD | DOC-12 |
| P3-2 | Paper validation gate before LIVE promotion | 정책+테스트 | STEP12-23 |
| P3-3 | Walk-forward/QG 결과를 Deployment 게이트에 강제 | 코드 연결 | STEP12-19 보강 |

---

## P4 — 운영 안정성

| ID | 제목 | 완료 조건 |
|----|------|-----------|
| P4-1 | Backup restore API (FE TODO) | POST ops backup restore |
| P4-2 | Full autotrading runbook (Paper vs LIVE) | `docs/operations/` Canonical |
| P4-3 | Metrics for outbox lag / fill lag / runner health | dashboard blocks |
| P4-4 | Notification on Kill Switch / Recovery conflict | telegram RO already; expand events |

---

## P5 — 문서·유지보수

| ID | 제목 | 완료 조건 |
|----|------|-----------|
| P5-1 | PHASE 2: AGENTS.md / CLAUDE.md / Cursor rules 표준화 | 사용자 승인 후 |
| P5-2 | Root audit MD → archive | 승인 후 이동 |
| P5-3 | STEP namespace 표기 통일 | STEP_MASTER_STATUS |
| P5-4 | Deprecated `alembic/versions` overlay 정리 | ARCHIVE |
| P5-5 | Dual dashboard router 문서화 또는 통합 계획 | KEEP/CONSOLIDATE |

---

## 우선 실행 순서 (권장)

1. P0-4 (커밋/head) → P0-1 (broker hardcode) → P0-2 회귀  
2. P1-1/P1-2 (STEP12→Runtime 정합, 기본 OFF)  
3. P1-4 Paper E2E  
4. P0-3 / P1-5 Kiwoom  
5. P5 문서 표준화 (병렬 가능, 코드 P0와 분리)
