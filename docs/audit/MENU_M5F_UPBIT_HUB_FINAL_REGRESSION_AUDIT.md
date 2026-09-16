# MENU M5-F — Upbit Hub Final Regression Audit

**Mode:** READ-ONLY AUDIT · **production mutation = 0**  
**Date:** 2026-08-15  
**Branch:** `release/v1.1.0` @ `21632e6`  
**Verdict:** `UPBIT_HUB_CONSOLIDATION_COMPLETE_WITH_LIMITATIONS`  
**M5_CLOSE:** **YES**

> 본 STEP은 production/API/backend/route/permission 수정 **금지**.  
> LIVE/ARM/Scheduler · News/Technical 정책 · Ops action **실행 금지**.  
> commit/push **없음** (별도 selective commit).

---

## 0. Git baseline

| STEP | Commit | Note |
|------|--------|------|
| M5-A | `285b521` | Hub 5-tab shell |
| M5-B | `c1af96e` | Technical section reorder |
| M5-C | `ffaa247` | News N2→N5 reorder (rowKey WIP excluded) |
| M5-D | — | **SKIP / KEEP_AS_IS** (docs only) |
| M5-E | `21632e6` | Ops Status→…→Ambiguous |
| HEAD | `21632e6` | origin ahead **3** (B/C/E local) |

M5 commit path types: **frontend 11 · docs 19 · backend 0**.  
`adminApi` / `config/routes` / AuthGuard — M5 range **미변경**.

---

## 1. Final 5-tab structure

| # | Tab label | Key | Mount |
|---|-----------|-----|-------|
| 1 | 개요 | `overview` | `UpbitLiveStatusReadSummary` (+ section guide buttons) |
| 2 | Technical | `technical` | `UpbitOpportunityScannerPanel` |
| 3 | 뉴스 파이프라인 | `news` | `UpbitNewsNoticeCollectorPanel` |
| 4 | A/B 실험 | `ab` | `UpbitNewsCombinedShadowPanel` |
| 5 | 운영·정합 | `ops` | `UpbitHubOpsSection` → `UpbitAmbiguousOrdersPanel` ×1 |

`UpbitHubTabs`: 미방문 pane `null` · 방문 후 `display:none` keep-alive · tab switch **mutation 없음**.  
URL `?tab=` **미지원** (limitation).

### Duplicate mount (production `.tsx`, tests 제외)

| Component | Mount count | Location |
|-----------|------------:|----------|
| `UpbitLiveStatusReadSummary` | 1 | upbit/page |
| `UpbitOpportunityScannerPanel` | 1 | upbit/page |
| `UpbitNewsNoticeCollectorPanel` | 1 | upbit/page |
| `UpbitNewsCombinedShadowPanel` | 1 | upbit/page |
| `UpbitHubOpsSection` | 1 | upbit/page |
| `UpbitAmbiguousOrdersPanel` | 1 | OpsSection only |
| `AdminUpbitLiveUbaPanel` | 1 | **accounts/page only** |

**duplicate mount count = 0**

---

## 2. Per-STEP regression

### M5-A — PASS

- 5 tabs · route `/admin/upbit` 단일 · News→A/B 순서 · keep-alive · LIVE control 없음

### M5-B Technical — PASS

Flow: Scanner → 후보/AI → Paper Shadow → Shadow 평가 → Cohort  
Contract: mutation **2** · onClick **3** · API **3** (`get/run/evaluate` scanner) · state/effect **0/0** · **no split**  
Scanner Score/Rank/TopN · cohort 정책: M5 range **미변경** (본 STEP도 변경 0)

### M5-C News — PASS (HEAD) / WT residual noted

Flow: N2 → N3/N3.1 → N4 → N5  
Contract (HEAD & WT): handlers **5** · GET **7** · mutation **4** · state/effect **0/0** · N6 **없음** (A/B tab)  
**HEAD:** `dataSource={items.map(... key: article_id ?? idx)}`  
**WT residual WIP:** `dataSource={items}` + `rowKey={(row)=>String(row.article_id??"")}` 등 — **M5-F 미수정**

### M5-D A/B — PASS (KEEP_AS_IS)

- Panel untouched by M5-D/E implementation  
- mutation **2**: `runUpbitCombinedShadow` · `evaluateUpbitCombinedShadow` only  
- BUY/SELL/ALLOW는 경고 문구만 (action 없음) · Scanner/Gate/Trading production mutation **0**

**A/B sample (READ):** connected DB `stock_platform` **public tables = 0** → 본 세션 live recount 불가.  
Last known (M5-D0): MATCHED completed **2**/20 · NO_NEWS completed **22**/20 · EXCLUDED completed **4** · milestone **`NEWS_AB_SAMPLE_ACCUMULATING`**. mismatch UI N/A.  
정책 변경 **0**.

### M5-E Ops — PASS

Flow: Status → Sync → Rate → Snapshot → Reconcile → Ambiguous  
Ops: mutation **4** · GET **3** · state/effect **1/0** · Ambiguous mount **1** · panel file **미수정 in M5-E**  
본 STEP: connection/sync/reconcile/rate/snapshot **실행 0**

---

## 3. LIVE / Risk canonical

| Contract | Result |
|----------|--------|
| `AdminUpbitLiveUbaPanel` mount | **1** (`/admin/accounts`) |
| `/admin/upbit` LIVE/ARM/DISARM/Scheduler RUN·PAUSE refs | **0** |
| `/admin/risk` LIVE/ARM/Scheduler mutation | **0** (Kill · settings · paused · limits · READ · accounts link 유지) |
| Risk residual WIP | present · **M5-F 미수정** |

---

## 4. Canonical ownership matrix

| Domain | Owner |
|--------|-------|
| LIVE/ARM/Scheduler **CONTROL** | `/admin/accounts` |
| Upbit Scanner/Shadow/News/A-B/Ops | `/admin/upbit` |
| Runtime | `/admin/trading` |
| Orders/Outbox | `/admin/orders` |
| Risk/Kill | `/admin/risk` |
| Recovery | `/admin/recovery` |
| System health | `/admin/monitoring` |
| Trading operations READ | `/admin/operations-dashboard` |
| Preflight | `/admin/operations/preflight` |

**중복 CONTROL:** Upbit/Risk에 LIVE/ARM/Scheduler CONTROL **없음** (PASS).

---

## 5. Route / Permission / API / Backend

| Delta (M5-A…E) | Count |
|----------------|------:|
| route add/delete/rename | **0** |
| AuthGuard / permission | **0** |
| backend endpoint | **0** |
| `adminApi` contract | **0** |

---

## 6. Trading / runtime safety (M5-F session)

| Check | Result |
|-------|--------|
| TradingOrder / Outbox / create_order / POST /v1/orders | **0** (본 STEP 미실행) |
| LIVE/ARM/Scheduler state change | **0** |
| server restart / env mutation | **0** |
| Scanner / Technical Shadow / News A/B / AI Gate policy mutation | **0** |
| Ops reconcile/sync/rate/snapshot/connection run | **0** |

---

## 7. Tests / lint / typecheck

| Suite | Result | Classification |
|-------|--------|----------------|
| `upbitHubTabs` | PASS | HEAD regression OK |
| `upbitLiveControlSingleMount` | PASS | M4-C OK |
| `upbitTechnicalSectionOrder` | PASS | HEAD OK |
| `upbitNewsPipelineSectionOrder` | **1 FAIL** (rowKey assert) | **WT WIP only** — HEAD would match committed key map |
| `upbitOpsReconciliationSectionOrder` | PASS | HEAD OK |
| `riskLiveControlSingleSurface` | PASS | M4-C2 OK |
| eslint (M5 shell/tests) | PASS | |
| tsc M5 paths | NewsCollector WT: `analysis_id`/`signal_id` errors | **pre-existing WIP** · M5 committed files 신규 오류 0 |

Focused: **27 PASS / 1 FAIL (WT WIP)** · Files: 5 PASS / 1 FAIL.

---

## 8. Remaining limitations (only residuals)

1. NewsCollector **rowKey WIP** (WT ≠ HEAD) — focused test + tsc noise  
2. AmbiguousOrdersPanel **한글/encoding WIP**  
3. Risk page residual presentation WIP  
4. RuntimePreflightPanel WIP  
5. Technical / News A/B **표본 자연 누적** (MATCHED&lt;20)  
6. Hub URL `?tab=` deep-link **미지원**  
7. Connected audit DB public schema empty → live A/B recount 불가 (M5-D0 snapshot 참조)

완료된 M5 탭 구조·ownership은 limitation으로 재기재하지 않음.

---

## 9. M5_CLOSE

**YES** — Upbit Hub IA consolidation (M5-A…E)는 구조적으로 완료.  
이후 Hub 구조 변경은 **별도 요구 없는 한 종료**.  
잔여 WIP는 Hub 밖/별도 선별 트랙.

---

## 10. Documents / git

Created:

- `docs/audit/MENU_M5F_UPBIT_HUB_FINAL_REGRESSION_AUDIT.md`
- `docs/audit/MENU_M5F_UPBIT_HUB_FINAL_REGRESSION_AUDIT.json`

Canonical 갱신: CURRENT_WORK · STEP_MASTER · ROADMAP · IMPLEMENTATION_STATUS · audit/README  

**commit: 없음 · push: 없음 · production mutation: 0**

---

## 11. Next STEP (exactly one)

**M6-0 — ADMIN/USER SHARED COMPONENT CONSOLIDATION PRECHECK** (READ-ONLY)

M6 구현 시작 금지.
