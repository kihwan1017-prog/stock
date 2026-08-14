# MENU M5-E0 — Upbit Ops / Reconciliation Tab Precheck

**Mode:** PRECHECK / DESIGN ONLY · **Verdict:** `OPS_RECONCILIATION_SECTION_REORGANIZE`  
**Date:** 2026-08-15  
**Baseline commit:** `ffaa247cdc447206842872a306d53d227a10b58a`  
**Host:** `/admin/upbit` → 운영·정합 (`ops={<UpbitHubOpsSection />}`)

> Production mutation **0**. commit/push **없음**. M5-E 구현 **금지**.  
> Ambiguous / NewsCollector / risk 등 WIP **미수정**.

---

## 0. Executive summary

운영·정합 탭 = **`UpbitHubOpsSection` (278 LOC)** + 내부에 마운트된 **`UpbitAmbiguousOrdersPanel` (491 LOC HEAD)**.  
page.tsx는 accounts 링크만 유지하고 ops action은 이미 OpsSection으로 이동됨.

기능은 UPBIT broker ops(연결·잔고 sync·체결 reconcile·rate·snapshot) + Ambiguous 정합으로 **도메인이 명확**하다. LIVE/ARM/Scheduler CONTROL 복제 **없음**.  
다만 OpsSection에 **섹션 heading이 거의 없고** 버튼·JSON·테이블이 한 스택이라 discoverability가 낮다.

**권장: OPTION B — SECTION_REORGANIZE** (`UpbitHubOpsSection`만 heading/순서 · **Ambiguous 파일 미수정**).

---

## 1. Complexity

| Surface | LOC | useState | useEffect | useQuery | useMutation | onClick | APIs used |
|---------|----:|---------:|----------:|---------:|------------:|--------:|----------:|
| `UpbitHubOpsSection` | **278** | **1** (`ubaId`) | 0 | 3 | 4 | ~5 | 7 |
| `UpbitAmbiguousOrdersPanel` (HEAD) | **491** | 0* | 0 | 4 | 7 | ~7 | 11 |
| Combined Ops tab | — | — | — | 7 | 11 | — | 18 |

\* Ambiguous는 `useState` 제네릭 표기로 카운트 왜곡 가능; 실질 로컬 state 머신 약함.

Mount: OpsSection **1** (page) · Ambiguous **1** (OpsSection만).

---

## 2. Inventory (존재하는 것만)

| ID | Feature | Domain | Risk | Present |
|----|---------|--------|------|---------|
| A | Account status JSON | STATUS_ONLY / ACCOUNT_OPS | READ_ONLY | YES |
| B | Connection test | BROKER_OPS | LOW_RISK_MUTATION | YES |
| C | Balance sync (UBA) | ACCOUNT_OPS / SNAPSHOT | MEDIUM_RISK_MUTATION | YES |
| D | Order reconcile (체결 동기화) | RECONCILIATION | MEDIUM_RISK_MUTATION | YES |
| E | Rate limit table + Recheck | RATE_LIMIT | LOW_RISK_MUTATION (재조회, 강제 해제 없음) | YES |
| F | Snapshot table + raw JSON | SNAPSHOT | READ_ONLY (+ sync가 write) | YES |
| G | Ambiguous list/health | AMBIGUOUS_ORDER | READ_ONLY | YES |
| H | Ambiguous resolver run / lookup / claim / manual / approve prep / reject | AMBIGUOUS_ORDER | MEDIUM→HIGH (approve=prep only, no auto-send) | YES |
| I | Recovery link | RECOVERY_REFERENCE | — | **Overview LiveSummary에만** (Ops 탭 내 링크 **없음**) |
| J | Accounts link | STATUS_ONLY ref | — | **page header** (+ LiveSummary) |
| K | LIVE/ARM/Scheduler control | — | — | **없음** (의도) |

---

## 3. API matrix (OpsSection)

| Handler | Method | Path | Scope | Confirm | Audit UI |
|---------|--------|------|-------|---------|----------|
| `getUpbitAccountStatus` | GET | `/broker/upbit/account/status` | broker env | — | JSON card |
| `testUpbitAccountConnection` | POST | `/broker/upbit/account/connection-test` | broker | no | message |
| `syncUpbitAccount` | POST | `/broker/upbit/account/sync?user_broker_account_id=` | UBA | no | message |
| `getUpbitAccountSnapshot` | GET | `/broker/upbit/account/snapshot` | UBA | — | table+JSON |
| `reconcileUpbitOrders` | POST | `/broker/upbit/account/reconcile-orders` | broker orders | no | message |
| `getUpbitRateLimits` | GET | `/admin/upbit/rate-limits` | admin | — | table |
| `recheckUpbitRateLimits` | POST | `/admin/upbit/rate-limits/{uba}/recheck` | UBA | no | “강제 해제 없음” |

### Ambiguous (요약)

| Group | APIs |
|-------|------|
| GET | list / health / resolver status / resolver runs |
| POST mut | run resolver now · retry lookup · release claim · lookup · manual review · **approve resubmit prep** · reject |

Approve: UI “자동 전송 없음” → **TRADING send 아님**.

---

## 4. Canonical ownership

| Feature | Elsewhere | Class | Keep on Ops? |
|---------|-----------|-------|--------------|
| LIVE/ARM/Scheduler CONTROL | `/admin/accounts` | STATUS_VS_CONTROL (Hub READ elsewhere) | **no control here** ✓ |
| Accounts link | header / LiveSummary | CROSS_DOMAIN_REFERENCE | YES |
| Recovery | `/admin/recovery` · LiveSummary link | CROSS_DOMAIN_REFERENCE | Ops에 링크 추가 가능(선택) |
| Ambiguous UI | **only Ops tab** | DIFFERENT_SCOPE | **YES keep** (orders/recovery에 mount 없음) |
| reconcile-orders | only Ops | DIFFERENT_SCOPE (≠ Ambiguous remote lookup) | YES |
| syncUpbitAccount | Ops only | DIFFERENT_SCOPE vs accounts `refreshAdminUbaSnapshot` | YES (유사하나 API 상이) |
| connection-test | Ops only | DIFFERENT_SCOPE | YES |
| rate recheck | Ops only | DIFFERENT_SCOPE (Upbit broker ops) | YES |
| Orders Outbox UI | `/admin/orders` | DIFFERENT_SCOPE | 유지 |

**TRUE_DUPLICATE (LIVE panel / Ambiguous mounts):** **0**  
**SUMMARY_VS_DETAIL:** account status JSON vs accounts UBA detail  
**STATUS_VS_CONTROL:** LiveSummary vs accounts CONTROL  

---

## 5. Domain notes

### Ambiguous
Upbit order ambiguity + remote lookup resolver + resubmit **prep**.  
`/admin/orders`·`/admin/recovery`에 UI 없음 → **Upbit Ops에 두는 것이 자연** (이동 금지 / MOVE_CANONICAL 비권장).

### Reconciliation (`reconcileUpbitOrders`)
Broker fill/order sync 요청 — Ambiguous lookup과 **다른 domain**. Recovery conflict resolve와도 다름.

### Balance sync
UBA snapshot binding sync — accounts의 runtime snapshot refresh와 **유사 목적·다른 endpoint** → TRUE_DUPLICATE 아님.

### Connection test
Broker connectivity probe — accounts connection_status **표시**와는 STATUS vs probe.

### Rate recheck
Status reprobe, not unblock — UPBIT ops에 적합 (monitoring 전역 아님).

---

## 6. UI flow

**Current:**
blurb → UBA+연결/잔고/체결 버튼 → account status → rate table/health → snapshot → Ambiguous panel

**Desired:**
Status → Connection/Sync → Rate → Snapshot → Reconciliation → Ambiguous → (optional Recovery/Accounts CROSS_LINK)

**Gap:** heading 부재 · reconcile이 sync와 같은 버튼 줄 · Ambiguous 전 구분 약함.

---

## 7. Options

| Option | Eval |
|--------|------|
| A KEEP_AS_IS | 가능하나 discoverability 약함 |
| **B SECTION_REORGANIZE ★** | OpsSection heading/순서만 · Ambiguous **파일 손대지 않음** · WIP 안전 |
| C REDUCE_DUPLICATE_ACTIONS | TRUE_DUPLICATE control **없음** → 불필요 |
| D MOVE_CANONICAL | Ambiguous 이동 근거 약함 · M5에서 비권장 |
| E COMPONENT_SPLIT | Ambiguous 이미 분리됨 · Ops 278은 split 과잉 |

**권장: B**  
reorder **YES (OpsSection only)** · duplicate remove **NO** · split **NO** · route/permission/API **NO**

---

## 8. Ambiguous WIP (WT vs HEAD)

| Class | Content |
|-------|---------|
| **PREEXISTING_WIP** | ~64 lines: **한글 라벨/메시지 복구·encoding** (로직/API 동일로 보임) |
| **M5-E0 production diff** | **0** |
| **UNEXPECTED** | **0** |

M5-E 구현 시 **AmbiguousOrdersPanel.tsx 편집 금지** 권고 (WIP 충돌).

---

## 9. Safety / regression

| Check | Result |
|-------|--------|
| LIVE/ARM/Scheduler on Ops | mutation **0** |
| M4 accounts canonical | intact |
| M5 tabs / mounts | 1 each |
| TradingOrder/Outbox this STEP | 0 |
| reconcile/sync/resolve **executed** | **NO** (READ-ONLY) |

---

## 10. Next STEP (exactly one)

**STEP M5-E — Ops SECTION_REORGANIZE only**  
(`UpbitHubOpsSection` headings/order · **do not edit AmbiguousOrdersPanel** · no API/policy)

승인 전 구현 금지.
