# MENU M5-D0 — Upbit A/B Experiment Tab Precheck

**Mode:** PRECHECK / DESIGN ONLY · **Verdict:** `AB_EXPERIMENT_TAB_KEEP_AS_IS`  
**Date:** 2026-08-15  
**Baseline commit:** `ffaa247cdc447206842872a306d53d227a10b58a`  
**Panel:** `frontend/src/features/admin/upbit/UpbitNewsCombinedShadowPanel.tsx`  
**Host:** `/admin/upbit` → A/B 실험 tab (`ab={<UpbitNewsCombinedShadowPanel />}`)

> Production mutation **0**. commit/push **없음**. M5-D 구현 **금지**.  
> NewsCollector rowKey WIP · 기타 dirty **미수정**.

---

## 0. Executive summary

A/B 탭은 이미 **단일 EXPERIMENT panel**로 CONTROL Scanner/Shadow와 분리되어 있고, mutation 2개(Run/Evaluate)는 combined-shadow experiment API만 호출한다. LOC **271**, state/effect **0**, UI 흐름도 대체로 status → actions → rows → stats 순서라 **강제 재배치·split 근거가 약하다**.

DB 표본(READ-ONLY): MATCHED completed **2**/20 · NO_NEWS completed **22**/20 → milestone **`NEWS_AB_SAMPLE_ACCUMULATING`** 유지.

**권장: OPTION A — KEEP_AS_IS.**

---

## 1. Complexity

| Metric | Value |
|--------|------:|
| total LOC | **271** |
| JSX LOC | **188** |
| useState / useEffect | **0 / 0** |
| useQuery | **3** |
| useMutation | **2** |
| onClick handlers | **3** (Run / Evaluate / refresh) |
| API functions used | **5** |
| GET | **3** (status / recent / stats) |
| POST mutation | **2** |
| AdminDataTable | **2** |
| AdminJsonCard | **1** |
| Typography.Title | **1** |
| major UI blocks | **~6** (blurb · env tags · latency/coverage · experiment tags · actions · tables+stats) |
| Practical complexity | **LOW–MEDIUM** |

Unused client API: `getUpbitCombinedShadowDiagnostics` (diagnostics는 status payload에 포함).

---

## 2. Feature inventory (존재 여부)

| ID | Feature | Present? | Where |
|----|---------|----------|-------|
| A | Experiment status | YES | `enabled`, `total_rows`, `completed_n` tags |
| B | Sample accumulation | YES | `sample_milestone` tags (status, 20/20 targets) |
| C | MATCHED / NO_NEWS / EXCLUDED | YES | `by_news_context` tags + MATCHED examples table |
| D | Combined Shadow rows | YES | Recent Experiment Rows |
| E | Experimental score | YES | `exp_score` / `experimental_combined_score` columns |
| F | Experimental decision | YES | BOOST/UNCHANGED/DEPRIORITIZE tags + `decision` column |
| G | rank_delta | YES | `Δrank` columns |
| H | evaluation 5/15/30/60 | **PARTIAL** | UI columns show **r60** only (not 5/15/30) |
| I | MFE/MAE | YES | table columns |
| J | coverage/overlap | YES | pret0, funnel_overlap, diagnostics overlap tags |
| K | latency/backlog | YES | N4_pending, medians, capacity, latency_root |
| L | milestone | YES | `sample={milestone.status}` + matched/no_news counts |
| M | Run/Evaluate actions | YES | Experiment Run · Evaluate Pending |
| N | provenance/debug | **PARTIAL** | FUTURE_SIGNAL_AT · root · pipeline env · stats JSON; dedicated provenance table **없음** |

**없음(신규 발명 금지):** Apply Trading · BUY/SELL/ALLOW buttons · 5/15/30 return columns · separate provenance table.

---

## 3. Current UI order vs logical

**Current:**
1. Title + EXPERIMENT blurb  
2. Pipeline env ON/OFF tags (N2–N6)  
3. Latency / capacity / coverage tags  
4. Experiment + milestone + MATCHED/NO_NEWS/decision tags (한 줄에 혼합)  
5. Warning (no Apply)  
6. Actions  
7. Latest NEWS_MATCHED examples  
8. Recent Experiment Rows  
9. Experiment stats JSON  

**Logical:** status → sample/coverage → MATCHED/NO_NEWS → combined → evaluation → milestone  

**판정:** 큰 역전 없음. 태그 밀도만 높음. **강제 reorder 불필요.**

---

## 4. Mutations

| UI | Endpoint | Class | DB experiment | Scanner | Control Shadow | Cohort | Gate | TradingOrder/Outbox |
|----|----------|-------|---------------|---------|----------------|--------|------|---------------------|
| Experiment Run | POST `/admin/upbit/combined-shadow/run` `{limit_runs:5, force:false}` | **EXPERIMENT_MUTATION** | create/update experiment rows | **NO** (reads CONTROL ranks) | **NO** | **NO** | **NO** | **NO** |
| Evaluate Pending | POST `.../evaluate` `{limit:50}` | **EXPERIMENT_MUTATION** | evaluate experiment rows | **NO** | **NO** (msg: CONTROL Shadow 미변경) | **NO** | **NO** | **NO** |
| 새로고침 | GET refetch×3 | — | — | — | — | — | — | — |

**TRADING_MUTATION / CONTROL_MUTATION:** **0**

---

## 5. N6–N10 contracts (FE)

| Contract | Evidence |
|----------|----------|
| CONTROL Scanner/Shadow/Cohort 불변 | panel copy + mutation success messages |
| experimental score ≠ scanner_score | copy + separate columns |
| BOOST/… ≠ BUY/SELL/ALLOW | copy; no trade action buttons |
| Apply/Enable Trading 없음 | explicit paragraph |
| look-ahead 완화 금지 | copy |
| Pipeline observation READ | latency/coverage tags from status |

---

## 6. Sample status (READ-ONLY DB)

`operation.upbit_news_combined_shadow` (조회 시각: 본 STEP):

| Bucket | Count |
|--------|------:|
| NEWS_MATCHED + COMPLETED | **2** |
| NO_NEWS + COMPLETED | **22** |
| NO_NEWS + ACTIVE | **7** |
| EXCLUDED_ONLY + COMPLETED | **4** |

Targets: MATCHED≥20 · NO_NEWS≥20 · mismatch=0 (A/B panel에 Technical `mismatch_count` UI **없음**).

**Milestone:** MATCHED 미달 → **`NEWS_AB_SAMPLE_ACCUMULATING`** 유지.  
정책/threshold 변경 **없음**.

Technical VALID≈50과 **혼합 금지** (별도 milestone).

---

## 7. Options

| Option | Eval |
|--------|------|
| **A KEEP_AS_IS ★** | 탭 독립 · EXPERIMENT isolation 명확 · LOC 적정 · sample 누적 중 UI churn 불필요 |
| B SECTION_REORGANIZE | 태그 그룹 heading만 가능하나 **필수 아님** |
| C COMPONENT_SPLIT | LOC 271 · query 3 · 과잉 |
| D DETAIL_ROUTE | 근거 없음 · **금지** |

**권장: A**  
split **NO** · reorder **NO** (필수) · backend/API/route/permission **NO**

---

## 8. Regressions / safety

| Check | Result |
|-------|--------|
| Tabs 5 | unchanged |
| Technical/News/A-B/Ops mounts | 1 each |
| LIVE panel accounts only | YES |
| Risk LIVE mut | 0 |
| TradingOrder/Outbox/create_order | 0 this STEP |
| production mutation | **0** |
| WIP (rowKey etc.) | **untouched** |

---

## 9. Next STEP (exactly one)

**STEP M5-E0 — Ops/Reconciliation tab structure PRECHECK**  
(또는 사용자 지정 시 A/B sample 자연 누적 관찰만 — **M5-D 구현 스킵**)

승인 전 M5-D 구현 금지.

---

## 10. Limitations

1. Evaluation horizon UI는 r60 중심 (5/15/30 컬럼 없음).  
2. n8_preflight_snapshot.json은 구식(2026-08-13) — 본 보고는 DB live SELECT 기준.  
3. Run/Evaluate가 BE에서 CONTROL을 건드리지 않음은 FE 계약+메시지 기준; BE code path는 기존 N6 계약에 의존.
