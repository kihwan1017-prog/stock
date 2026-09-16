# MENU M5-0 — Upbit Hub Consolidation Precheck

**Mode:** PRECHECK / DESIGN ONLY · **Verdict:** `UPBIT_HUB_DESIGN_READY_WITH_LIMITATIONS`  
**Date:** 2026-08-15  
**Baseline:** M4-C2-APPLY committed · LIVE canonical `/admin/accounts`  
**Scope route:** `/admin/upbit` → `frontend/src/app/(admin)/admin/upbit/page.tsx`

> Production page/component/API **변경 없음**.  
> LIVE/ARM/Scheduler/Scanner/News/TradingOrder/Outbox **실행·정책 변경 없음**.  
> M5-A 구현 자동 진행 금지. commit/push 없음.

---

## 0. Executive summary

`/admin/upbit`는 **UPBIT 연구·운영 허브**다. LIVE/ARM/Scheduler **CONTROL은 이미 `/admin/accounts`로 canonical**이고, Hub에는 READ summary + accounts 링크만 있다.

실제 mount된 **feature panel은 5개**뿐이며, Technical Shadow/Cohort·News N2–N5는 **별도 route가 아니라** Scanner / News Collector 패널 **내부에 합쳐져** 있다. 페이지는 탭 없이 **세로 스택**이며, **N6 Combined Shadow가 N2–N5 Collector보다 위에** 마운트되어 pipeline 순서가 UI상 역전되어 있다.

**권장:** OPTION B — `/admin/upbit` 유지 + 내부 Tabs (backend mutation 0, route 0).

---

## 1. Mount inventory (`page.tsx`)

| # | Component | Lines | Category | Control class |
|---|-----------|------:|----------|---------------|
| 1 | `UpbitLiveStatusReadSummary` | 194 | ACCOUNT_STATUS | READ_ONLY |
| 2 | `UpbitOpportunityScannerPanel` | 219 | TECHNICAL_SCANNER + TECHNICAL_SHADOW + TECHNICAL_COHORT | LOW_RISK_MUTATION |
| 3 | `UpbitNewsCombinedShadowPanel` | 271 | NEWS_AB_EXPERIMENT | LOW_RISK_MUTATION |
| 4 | `UpbitNewsNoticeCollectorPanel` | 390 | NEWS_COLLECTION + NEWS_MAPPING + NEWS_AI + NEWS_SIGNAL | LOW_RISK_MUTATION / OPERATIONAL_CONTROL |
| 5 | Page-inline: account status / rate limit / snapshot | (page 296) | ACCOUNT_STATUS + SYSTEM_STATUS | READ + LOW_RISK / OPERATIONAL |
| 6 | `UpbitAmbiguousOrdersPanel` | 491 | ORDER_RECONCILIATION | OPERATIONAL_CONTROL |

**Feature panel mount count = 5** (+ page shell operational blocks).  
**별도 mount 없음:** Technical Shadow only, Cohort only, Symbol Mapping only, AI News only, News Signal only — 모두 위 패널 내부.

관련 sibling route (본 Hub 밖): `/admin/upbit/markets` — 시세/instrument sync (`DIFFERENT_SCOPE`).

---

## 2. Panel detail (code-backed)

### 2.1 `UpbitLiveStatusReadSummary`

| 항목 | 내용 |
|------|------|
| Purpose | M4-C LIVE/ARM/Scheduler **조회 전용** + accounts/recovery 링크 |
| READ | UBA list(UPBIT), LIVE/ARM/Paused/Credential tags, live-ops readiness, trading scheduler status |
| CONTROL | **0** (`useMutation` 없음) |
| API | `listAdminBrokerAccounts`, `getAdminLiveOpsReadiness`, `getTradingSchedulerStatus` |
| Scheduler / Trading / Shadow / News | status READ only / no / no / no |
| Duplicate | `STATUS_VS_CONTROL` vs `/admin/accounts` `AdminUpbitLiveUbaPanel` |

### 2.2 `UpbitOpportunityScannerPanel`

| 항목 | 내용 |
|------|------|
| Purpose | SHADOW_ONLY Opportunity Scanner + Paper Shadow + Cohort stats |
| READ | Scanner status, evaluator scheduler JSON, Top candidates, active/completed shadows, cohort JSON |
| CONTROL | Dry Run 1회 · Shadow 평가 |
| API GET | `getUpbitOpportunityScannerStatus` (30s refetch; shadows/cohort embedded) |
| API MUT | `runUpbitOpportunityScanner({ notify:true, force_ai:false })`, `evaluateUpbitOpportunityShadows` |
| TradingOrder | **NO** (UI: LIVE ORDER: NO) |
| Technical Scanner / Shadow / Cohort | **YES / YES / YES** (단일 패널) |
| Milestone / Review UI | **없음** (cohort 카운터/JSON만) |
| Market AI | 후보 recommendation 필드·dry-run `force_ai:false`만 — **별도 Market AI 패널 없음** |

### 2.3 `UpbitNewsCombinedShadowPanel`

| 항목 | 내용 |
|------|------|
| Purpose | N6 Combined Technical+News Shadow **experiment only** |
| READ | Pipeline env tags, experiment aggregates, NEWS_MATCHED examples, recent rows, stats |
| CONTROL | Experiment Run · Evaluate Pending |
| API | `getUpbitCombinedShadowStatus/Recent/Stats`, `runUpbitCombinedShadow`, `evaluateUpbitCombinedShadow` |
| Technical CONTROL Shadow | 관측만 (정책/스케줄 변경 UI 없음) |
| Trading | **NO** |

### 2.4 `UpbitNewsNoticeCollectorPanel` (N2–N5 결합)

| 항목 | 내용 |
|------|------|
| Purpose | Collector → Mapping → AI Analysis → News Signal **한 파일·한 세로 스택** |
| READ | recent notices(+mapped), AI recent, signals recent, status/stats JSON |
| CONTROL | 수동 수집 · Symbol Mapping · AI News Analysis · News Signal 표준화 |
| API MUT | `runUpbitNewsCollector`, `runUpbitNewsSymbolMapping`, `runUpbitNewsAnalysis`, `runUpbitNewsSignals` |
| Signal 성격 | INFORMATIONAL ONLY (BUY/SELL/Scanner Apply 없음) |
| 결합 문제 | **N2–N5 단일 component** — 탭 분리 시 섹션 추출 또는 하위 panel split 필요 |

### 2.5 Page shell (inline)

| Mutation | API | Class | Trading? |
|----------|-----|-------|----------|
| 연결 테스트 | `testUpbitAccountConnection` | LOW_RISK_MUTATION | No |
| 잔고 동기화 | `syncUpbitAccount` | OPERATIONAL_CONTROL | No (snapshot) |
| 체결 동기화 | `reconcileUpbitOrders` | OPERATIONAL_CONTROL | No create; fill sync |
| Rate Recheck | `recheckUpbitRateLimits` | LOW_RISK_MUTATION | No |

READ: `getUpbitAccountStatus`, `getUpbitAccountSnapshot`, `getUpbitRateLimits`.

### 2.6 `UpbitAmbiguousOrdersPanel`

| 항목 | 내용 |
|------|------|
| Purpose | Ambiguous order health + remote-lookup resolver + resubmit **prep** |
| READ | list, health, resolver status, resolver runs |
| CONTROL (7) | run resolver now, retry lookup, release claim, lookup, manual review, approve resubmit prep, reject |
| TradingOrder 생성/실전송 | **NO** (승인 = prep only, UI 명시) |
| Class | OPERATIONAL_CONTROL (TRADING_CONTROL 아님) |

---

## 3. Classification counts

| Category | Surfaces |
|----------|----------|
| ACCOUNT_STATUS | LiveSummary + page status/snapshot |
| TECHNICAL_SCANNER | OpportunityScanner (part) |
| TECHNICAL_SHADOW | OpportunityScanner (part) |
| TECHNICAL_COHORT | OpportunityScanner cohort JSON |
| NEWS_COLLECTION | NoticeCollector |
| NEWS_MAPPING | NoticeCollector |
| NEWS_AI | NoticeCollector |
| NEWS_SIGNAL | NoticeCollector |
| NEWS_AB_EXPERIMENT | CombinedShadow |
| ORDER_RECONCILIATION | Ambiguous + page reconcile |
| SYSTEM_STATUS | Rate limits |
| OTHER | (none invented) |

**READ-only feature surfaces:** LiveSummary (+ embedded GETs in all panels).  
**Mutation/control handlers (Hub):** page 4 + scanner 2 + combined 2 + collector 4 + ambiguous 7 = **19**.  
**TRADING_CONTROL (LIVE/ARM/order place):** **0**.

---

## 4. Duplicate vs other Admin pages

| Hub surface | Other page | Class |
|-------------|------------|-------|
| LIVE/ARM/Scheduler CONTROL | `/admin/accounts` canonical | **STATUS_VS_CONTROL** (Hub=status) |
| LIVE status tags | `/admin/risk` (M4-C2 status+link) | **CROSS_DOMAIN_REFERENCE** / STATUS shared theme |
| Recovery link | `/admin/recovery` | **CROSS_LINK** |
| Generic KRX news sync | `/admin/news` | **DIFFERENT_SCOPE** |
| Orders list | `/admin/orders` | **DIFFERENT_SCOPE** (Ambiguous 없음) |
| Runtime hub | `/admin/trading` | **DIFFERENT_SCOPE** |
| Ops dashboard | `/admin/operations-dashboard` | **CROSS_DOMAIN_REFERENCE** (가능) |
| Monitoring | `/admin/monitoring` | **DIFFERENT_SCOPE** |
| Account snapshot/sync | accounts panel refresh | **SUMMARY_VS_DETAIL** / overlap ops |
| Scanner/News/Ambiguous | other admin pages | **DIFFERENT_SCOPE** (Hub exclusive mounts) |

**TRUE_DUPLICATE (LIVE panel):** **0** (M4-C: mount count = 1 on accounts).  
**TRUE_DUPLICATE (Hub panels):** **0**.

### Canonical ownership (SoT)

| Domain | Canonical |
|--------|-----------|
| LIVE/ARM/Scheduler CONTROL | `/admin/accounts` |
| LIVE READ summary (UPBIT) | `/admin/upbit` |
| Kill / risk settings | `/admin/risk` |
| Recovery HIGH mutation | `/admin/recovery` |
| UPBIT Scanner/Shadow/News N2–N6/Ambiguous UI | `/admin/upbit` (현재) |
| Generic news | `/admin/news` |
| Runtime CONTROL | `/admin/trading` |

---

## 5. M4-C / M4-C2 regression (verify only)

| Check | Result |
|-------|--------|
| `AdminUpbitLiveUbaPanel` JSX mount count | **1** → `accounts/page.tsx` |
| `/admin/upbit` panel mount | **absent**; `UpbitLiveStatusReadSummary` present |
| `/admin/upbit` LIVE/ARM/Scheduler mutation strings | **0** |
| `/admin/risk` LIVE/ARM/Scheduler mutation strings | **0** (working tree 기준) |
| Evidence test | `upbitLiveControlSingleMount.test.ts` |

**M4-C regression: PASS.**  
**Risk M4-C2 regression: PASS** (LIVE mut surface).

---

## 6. News Pipeline (UI 실구조)

```text
Collector / Mapping / AI / Signal   ← 전부 UpbitNewsNoticeCollectorPanel (1 component)
        ↓
Combined Shadow A/B                 ← UpbitNewsCombinedShadowPanel
```

| Stage | Component | Mount order on page |
|-------|-----------|---------------------|
| N2 Collector | NoticeCollector | **4번째** (Combined **뒤**) |
| N3 Mapping | NoticeCollector | 동일 |
| N4 AI | NoticeCollector | 동일 |
| N5 Signal | NoticeCollector | 동일 |
| N6/N7 Combined A/B | CombinedShadowPanel | **3번째** (Collector **앞**) |

**과도 결합:** N2–N5 = 1 panel.  
**순서 문제:** pipeline UI가 N6 → N2…N5 순으로 보임 → M5에서 MOVE_SECTION 권장.

`/admin/news`는 Upbit N2–N6과 **다른 도메인**(symbol news sync).

---

## 7. Technical Pipeline (UI 실구조)

```text
Scanner + Shadow + Cohort (+ candidate AI fields)
  └─ 전부 UpbitOpportunityScannerPanel
```

| Expected stage (목표 tree) | 실제 UI |
|----------------------------|---------|
| Scanner | OpportunityScannerPanel |
| Market AI | **별도 패널 없음** (후보 recommendation / force_ai flag만) |
| Technical Shadow | 동일 패널 Paper Shadow tables |
| Cohort | 동일 패널 “Shadow Stats / Cohort” JSON |
| Milestone / Review | **전용 UI 없음** (문서/리뷰는 audit docs 쪽) |

**News vs Technical 논리 분리 필요?** **YES** — 도메인·스케줄·정책이 다르고, 현재는 한 페이지에 섞여 discoverability↓.  
단 **지금 당장 신규 route 불필요** — 탭/섹션으로 충분.

---

## 8. OPTION 비교

| 기준 | A Section only | B Tabs on same route | C Overview + detail routes |
|------|----------------|----------------------|----------------------------|
| discoverability | 중 (스크롤) | **고** | 고 (단 nav 분산) |
| operator workflow | 약 | **강** (탭별 작업) | 강 (이동 비용↑) |
| control safety | 중 | **중~고** (탭으로 TRADING 격리 유지) | 고 (권한 세분화 가능) |
| component complexity | 낮음~중 | 중 (shell + 추출) | 고 |
| route 증가 | 0 | **0** | 다수 |
| permission 영향 | 0 | 0 (동일 `menu:upbit`) | 탭별 permission 유혹↑ |
| regression risk | 저 | **저~중** | 고 |
| 확장성 | 약 | **중~고** | 고 |

**권장: OPTION B**  
- M4-C LIVE 분리 유지  
- backend/API 변경 0  
- N2–N5 / Technical / A/B / Reconciliation 논리 분리  
- route·permission 동결  

OPTION A는 단기 가능하나 현재 길이(세로 스택) 문제를 거의 못 줄임.  
OPTION C는 M5 후기(필요 시) — 지금은 regression·permission 비용 과다.

---

## 9. Target tree 적합성 (제안 tree vs 코드)

제안:

```text
UPBIT
 ├─ 개요 (LIVE READ · Scanner 요약 · Cohort 요약 · News A/B 요약)
 ├─ Technical (Scanner · Shadow · Cohort)
 ├─ News Pipeline (Collector · Mapping · AI · Signal)
 ├─ A/B Experiment (Combined Shadow)
 └─ Reconciliation (Ambiguous + page reconcile/sync)
```

| 판정 | 이유 |
|------|------|
| **적합 (채택 방향)** | 실제 mount가 이 축과 일치; LIVE CONTROL은 Overview→accounts CROSS_LINK |
| 수정 필요 | Market AI / Milestone 전용 UI **없음** → tree에서 제거하거나 DETAIL_ONLY(문서 링크) |
| 수정 필요 | Account rate-limit/snapshot은 Overview 또는 Reconciliation 인접 SYSTEM 블록으로 |
| 채택 금지 | 기능을 없애는 REMOVE |

**권장 target tree (코드 정합):**

```text
/admin/upbit  (Tabs — OPTION B)
 ├─ Overview
 │   ├─ UpbitLiveStatusReadSummary
 │   ├─ Scanner/Cohort/News A/B 요약 카드 (READ; 후속 wave)
 │   └─ accounts / recovery CROSS_LINK
 ├─ Technical
 │   └─ UpbitOpportunityScannerPanel (내부 섹션 유지; 추후 추출 가능)
 ├─ News Pipeline
 │   └─ UpbitNewsNoticeCollectorPanel (후속: N2–N5 하위 탭/섹션)
 ├─ A/B Experiment
 │   └─ UpbitNewsCombinedShadowPanel
 └─ Ops / Reconciliation
     ├─ page shell: connection / sync / reconcile / rate / snapshot
     └─ UpbitAmbiguousOrdersPanel
```

---

## 10. Disposition (기능 삭제 강제 없음)

| Surface | Verdict |
|---------|---------|
| LiveStatusReadSummary | **KEEP** + **CROSS_LINK** (accounts) |
| OpportunityScanner (+Shadow/Cohort) | **KEEP** · **MOVE_SECTION** (Technical tab) |
| NewsNoticeCollector (N2–N5) | **KEEP** · **MOVE_SECTION** · 내부 **MERGE_UI 유지**(단기) / 중기 추출 |
| NewsCombinedShadow | **KEEP** · **MOVE_SECTION** (A/B tab; Collector **앞→뒤** 순서 교정) |
| Ambiguous | **KEEP** · **MOVE_SECTION** (Reconciliation) |
| Page sync/reconcile/rate/snapshot | **KEEP** · **MOVE_SECTION** (Ops tab) |
| `/admin/news` 교차 | **CROSS_LINK** only |
| Milestone Review UI | **DETAIL_ONLY** (audit docs; Hub에 기능 없음 → 신규 발명 금지) |
| DEPRECATE_CANDIDATE | **없음** |
| REMOVE_CANDIDATE | **없음** |

---

## 11. Component size / coupling

| Rank | Lines | File |
|-----:|------:|------|
| 1 | 491 | `UpbitAmbiguousOrdersPanel.tsx` |
| 2 | 390 | `UpbitNewsNoticeCollectorPanel.tsx` |
| 3 | 296 | `upbit/page.tsx` |
| 4 | 271 | `UpbitNewsCombinedShadowPanel.tsx` |
| 5 | 219 | `UpbitOpportunityScannerPanel.tsx` |

**결합 문제**

1. NoticeCollector = N2–N5 + 4 mutations 한 파일  
2. OpportunityScanner = Scanner+Shadow+Cohort+evaluator status  
3. page.tsx = Hub host + broker ops mutations + tables  
4. Combined가 Collector보다 위 → 인지 결합 왜곡  

탭 분리만으로도 1차 개선 가능; **대규모 refactor는 M5-B+에서 제안만**.

---

## 12. API / Permission / Route

| 항목 | 판정 |
|------|------|
| Backend/API 변경 | **불필요** (기존 adminApi 재배치만) |
| Permission | `menu:upbit` + Admin `AuthGuard requiredRoles=["admin"]` + `enforceMenuPermission` — **탭별 새 permission 불필요** (검토만) |
| Route 변경 | M5-A~E **불필요** (OPTION B). markets sibling 유지 |

---

## 13. M5 implementation waves (설계만)

| Wave | Scope | Out of scope |
|------|-------|--------------|
| **M5-A** | Tab shell + Overview(기존 LiveSummary mount 이동) · 패널 순서만 재배치 · **mutation 동작 변경 0** | policy/API/LIVE |
| **M5-B** | Technical tab ← OpportunityScannerPanel | Shadow policy |
| **M5-C** | News Pipeline tab ← NoticeCollector; 선택적 내부 섹션 heading | N2–N10 정책 |
| **M5-D** | A/B tab ← CombinedShadow | score/threshold |
| **M5-E** | Ops/Reconciliation ← Ambiguous + page broker ops | TradingOrder send |

한 STEP에서 page 전면 재작성 **금지**. 각 wave 후 regression: M4-C mount test + LIVE mut = 0.

---

## 14. Safety note

본 STEP: production mutation **0**, LIVE/ARM/Scheduler/Scanner 설정/News 정책/TradingOrder/Outbox **미실행**.  
Technical cohort · News A/B 자연 누적 **방해 없음**.

---

## 15. Limitations

1. Milestone/Market AI 전용 UI는 코드에 없어 목표 tree를 그대로 복사하면 과설계.  
2. Working-tree 잔여(risk title WIP, NewsCollector tsc 등)는 M5와 무관 — 본 조사는 mount/API 기준.  
3. Backend scheduler job 내부 동작은 UI surface 기준으로만 분류.  
4. `/admin/upbit/markets`는 Hub precheck 범위 외 sibling.

---

## 16. Next STEP (exactly one)

**STEP M5-A — Upbit Hub Tab shell + Overview reorder (UI only, API mutation behavior unchanged)**

승인 전 구현 금지.
