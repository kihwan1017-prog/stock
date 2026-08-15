# MENU M8-F — Final Menu / Route / Permission Regression CLOSE

**Mode:** FINAL CLOSE AUDIT ONLY · **production mutation = 0**  
**Date:** 2026-08-15  
**HEAD:** `f18d02f` · `release/v1.1.0` · origin **ahead 10**  
**Baseline:** M8-0 `FINAL_IA_REGRESSION_AUDIT_READY_WITH_LIMITATIONS`  
**Verdict:** `MENU_CONSOLIDATION_COMPLETE_WITH_LIMITATIONS`  
**MENU_CONSOLIDATION_CLOSE:** **YES**

> production/menu/route/redirect/permission/AuthGuard/API **변경 금지**.  
> residual WIP **정리 금지**. commit/push **금지** (본 STEP).

---

## Close flags

| Track | Status |
|-------|--------|
| M3 | **CLOSED** |
| M4 | **CLOSED** |
| M5 | **CLOSED** |
| M6 | **CLOSED** |
| M7 | **CLOSED** |
| M8 | **CLOSED** |

---

## Final approved IA baseline

| Portal | Top-level | Leaf | Status |
|--------|----------:|-----:|--------|
| **Admin** | **11** | **55** | CURRENT_APPROVED_IA |
| **User** | **12** | **29** | CURRENT_APPROVED_IA |

M2 target 9/8 is **not** the final bar. Do not force-merge domains to hit old counts.

### Admin domains (fixed)

운영 대시보드 · 회원·권한 · 계좌 · 시장 데이터 · 전략·후보 · 자동매매 운영 · 거래 · 리스크·안전 · 알림 · 시스템 운영 · 내 정보

### User highlights (fixed)

Strategy Request/Draft · LLM → `/user/ai` · Accounts · Market · Auto Trading · Orders · LIVE Validation · Risk/Notifications · Profile

---

## Final contracts (re-verified at HEAD)

| Contract | Value |
|----------|------:|
| Admin routes | **60** |
| User routes | **36** |
| KEEP_CANONICAL | **84** |
| KEEP_REDIRECT | **3** |
| DEPRECATE_REDIRECT | **9** |
| DETAIL_ONLY / HIDDEN_ACTIVE / ORPHAN / REMOVE | **0** |
| duplicate href / key / broken / unclassified | **0** |
| permission mismatch | **0** |
| intentional Admin no `menu:*` | **6** (role-gated; not Close blocker) |
| AuthGuard issues | **0** |
| `AdminUpbitLiveUbaPanel` mount | **1** (`/admin/accounts`) |
| duplicate LIVE/ARM mutation | **0** |
| Risk LIVE/ARM mutation | **0** (Kill retained) |
| Upbit Hub tabs | **5** |
| Upbit duplicate mounts / LIVE via Hub | **0** |
| shared utils / order keys / SR keys | **7 / 7 / 4** |
| unexpected cross-domain | **0** |
| redirects 12 / KEEP3 / DEP9 / chain0 | **PASS** |
| REMOVE gate | **FAIL** (UNKNOWN external) — intentional retain |

---

## M3–M7 one-line results

| STEP | Result |
|------|--------|
| M3 navigation + workflow promotion | **PASS** |
| M4 ops ownership + LIVE single surface + Risk cleanup | **PASS** |
| M5 Upbit Hub consolidation | **PASS** |
| M6 shared presentation | **PASS** |
| M7 legacy redirect compatibility | **PASS** |

---

## Tests / lint / tsc

| Result class | Count / note |
|--------------|--------------|
| PASS | **66** |
| FAIL_PREEXISTING_WIP | **1** (NewsCollector rowKey contract vs WT) |
| FAIL_FINAL_REGRESSION | **0** |
| eslint (menu / M3–M7 committed paths) | **PASS** (M8 new = 0) |
| tsc FINAL IA new | **0** |
| tsc PREEXISTING_WIP | live-validation + NewsCollector (known) |

---

## Residual WIP (not project FAIL)

| Class | Representative |
|-------|----------------|
| PREEXISTING_WIP | NewsCollector · Ambiguous · risk/portfolio · MarketExplorer · RuntimePreflight · live-validation · recovery · accounts helpers |
| UNRELATED_TO_MENU_CONSOLIDATION | backend · tests · ops · `.run` · `tmp_*` |
| MENU_RELATED_DEFERRED_WIP | optional Admin `menu:*` for 6 leaves · M7-0 precheck untracked docs |

~93 WT paths — **do not interpret as Menu Consolidation FAIL**.

---

## Risk final

| Bucket | Count | Close blocker? |
|--------|------:|----------------|
| BLOCKER | **0** | — |
| HIGH | **0** | — |
| MEDIUM | **0** | — |
| LOW | **1** | **No** — Admin 6 leaves lack dedicated `menu:*`; still behind Admin AuthGuard / role. Hardening is optional future STEP. |
| DEFERRED_WIP | **n** | separate tracks |

---

## Safety

TradingOrder / Outbox / create_order / POST orders **0** · LIVE/ARM/Scheduler/Runtime/Kill/Recovery **not executed** · Scanner/Shadow/Cohort/News/A-B/Gate policy **0**.

---

## Policy after CLOSE

Future menu/IA changes require a **new STEP** with explicit product/UX need.  
Do not reopen redirect deletion without telemetry/external evidence.  
Do not reopen Hub/LIVE ownership without safety review.

---

## Next STEP (exactly one)

Menu consolidation track **ended**.

**Return to trading-system roadmap monitoring:**  
Technical VALID cohort 50 / News A-B sample milestone  
(confirm current milestone via separate READ STEP if needed — not opened here).
