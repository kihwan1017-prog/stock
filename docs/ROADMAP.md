# ROADMAP

**역할:** 자동매매·플랫폼 잔여 작업 (P0–P5).  
**최종 갱신:** 2026-07-31  
**P0 ID는 PHASE 2 Canonical 고정** (PHASE 1 remaining-work 파일의 P0 번호와 다를 수 있음 → **본 문서 우선**).

상태 값: `OPEN` · `IN_PROGRESS` · `BLOCKED` · `DONE` · `DEFERRED`

**종합 (추정):** 개발 ~76% · Paper ~72% · LIVE ~48% · 운영 **NOT READY** · LIVE **NOT APPROVED** · Paper 무인 **NOT READY**  
→ [PROJECT_IMPLEMENTATION_STATUS.md](PROJECT_IMPLEMENTATION_STATUS.md)

---

## P0 — 실거래·배포·데이터 정합성 차단

### P0-1 — Realtime `broker_code="KIWOOM"` 하드코딩

| 필드 | 내용 |
|------|------|
| 우선순위 | P0 |
| 시장 | Upbit / Kiwoom |
| 문제 | Realtime 주문 경로가 broker를 KIWOOM으로 고정 → 잘못된 Outbox enqueue |
| 선행 | — |
| 변경 예정 | realtime order executor / submit 경로 |
| 완료 조건 | Scope·UBA의 `broker_code`로 enqueue |
| 필수 테스트 | unit + scope integration |
| 안전 | LIVE OFF 유지; 실주문 없이 Mock |
| 상태 | OPEN |

### P0-2 — Kiwoom Fill → TradingOrder → Position/Balance/P&L 단절

| 필드 | 내용 |
|------|------|
| 우선순위 | P0 |
| 시장 | Kiwoom LIVE |
| 문제 | Fill이 pending 수준에 머물고 TradingOrder/Position 장부와 미연결 |
| 선행 | 설계 문서; P0-1 권장 |
| 변경 예정 | Kiwoom fill sync / reconcile |
| 완료 조건 | WS/폴링 event → order state → position/balance 경로 |
| 필수 테스트 | mock WS + DB |
| 안전 | 실계좌 없이 Mock; LIVE smoke는 별도 승인 |
| 상태 | OPEN |

### P0-3 — STEP12 Lifecycle/Registration/Deployment ↔ Scoped Runtime 불일치

| 필드 | 내용 |
|------|------|
| 우선순위 | P0 |
| 시장 | ALL |
| 문제 | Registry `running=false`, inactive links, READY_TO_START ≠ loader ACTIVE; 자동 연결 부재 |
| 선행 | P0-4 (커밋/head) 권장 |
| 변경 예정 | promotion→activation→registration→runtime bootstrap 정책 |
| 완료 조건 | 상태 모델 문서화 + 명시적 Promote-to-ACTIVE(기본 OFF) |
| 필수 테스트 | step12-18/19 + runtime bootstrap |
| 안전 | 자동 start 기본 OFF |
| 상태 | OPEN |

### P0-4 — Git 커밋 Alembic Head ↔ 워킹트리 Head 불일치

| 필드 | 내용 |
|------|------|
| 우선순위 | P0 |
| 시장 | — |
| 문제 | baseline `3554ef8` head와 WT head(`a7f3e91c4d28` 등) 불일치 |
| 선행 | STEP12/FE/UBA 커밋 경계 계획 |
| 변경 예정 | migrations 커밋 단위; DB sync 절차 |
| 완료 조건 | 단일 head 문서화 + 배포 절차와 일치 |
| 필수 테스트 | migration helpers / upgrade dry |
| 안전 | 운영 DB 무단 upgrade 금지 |
| 상태 | OPEN |

### P0-5 — Paper Outbox ACCEPTED → PaperExecutionService 자동 Fill 부재

| 필드 | 내용 |
|------|------|
| 우선순위 | P0 |
| 시장 | Stock/Crypto Paper |
| 문제 | Outbox ACCEPT ≠ 자동 fill/position |
| 선행 | — |
| 변경 예정 | Paper execution 연결 또는 명시 플래그 정책 |
| 완료 조건 | 플래그 ON 시 fill→position; 기본 안전 동작 문서화 |
| 필수 테스트 | Paper E2E |
| 안전 | 자동 fill은 Paper만; LIVE 경로 혼입 금지 |
| 상태 | OPEN |

---

## P1 — Runtime → Signal → Risk → Order → Broker 연결

| ID | 제목 | 시장 | 선행 | 완료 조건 | 테스트 | 안전 | 상태 |
|----|------|------|------|-----------|--------|------|------|
| P1-1 | Deployment READY_TO_START ↔ loader ACTIVE 정합 | ALL | P0-3,P0-4 | 명시 게이트 | step12-19 | 기본 OFF | OPEN |
| P1-2 | Runtime Registration → active AccountStrategyLink | ALL | P1-1 | 이중승인 후 is_active | step12-18 | 기본 OFF | OPEN |
| P1-3 | Session OPEN ↔ Runner start 정책화 | ALL | P1-2 | 플래그로만 자동 start | session scheduler | 기본 OFF | OPEN |
| P1-4 | Signal → Order E2E (Paper) | Paper | P0-1,P0-5,P1-2 | Hub→outbox→fill→position | Paper E2E | Paper only | OPEN |
| P1-5 | Kiwoom realtime MD 또는 배치 신호 경로 제품 결정 | KRX | — | 결정+문서 | — | — | OPEN |

---

## P2 — Fill → Position → Balance → P&L → Recovery

| ID | 제목 | 선행 | 완료 조건 | 상태 |
|----|------|------|-----------|------|
| P2-1 | Kiwoom pending ↔ TradingOrder reconcile | P0-2 | conflict UI+서비스 | OPEN |
| P2-2 | Settlement/Ledger UBA·Paper FK 완성 | P0-4 | migration+tests | OPEN |
| P2-3 | Intraday PnL snapshot | P2-2 | API+dashboard | OPEN |

---

## P3 — Backtest / Paper / Performance / Risk 검증

| ID | 제목 | 완료 조건 | 상태 |
|----|------|-----------|------|
| P3-1 | Paper validation gate before LIVE promotion | 정책+테스트 | OPEN |
| P3-2 | Walk-forward/QG → Deployment 게이트 강제 | 코드 연결 | OPEN |
| P3-3 | Performance/Risk 리포트 운영 대시보드 | FE+API | OPEN |

---

## P4 — Monitoring / Notification / Backup / Runbook

| ID | 제목 | 완료 조건 | 상태 |
|----|------|-----------|------|
| P4-1 | Backup restore API (FE TODO) | POST ops restore | OPEN |
| P4-2 | Full autotrading runbook (Paper vs LIVE) | `docs/operations/` | OPEN |
| P4-3 | Outbox/fill/runner metrics | dashboard | OPEN |
| P4-4 | Kill Switch / Recovery conflict 알림 확장 | telegram events | OPEN |

---

## P5 — 문서 · Legacy · 중복 정리

| ID | 제목 | 완료 조건 | 상태 |
|----|------|-----------|------|
| P5-1 | PHASE 2 Canonical 문서 표준화 | 본 PHASE 완료보고 | **DONE** (승인 대기) |
| P5-2 | PHASE 3 Archive 이동 계획 실행 | 사용자 승인 후 이동 | OPEN |
| P5-3 | Deprecated `alembic/versions` 정리 | ARCHIVE 표기 | OPEN |
| P5-4 | Dual dashboard router 문서화/통합 | KEEP or CONSOLIDATE | OPEN |

---

## 권장 실행 순서

1. P0-4 (커밋/head) → P0-1 (broker hardcode) → P0-5 (Paper fill)  
2. P0-3 / P1-1 / P1-2 (STEP12↔Runtime, 기본 OFF)  
3. P1-4 Paper E2E  
4. P0-2 / P1-5 Kiwoom  
5. P5 Archive (승인 후)

관련: [PROJECT_IMPLEMENTATION_STATUS.md](PROJECT_IMPLEMENTATION_STATUS.md) · [audit/PROJECT_REMAINING_WORK_20260731.md](audit/PROJECT_REMAINING_WORK_20260731.md) (Historical 초안)
