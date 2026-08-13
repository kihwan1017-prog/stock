# ROADMAP

**역할:** 자동매매·플랫폼 잔여 작업 (P0–P5).  
**최종 갱신:** 2026-08-13  

**Ops note (2026-08-13):** Shadow cohort milestone watch — `SAMPLE_ACCUMULATING` until VALID≥30 ∧ new-policy MATCH≥10 ∧ mismatch=0 → 1회 `SHADOW_COHORT_30_REVIEW_READY`. 정책/threshold 변경 없음. SHADOW_ONLY 유지.  
**News note (2026-08-13):** STEP N2 Collector READY — COLLECT only. Next: **N3 Symbol Mapping** (AI/Scanner/Gate 연동 금지 유지).  
**P0 ID는 PHASE 2 Canonical 고정** (PHASE 1 remaining-work 파일의 P0 번호와 다를 수 있음 → **본 문서 우선**).

상태 값: `OPEN` · `IN_PROGRESS` · `BLOCKED` · `DONE` · `DEFERRED`

**종합 (추정):** 개발 ~78% · Paper ~78% · LIVE ~52% · 운영 **NOT READY** · LIVE **NOT APPROVED** · Paper 무인 **PARTIAL**  
→ [PROJECT_IMPLEMENTATION_STATUS.md](PROJECT_IMPLEMENTATION_STATUS.md)

---

## P0 — 실거래·배포·데이터 정합성 차단

### P0-1 — Realtime `broker_code="KIWOOM"` 하드코딩

| 필드 | 내용 |
|------|------|
| 우선순위 | P0 |
| 시장 | Upbit / Kiwoom |
| 문제 | Realtime 주문 경로가 broker를 KIWOOM으로 고정 → 잘못된 Outbox enqueue |
| 완료 조건 | Scope·UBA의 `broker_code`로 enqueue |
| 상태 | **IN_PROGRESS** (코드: `risk_integrated_order_executor` scope/exchange resolve, 미커밋) |

### P0-2 — Kiwoom Fill → TradingOrder → Position/Balance/P&L 단절

| 필드 | 내용 |
|------|------|
| 우선순위 | P0 |
| 시장 | Kiwoom LIVE |
| 문제 | Fill이 pending 수준에 머물고 TradingOrder/Position 장부와 미연결 |
| 완료 조건 | WS/폴링 event → order state → position/balance 경로 |
| 상태 | **IN_PROGRESS** (WS→ExecutionSync bridge 추가; LIVE Position 원장 WRITE는 OPEN) |

### P0-3 — STEP12 Lifecycle/Registration/Deployment ↔ Scoped Runtime 불일치

| 필드 | 내용 |
|------|------|
| 우선순위 | P0 |
| 시장 | ALL |
| 문제 | Registry `running=false`, inactive links, READY_TO_START ≠ loader ACTIVE |
| 완료 조건 | 상태 모델 문서화 + 명시적 Promote-to-ACTIVE(기본 OFF) |
| 상태 | **IN_PROGRESS** (`runtime_start_service` + admin `/runtime-start`, Runner auto-start OFF) |

### P0-4 — Git 커밋 Alembic Head ↔ 워킹트리 Head 불일치

| 필드 | 내용 |
|------|------|
| 상태 | **DONE** (Git head `a7f3e91c4d28`, 운영 DB upgrade는 별도 Gate) |

### P0-5 — Paper Outbox ACCEPTED → PaperExecutionService 자동 Fill 부재

| 필드 | 내용 |
|------|------|
| 우선순위 | P0 |
| 시장 | Stock/Crypto Paper |
| 문제 | Outbox ACCEPT ≠ 자동 fill/position |
| 완료 조건 | 플래그 ON 시 fill→position; LIVE 혼입 금지 |
| 상태 | **IN_PROGRESS** (`PaperOutboxFillService` + outbox_worker hook, `paper_outbox_auto_fill`) |

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
