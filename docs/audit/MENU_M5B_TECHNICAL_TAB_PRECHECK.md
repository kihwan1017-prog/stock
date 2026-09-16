# MENU M5-B0 — Technical Tab Structure Precheck

**Mode:** PRECHECK / DESIGN ONLY · **Verdict:** `TECHNICAL_TAB_SECTION_REORGANIZE`  
**Date:** 2026-08-15  
**Baseline commit:** `285b5218989b3069131a51e488dad3f500678b6e`  
**Panel:** `frontend/src/features/admin/upbit/UpbitOpportunityScannerPanel.tsx`  
**Host:** `/admin/upbit` → Technical tab (`UpbitHubTabs` · `technical` prop)

> Production code **변경 없음**. commit **없음**. M5-B 구현 **금지**.  
> Scanner/Shadow/Cohort **정책 변경 없음**. LIVE/TradingOrder **미실행**.

---

## 0. Executive summary

`UpbitOpportunityScannerPanel`은 **LOC 219**, `useState`/`useEffect` **0**, API는 **단일 GET status**에 Scanner·Evaluator·Candidates·Shadows·Cohort가 모두 실려 있고 mutation은 **Dry Run / Shadow 평가 2개**뿐이다.

파일 크기·복잡도만으로는 **COMPONENT_SPLIT 근거 부족**.  
다만 UI 순서가 `Evaluator → Candidates → Cohort JSON → Shadow tables`로 **desired flow와 어긋나** 있으며 heading이 Scanner/Paper Shadow 2단만 있어 discoverability가 낮다.

**권장: OPTION B — SECTION_REORGANIZE** (파일 1개 유지 · section heading/순서만 정리).

---

## 1. Inventory (존재하는 것만)

| ID | Area | Present? | Where |
|----|------|----------|-------|
| A | Scanner | **YES** | status tags · Scanner Status JSON · Dry Run |
| B | Technical Candidate | **YES** | Last Top Candidates table (`summary.candidates`) |
| C | Market AI status | **PARTIAL** | candidate/shadow `recommendation`/`confidence`/`risk` columns · status `ai_calls` — **전용 Market AI UI 없음** |
| D | Shadow | **YES** | Active/Completed tables · Paper Shadow heading |
| E | Shadow evaluation | **YES** | Shadow Evaluator Scheduler JSON · 「Shadow 평가」button |
| F | Cohort | **YES** | header `cohort_n`/`cohort_status` tags · Shadow Stats / Cohort JSON |
| G | Milestone | **NO dedicated UI** | `cohort_status` 필드가 stats에 올 수 있음 · `SHADOW_COHORT_30_REVIEW_READY` 전용 화면 **없음** |
| H | Statistics | **YES** | shadowStats JSON card · scanner summary counters |
| I | Manual actions | **YES** | Dry Run · Shadow 평가 · 새로고침 |
| J | 기타 | evaluator scheduler status only | — |

**Invented UI 없음** (Market AI / Milestone 신규 화면 제안하지 않음).

---

## 2. LOC / Complexity

| Metric | Value |
|--------|------:|
| total LOC | **219** |
| JSX LOC (from `return`) | **145** |
| `useState` | **0** |
| `useEffect` | **0** |
| `useQuery` hooks | **1** |
| `useMutation` hooks | **2** |
| onClick handlers | **3** (run / evaluate / refetch) |
| API client calls used | **3** (1 GET + 2 POST) |
| AdminJsonCard | **3** |
| AdminDataTable | **3** |
| Typography.Title sections | **2** |

**Practical complexity:** **LOW–MEDIUM**  
선형 렌더 · 분기 거의 없음 · 로컬 상태 머신 없음 · 데이터 파싱(`asRecord`/`Array.isArray`)만 존재.  
Cyclomatic 도구 미사용.

---

## 3. UI sections (render order)

| # | Section | Purpose | API source | Local state | Mutation | Dependencies |
|---|---------|---------|------------|-------------|----------|--------------|
| 1 | Title + description | SHADOW_ONLY 고지 | — | — | no | — |
| 2 | Status Tags + Actions | enabled/mode/running/evaluator/cohort/mismatch + buttons | GET status | — | Dry Run / Evaluate / Refetch | same query |
| 3 | Scanner Status | scanner run counters + last summary funnel | GET status (`st` + `summary`) | — | no | #2 |
| 4 | Shadow Evaluator Scheduler | evaluator loop status | GET status (`evaluator`) | — | no | #2 |
| 5 | Last Top Candidates | technical Top-N + AI fields | GET status (`summary.candidates`) | — | no | #3 (same payload) |
| 6 | Paper Shadow heading | shadow domain intro | — | — | no | — |
| 7 | Shadow Stats / Cohort | cohort/stats dump | GET status (`shadows.stats`) | — | no | #2 tags |
| 8 | Active Shadows | open paper shadows | GET status (`shadows.active`) | — | no | #7 domain |
| 9 | Completed Shadows | closed paper shadows | GET status (`shadows.completed`) | — | no | #7 domain |

---

## 4. API dependency

| Client | HTTP | Path | Used by panel? | Sections |
|--------|------|------|----------------|----------|
| `getUpbitOpportunityScannerStatus` | **GET** | `/admin/upbit/opportunity-scanner/status` | **YES** | all READ |
| `runUpbitOpportunityScanner` | **POST** | `/admin/upbit/opportunity-scanner/run` | **YES** | Manual Dry Run |
| `evaluateUpbitOpportunityShadows` | **POST** | `/admin/upbit/opportunity-scanner/shadows/evaluate` | **YES** | Manual Shadow 평가 |
| `listUpbitOpportunityShadows` | **GET** | `/admin/upbit/opportunity-scanner/shadows` | **NO** (adminApi만 존재) | — |

PUT/DELETE: **없음**.

두 mutation 모두 성공 시 **동일** `queryKeys.admin.upbitOpportunityScanner()` invalidate.

---

## 5. Mutations

| UI | Endpoint | Safety | TradingOrder? | Shadow-only? | Confirm | Location |
|----|----------|--------|---------------|--------------|---------|----------|
| Dry Run 1회 | POST `.../run` `{notify:true, force_ai:false}` | message: SHADOW ONLY / LIVE ORDER NO | **NO** | **YES** | **없음** (즉시 mutate) | header actions |
| Shadow 평가 | POST `.../shadows/evaluate` `{}` | message: 주문 없음 | **NO** | **YES** | **없음** | header actions |
| 새로고침 | GET refetch | READ | NO | — | — | header |

LIVE/ARM/Scheduler/order-place mutation: **0** (재확인).

---

## 6. Coupling

| Shared | Evidence |
|--------|----------|
| Shared API response | 단일 `status.data` → scanner + evaluator + candidates + shadows + stats |
| Shared refresh | 두 mutation → 동일 invalidate; 새로고침 = 동일 query |
| Shared React state | **없음** (`useState` 0) |
| Scanner → Shadow UI feed | candidates/shadows 모두 status 하위; FE에서 Scanner 결과를 Shadow에 직접 넘기지 않음 |
| Shadow → Cohort | `shadows.stats` 동일 payload |

**Classification: `HIGH_COUPLING` (data/API)** · **`LOW_COUPLING` (local UI state)**  
종합 권고 관점: **HIGH_COUPLING** — split 시 GET 중복 또는 prop-drill 강제.

---

## 7–8. Options

### OPTION A — KEEP_SINGLE_PANEL
복잡도↓ · regression↓ · 단 flow/heading 문제 **미해결**.

### OPTION B — SECTION_REORGANIZE ★
파일 유지 · heading/card 순서만 개선 · API/state 중복 0 · cost 낮음 · UX↑.

### OPTION C — COMPONENT_SPLIT
파일 3개+ 가능하나 LOC 219·상태 0·단일 GET으로 **이득 적음** · API/props 중복 또는 부모 컨테이너 필요 · regression↑ · **비권장**.

| Criterion | A | B | C |
|-----------|---|---|---|
| complexity | low | low | medium↑ |
| regression risk | lowest | low | higher |
| testability | ok | ok+ | maybe |
| maintainability | ok | **better** | over-split |
| API duplication | 0 | 0 | risk |
| state duplication | 0 | 0 | risk |
| UX | weak flow | **align flow** | same if careful |
| cost | 0 | **small** | large |

**Recommended: OPTION B**

Split 필요 여부: **NO**  
Heading/section reorder 필요: **YES**

---

## 9. Flow

**Desired (logical):**  
Scanner → Candidate/AI → Shadow → Evaluation → Cohort → Milestone Review

**Current UI:**  
Scanner tags/actions → Scanner Status → **Evaluator** → Candidates → Paper heading → **Cohort stats** → Active → Completed

| Gap | Note |
|-----|------|
| Evaluator before Candidates | 재배치 후보 |
| Cohort JSON before shadow tables | 재배치 후보 (lists → stats 또는 stats를 lists 뒤) |
| Milestone Review | UI 없음 · audit docs DETAIL_ONLY |

**Suggested reorder (design only, M5-B):**  
1 Scanner status · 2 Candidates (AI columns) · 3 Active/Completed Shadows · 4 Evaluator + Evaluate action · 5 Cohort/Stats tags+JSON · (Milestone 신규 UI 금지)

---

## 10. Market AI / Milestone / Cohort review

| Topic | Finding |
|-------|---------|
| Market AI dedicated UI | **없음** — table column만. M5-B에서 신규 금지 |
| Milestone dedicated UI | **없음** — `cohort_*` in stats/tags only |
| Cohort review v2 | `docs/audit/TECHNICAL_SHADOW_COHORT_REVIEW_READY_V2_*` **audit only** — UI 억지 통합 **금지** · DETAIL_ONLY |

---

## 11. M5-A / Safety regression (verify)

| Check | Result |
|-------|--------|
| Technical tab | 1 (`UPBIT_HUB_TAB_KEYS.technical`) |
| Scanner panel JSX mount | **1** (`upbit/page.tsx` only) |
| News/A-B/Ops shell | unchanged this STEP |
| LIVE/ARM/Scheduler mut on upbit | **0** |
| Scanner/Shadow/Cohort policy | untouched |
| TradingOrder / Outbox / create_order | **0** |
| Existing WIP files | untouched |

---

## 12. API / backend / permission / route

| Item | Needed for OPTION B? |
|------|----------------------|
| API change | **NO** |
| Backend change | **NO** |
| Permission / route / AuthGuard / menu | **NO** |

---

## 13. Next STEP (exactly one)

**STEP M5-B — Technical panel SECTION_REORGANIZE only**  
(heading/section order · no policy · no split · no new Market AI/Milestone UI)

승인 전 구현 금지.

---

## 14. Limitations

1. Runtime status payload shape는 FE 파싱 필드 기준 (백엔드 schema 전수 미실시).  
2. `listUpbitOpportunityShadows` unused — 별도 조사 STEP 후보.  
3. Dry Run/Evaluate에 confirm modal 없음 — safety 개선은 본 권고 범위 외(정책 변경과 혼동 주의).
