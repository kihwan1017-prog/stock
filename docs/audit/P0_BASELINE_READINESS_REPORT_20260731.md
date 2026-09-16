# P0 BASELINE READINESS REPORT — 2026-07-31

P0 구현 **시작 전** 기준선. 소스 수정 없음.  
P0 ID: [docs/ROADMAP.md](../ROADMAP.md) Canonical.

---

## 종합

| P0 | 지금 코딩 시작? | 차단 |
|----|-----------------|------|
| P0-4 Alembic head | **커밋 패키징으로 해소** (코드 버그 아님) | 미커밋 22 rev |
| P0-1 broker hardcode | **조건부 YES** | dirty WT 혼선 위험 → docs+UBA+STRAT12 커밋 후 권장 |
| P0-2 Kiwoom Fill | **조건부 YES** | STRAT12와 무관 · 별도 브랜치/커밋 |
| P0-5 Paper auto-fill | **조건부 YES** | 동일 |
| P0-3 STEP12↔Runtime | **NO** until CP-05 | Registry 코드가 WT에만 있음 |

권장 기준선: **CP-01…CP-07 커밋 완료 후** `release/v1.1.0` (또는 전용 브랜치)에서 P0 작업.

---

## P0-4 — Alembic commit/head mismatch

| 항목 | 내용 |
|------|------|
| 성격 | **정상적인 미커밋 head 차이** + 배포 시 위험 |
| Chain 오류? | **아니오** — 단일 head `a7f3e91c4d28`, `ae5f6a7b8c9d` 조상 |
| 선행 Package | CP-04 → CP-05 |
| 선행 테스트 | step_2_5_* · step12_* · migration_helpers |
| Branch | 현재 `release/v1.1.0` |
| 즉시 시작 | “수정 코딩” 불필요 — **커밋 실행**이 해법 |
| 배포 절차 | 커밋 없이 운영 upgrade 금지 |

---

## P0-1 — Realtime `broker_code="KIWOOM"` hardcoding

| 항목 | 내용 |
|------|------|
| 선행 Package | 권장: docs+UBA+STRAT12 커밋으로 WT 정리 |
| 선행 테스트 | realtime/order unit + scope |
| 즉시 시작 | 가능하나 **다른 WIP와 한 커밋에 섞지 말 것** |
| 차단 | 없음 (논리) · 프로세스상 dirty 권장 |

---

## P0-2 — Kiwoom Fill → TradingOrder → Position

| 항목 | 내용 |
|------|------|
| 선행 | 없음 (STRAT12 비의존) |
| 테스트 | mock WS + DB |
| 즉시 | YES on clean tree 권장 |
| LIVE | 별도 승인 · Mock only 기본 |

---

## P0-5 — Paper Outbox → PaperExecutionService

| 항목 | 내용 |
|------|------|
| 선행 | 없음 |
| 테스트 | Paper E2E |
| 즉시 | YES on clean tree 권장 |
| 안전 | Paper only flag |

---

## P0-3 — STEP12 Registry/Deployment ↔ Scoped Runtime

| 항목 | 내용 |
|------|------|
| 선행 Package | **CP-05 필수** (registry/readiness 코드) |
| 선행 테스트 | test_step12_18/19 · runtime bootstrap |
| 즉시 | **NO** |
| 차단 | 미커밋 STRAT-12 · 설계상 자동 start OFF 유지 |

---

## 권장 시퀀스

```text
Commit CP-01 … CP-07 (승인 후)
  → tag/note: alembic head a7f3e91c4d28
  → P0-4 closed as “committed”
  → P0-1 / P0-5 / P0-2 (우선순위 ROADMAP)
  → P0-3 last among runtime-touching
```

**본 단계 STOP:** P0 구현·commit 실행 없음.
