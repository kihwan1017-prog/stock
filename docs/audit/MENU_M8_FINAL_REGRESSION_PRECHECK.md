# MENU M8-0 — Final Admin/User Menu, Route, Permission Regression Precheck

**Mode:** READ-ONLY FINAL AUDIT · **production mutation = 0**  
**Date:** 2026-08-15  
**HEAD:** `f18d02f` · branch `release/v1.1.0` · origin **ahead 10**  
**M7_CLOSE:** YES (`LEGACY_REDIRECT_CLEANUP_COMPLETE_WITH_LIMITATIONS`)  
**Verdict:** `FINAL_IA_REGRESSION_AUDIT_READY_WITH_LIMITATIONS`

> menu/route/page/redirect/permission/AuthGuard/API/backend **수정 금지**.  
> residual WIP **수정 금지**. commit/push **금지**.

---

## 0. Git baseline

| Item | Value |
|------|-------|
| branch | `release/v1.1.0` |
| HEAD | `f18d02f` (M7 CLOSE docs) |
| origin | ahead **10** |
| residual WIP | **~93** dirty/untracked paths (separated from baseline) |

---

## 1. Final IA baseline (CURRENT_APPROVED_IA)

M2 early target (Admin 9 / User 8) is **not** the PASS bar.  
M4-B kept separate Admin ops domains → **CURRENT_APPROVED_IA**:

| Scope | Top-level | Leaf | Status vs M3–M7 approved |
|-------|----------:|-----:|--------------------------|
| Admin | **11** | **55** | CURRENT_APPROVED_IA |
| User | **12** | **29** | CURRENT_APPROVED_IA |

### Admin top-level (HEAD)

1. 운영 대시보드  
2. 회원·권한  
3. 계좌  
4. 시장 데이터  
5. 전략·후보  
6. 자동매매 운영  
7. 거래  
8. 리스크·안전  
9. 알림  
10. 시스템 운영  
11. 내 정보  

### User top-level (HEAD)

1. 대시보드 · 2. 내 계좌 · 3. 시장 정보 · 4. 매매 후보 · 5. 내 전략 ·  
6. 업비트 LIVE 검증 · 7. 내 주문·체결 · 8. 내 잔고·손익 · 9. 내 리스크 ·  
10. 내 리포트 · 11. 알림 · 12. 내 정보  

---

## 2–3. Menu integrity

| Check | Result |
|-------|--------|
| broken menu href | **0** (`menu.test.ts`) |
| duplicate menu href | **0** |
| duplicate menu key (flat leaves) | **0** (Admin/User namespaces separate; shared key names ok across portals) |
| `/admin/monitoring` sidebar | **1** |
| LLM 분석 | → **`/user/ai`** (not `/user/candidates/llm`) |

---

## 4. Route / page inventory

| Scope | `page.tsx` |
|-------|-----------:|
| Admin | **60** |
| User | **36** |
| Total | **96** |

| Classification | Count | Notes |
|----------------|------:|-------|
| KEEP_CANONICAL | **84** | content pages; menu leaf coverage matches |
| KEEP_REDIRECT | **3** | `/admin`, `/user`, `/user/candidates/llm` |
| DEPRECATE_REDIRECT | **9** | M7-B matrix |
| DETAIL_ONLY | **0** | `/user/ai` now menu-canonical |
| HIDDEN_ACTIVE | **0** | |
| ORPHAN | **0** | |
| BROKEN | **0** | |
| REMOVE_CANDIDATE | **0** | |
| unclassified active page | **0** | 84 content = 55+29 menu leaves |

---

## 5–6. Coverage

menu → page: **PASS**  
page → menu: every non-redirect page is a menu leaf (Admin/User).

---

## 7–12. Track regressions

| Track | Result |
|-------|--------|
| **M3-A** monitoring duplicate gone | PASS |
| **M3-B** strategy-requests/drafts + admin portfolio-validations | menu + page PASS |
| **M4** autotrading-ops / system / risk-ops / trading-group | PASS |
| **LIVE control** `AdminUpbitLiveUbaPanel` mount | **1** (`/admin/accounts` only) |
| `/admin/upbit` LIVE mutation | **0** |
| `/admin/risk` LIVE/ARM mutation | **0** (Kill retained) |
| **M5** Hub 5 tabs | 개요 / Technical / 뉴스 파이프라인 / A/B 실험 / 운영·정합 |
| Upbit duplicate panel mounts | **0** (focused tests PASS) |
| **M6** shared utils | **7** (`asRecord`,`extractRows`,`cell`, status colors×2, rate helpers×2) |
| shared order keys | **7** |
| shared SR keys | **4** |
| hooks/mega/capability props | **0** |
| user→admin `dataHelpers` | **0** |
| admin shim | retained (`features/admin/utils/dataHelpers` re-export) |
| M6-D/E SKIP | maintained |
| **M7** redirects | 12 / KEEP3 / DEP9 / chain0 / REMOVE0 |
| `/user/ai` + llm redirect | PASS |
| external | UNKNOWN · REMOVE gate FAIL |

---

## 13. Permission matrix (summary)

| Class | Count / notes |
|-------|----------------|
| Admin leaves with `menu:*` | majority MATCH with AuthGuard admin + enforceMenuPermission |
| **INTENTIONAL_NO_MENU_PERMISSION** | **6**: `indicators`, `strategy-requests`, `strategy-drafts`, `portfolio-validations`, `recovery`, `profile` — admin role gate only |
| User leaves | `minAccess: user` · no `menu:*` keys — INTENTIONAL portal pattern |
| MISMATCH | **0** |
| REVIEW_REQUIRED (new) | **0** |

M2 candidate keys `menu:indicators|recovery|profile|strategy_*|portfolio_validations` — **still absent**; deferred to optional future hardening (not M8-0 work).

---

## 14. AuthGuard

| Surface | Gate |
|---------|------|
| Admin layout | `requiredRoles=["admin"]` + menu permission enforce |
| User layout | role filter + pathname roles; admin redirected to admin dashboard |
| Strategy / AI / accounts / upbit / risk / recovery | under layouts; **no bypass found** |
| AuthGuard mutation (M8) | **0** |

---

## 15. Cross-domain imports

| Direction | Finding |
|-----------|---------|
| user → admin `dataHelpers` | **0** |
| admin → user features | **0** |
| INTENTIONAL | `useMarketSessionStatus` → `adminApi` (M6 limitation) |
| unexpected new | **0** |

---

## 16. Safety

TradingOrder/Outbox/create_order/POST orders (M8 audit) **0** · LIVE/ARM/Scheduler/Kill/Recovery **not executed** · Scanner/Shadow/News/A-B policy **0**.

---

## 17. Tests / lint / tsc

| Suite | Result |
|-------|--------|
| `menu.test.ts` | **11 PASS** |
| LIVE single-mount / risk surface | **PASS** |
| Upbit Hub tabs / Technical / Ops order | **PASS** |
| News pipeline order | **1 FAIL** — `dataSource={items.map}` vs WT `dataSource={items}` + rowKey — **PREEXISTING_WIP** (NewsCollector), not HEAD `f18d02f` regression |
| shared utils / orders / SR | **PASS** |
| Focused overall | **66 PASS / 1 FAIL (WIP)** |
| eslint menu | **PASS** |
| tsc M8-new on menu/shared | **0**; PREEXISTING: live-validation + NewsCollector |

---

## 18. Residual WIP (classify)

| Bucket | Examples | Class |
|--------|----------|-------|
| NewsCollector rowKey / Ambiguous | upbit panels | PREEXISTING_WIP · M8_NOT_RELEVANT |
| risk / portfolio / MarketExplorer / RuntimePreflight / live-validation | FE pages | PREEXISTING_WIP |
| recovery / accounts helpers | panels + untracked armToken | PREEXISTING_WIP |
| backend / tests / ops | py + ps1 | PREEXISTING_WIP · M8_NOT_RELEVANT |
| `.run` / `tmp_*` | local | PREEXISTING_WIP |
| M7-0 precheck md/json | untracked audit | PREEXISTING_WIP · optional docs commit later |
| CURRENT_WORK dirty before this STEP | docs | updated by M8-0 docs |

---

## 19. Risk buckets

| Bucket | Count | Items |
|--------|------:|-------|
| BLOCKER | **0** | — |
| HIGH | **0** | — |
| MEDIUM | **0** | — |
| LOW | **1** | Admin 6 leaves without `menu:*` (intentional; optional future) |
| DEFERRED_WIP | **1+** | NewsCollector test/tsc · other residual inventory |
| INFORMATIONAL | **2** | M2 9/8 superseded by CURRENT_APPROVED 11/12 · redirects retained |

---

## 20. Recommended final baseline

```text
Admin IA: 11 top / 55 leaf
User IA:  12 top / 29 leaf
Pages:    Admin 60 / User 36
Redirect: 12 (KEEP 3 / DEPRECATE 9) — retain
LIVE UBA: /admin/accounts only
Hub:      5 tabs
Shared:   utils7 / order7 / sr4
M7_CLOSE / M6_CLOSE / M5_CLOSE = YES
```

---

## 21. Next STEP (exactly one)

**M8-F — FINAL MENU / ROUTE / PERMISSION REGRESSION CLOSE**

No M8-A/B implementation required for PASS conditions.  
Optional later (out of M8): menu permission keys for 6 Admin leaves; WIP tracks separate.
