# MENU M5-B — Technical Tab SECTION_REORGANIZE

**Mode:** APPLY (UI order only) · **Verdict:** `TECHNICAL_SECTION_REORGANIZE_READY_WITH_LIMITATIONS`  
**Date:** 2026-08-15  
**Baseline:** M5-B0 `TECHNICAL_TAB_SECTION_REORGANIZE` · M5-A `285b521`  
**File:** `frontend/src/features/admin/upbit/UpbitOpportunityScannerPanel.tsx`

> Component split **없음**. API/mutation/policy **변경 없음**.  
> commit/push = 사용자 승인 후 선별.

---

## 1. BEFORE / AFTER order

| BEFORE | AFTER |
|--------|-------|
| mixed tags + Dry Run + Evaluate + refresh | **Scanner 상태** (scanner tags · Dry Run · refresh · Scanner Status) |
| Scanner Status | **후보 / AI 분석** (Last Top Candidates) |
| Shadow Evaluator Scheduler | **Paper Shadow** (Active → Completed) |
| Last Top Candidates | **Shadow 평가** (evaluator tag · Evaluate · Evaluator Scheduler) |
| Paper heading · Cohort JSON · Active · Completed | **Cohort 성과** (cohort/mismatch tags · Stats JSON; milestone 전용 UI 없음) |

---

## 2. Unchanged contracts

| Item | Before | After |
|------|--------|-------|
| LOC | 219 | **248** (headings/descriptions only) |
| useState / useEffect | 0 / 0 | 0 / 0 |
| useQuery / useMutation | 1 / 2 | 1 / 2 |
| Handlers | 3 onClick | 3 |
| API | GET status · POST run · POST evaluate | same |
| Endpoints | unchanged | unchanged |
| force_ai / notify | false / true | same |
| Split files | none | none |

---

## 3. Policy / safety

Scanner/Shadow/Cohort thresholds · Top-N · TP/SL · AI gate · SHADOW_ONLY — **미변경**.  
LIVE/ARM/Scheduler mut on upbit — **0**.  
TradingOrder/Outbox — **0**.  
risk page — **미수정**.

---

## 4. M5-A regression

Tabs 5 · Technical mount panel=1 · News/A-B/Ops props 유지.

---

## 5. Tests

`upbitTechnicalSectionOrder.test.ts` + hub/live regression — **16 passed**.  
eslint changed files — PASS.  
tsc M5-B 신규 — **0** (기존 WIP 분리).

---

## 6. Changed files

| File | Role |
|------|------|
| `UpbitOpportunityScannerPanel.tsx` | section reorder only |
| `upbitTechnicalSectionOrder.test.ts` | **new** |
| `docs/audit/MENU_M5B_TECHNICAL_SECTION_REORGANIZE.md` | this |
| Canonical + audit README | status |

**Not touched:** Ambiguous, NewsCollector, risk, HubTabs, Ops, backend.

---

## 7. Limitations

1. Intro copy에 “Paper Shadow” 문구 잔존 (섹션 제목과 문자열 중복 → 테스트는 card title 순서 사용).  
2. Confirm modal 미추가 (동작 변경 금지).  
3. Milestone 전용 UI 없음 — cohort_status 필드만 Cohort 영역.

---

## 8. Next STEP (exactly one)

**M5-C0 — News Pipeline tab structure PRECHECK** (승인 전 구현 금지)
