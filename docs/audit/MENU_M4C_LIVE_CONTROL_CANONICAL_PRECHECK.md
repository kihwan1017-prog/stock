# MENU M4-C0 — LIVE / ARM Control Canonicalization Precheck

**Mode:** PRECHECK / DESIGN ONLY · **Verdict:** `LIVE_CONTROL_CANONICAL_DESIGN_READY`  
**Date:** 2026-08-15  
**Baseline:** M4-B `e045c638f6656f63a97f472f42a29bbddaaf0a0c`  
**Input:** M4-0 TRUE_DUPLICATE D1 · M4-A/M4-B menu IA

> Production menu/page/route/component/API **변경 없음**.  
> LIVE/ARM/Scheduler **실행·상태 변경 없음**.  
> M4-C 구현 자동 진행 금지.

---

## 1. Mount inventory

| # | Route | Parent | Import | Props | UBA selection | Filter |
|---|-------|--------|--------|-------|---------------|--------|
| 1 | `/admin/accounts` | `accounts/page.tsx` | `@/features/admin/accounts/AdminUpbitLiveUbaPanel` | **none** (`<AdminUpbitLiveUbaPanel />`) | panel 내부 `detailUbaId` state | `listAdminBrokerAccounts({ broker_code: "UPBIT" })` |
| 2 | `/admin/upbit` | `upbit/page.tsx` | 동일 | **none** | 동일 (독립 React tree) | 동일 |

**Mount count = 2.** 추가 mount **없음** (테스트 import만 존재).

### 동일 component / config

| 항목 | 결과 |
|------|------|
| 동일 module export | YES |
| props 차이 | **없음** (둘 다 zero-props) |
| API client | 동일 `adminApi.*` |
| mutation handlers | 동일 `runtimeControlMutation` |
| confirmation | 동일 `modal.confirm` + reason 코드 |
| readiness / preflight | 동일 query keys |

**분류: `TRUE_DUPLICATE_CONTROL`**

두 마운트는 별도 React instance이므로 상태(`detailUbaId` 등)는 공유되지 않음.  
동일 UBA에 대해 **두 화면에서 동시 HIGH-risk mutation 가능**.

---

## 2. Panel 기능 분해

### READ (status)

- UBA list (UPBIT, inactive 포함)
- LIVE / ARM / trading_paused / credential_status
- live-ops-readiness · autotrading-readiness
- Trading Scheduler desired/actual
- Runtime preflight (LIVE_ON mode) freshness
- ops status · conflict summary
- Worker status (readiness.checks 경유, FE mutation 없음)

### CONTROL (mutation)

| Control | API | Method | Confirm | UBA scope |
|---------|-----|--------|---------|-----------|
| LIVE ON/OFF | `/api/v1/admin/live-order/accounts/{uba}` | PUT | Modal + UI gate | per UBA |
| ARM | `.../arm` | POST | Modal + UI gate | per UBA |
| DISARM | `.../disarm` | POST | Modal + UI gate | per UBA |
| Scheduler RUN | `/api/v1/admin/trading-scheduler/start` | POST | Modal + UI gate | body `user_broker_account_id` |
| Scheduler PAUSE | `/api/v1/admin/trading-scheduler/pause` | POST | Modal | optional UBA |
| Resume Trading | recovery resume | POST | Modal | per UBA |
| Unlock Account | recovery unlock | POST | (panel) | per UBA |
| Retry Recovery | account recovery | POST | | per UBA |
| Conflict dry-run | dry-run resolve | POST | Dry-run only (`DRY_RUN_ONLY`) | per UBA |
| UBA CRUD | broker-accounts | POST/PUT/DELETE | | UPBIT |
| Credential register/replace | credential vault | POST | | per UBA |
| Recommended risk apply | broker risk | POST | | per UBA |
| Refresh snapshot | refresh | POST | | per UBA |

**중요:** panel은 LIVE/ARM만이 아니라 **UBA CRUD + Credential + Recovery ops**까지 포함한 **fat composite**.  
M4-C에서 mount 제거 = CRUD까지 한쪽에서 사라질 수 있음 → status/link 대체 필수.

---

## 3. Page roles

### `/admin/accounts`

- Primary: 전체 계좌 허브 (Paper CRUD · Kiwoom sync · **UPBIT LIVE UBA panel** · broker snapshot)
- LIVE/ARM이 “계좌 수명주기”의 자연 연장인가? **YES (장점)**
- 단점: multi-broker 페이지에 Upbit-특화 panel이 무거움; Upbit ops 허브와 동선 분리

### `/admin/upbit`

- Primary: UPBIT 운영 허브 (UBA panel + Scanner + Shadow + News + Ambiguous + account sync)
- LIVE/ARM을 Upbit 허브 canonical로? **운영 discoverability는 높음**
- 단점: Kiwoom 확장 시 broker hub마다 LIVE surface 복제 위험; API는 UBA-generic인데 UI만 Upbit에 고착

---

## 4. Operator flow

```text
UBA 생성/Credential → Connection/Recovery Resume
→ Risk/한도 → Preflight → LIVE ON → ARM → Scheduler RUN
→ (Upbit) Scanner/Shadow/News 관찰
```

| 단계 | 가장 자연스러운 화면 |
|------|---------------------|
| CRUD / Credential / Resume | **accounts** (또는 panel 공통) |
| LIVE / ARM / Scheduler | **accounts** (UBA-generic API) 또는 upbit (현재 운영 습관) |
| Scanner / News / Ambiguous | **upbit only** |

권장: HIGH-risk control은 **accounts**, Upbit hub는 **status + deep link**.

---

## 5. OPTIONS

### OPTION A — Canonical `/admin/accounts`

| 기준 | 평가 |
|------|------|
| 업무 자연성 | 계좌 수명주기와 정합 |
| 위험 control 집중 | HIGH — 단일 surface |
| discoverability | Upbit 전용 운영자는 링크 필요 |
| UBA context | 명확 |
| broker extensibility | **최상** (Kiwoom panel 병치 가능) |
| Upbit 결합 | 약함 (의도적) |
| menu IA | 계좌 그룹과 일치 |
| 중복 제거 용이 | panel mount 1회만 유지 |

**secondary `/admin/upbit`:** panel 제거 → READ summary (ops/readiness tags) + Link `/admin/accounts`  
CRUD를 upbit에서 잃으면 안 되면: accounts에 CRUD+CONTROL 유지, upbit는 status만.

### OPTION B — Canonical `/admin/upbit`

| 기준 | 평가 |
|------|------|
| discoverability | Upbit ops 중 최고 |
| broker extensibility | **최악** (broker hub 고착) |
| API ownership 정합 | 약함 (UBA-generic API vs Upbit page) |
| accounts 역할 | CRUD/Paper와 LIVE 분리되어 흐름 분절 |

### OPTION C — `/admin/live-control` 신설

- HIGH 집중도 우수하나 route/menu/permission 신설 → **M4-C 범위 초과 · 비권장**
- 구현 금지 (본 PRECHECK)

### OPTION D — 이중 mount 유지

- 위험: 동일 UBA에 이중 confirm 경로 · 상태 레이스 · 오조작
- 장점: 동선 최소
- **비권장** (M4-0 D1 해소 목표와 충돌)

---

## 6. Recommended

**`OPTION_A`**

| | |
|--|--|
| canonical_page | `/admin/accounts` |
| secondary_page | `/admin/upbit` |
| secondary UX | READ status + “계좌 LIVE 제어” 링크 (mutation 0) |
| risk page | **별도 DEFER** — TRUE_DUPLICATE_LIVE_CONTROL (약한 FE gate). WIP 수정 금지 |

### Scoring (요약)

| 기준 | A | B | C | D |
|------|---|---|---|---|
| 업무 자연성 | 4 | 3 | 3 | 2 |
| 위험 집중 | 5 | 4 | 5 | 1 |
| discoverability | 3 | 5 | 2 | 5 |
| UBA 명확성 | 5 | 4 | 5 | 3 |
| broker extensibility | 5 | 1 | 4 | 2 |
| Upbit 결합 | 2 | 5 | 2 | 5 |
| menu IA | 5 | 3 | 2 | 3 |
| 중복 제거 | 5 | 5 | 5 | 0 |

---

## 7. API ownership

| API | Class |
|-----|--------|
| `/admin/live-order/accounts/{uba}` | **UBA-generic** (admin, `require_admin`) |
| `.../arm` · `.../disarm` | **UBA-generic** |
| `/admin/trading-scheduler/start\|pause` | **UBA-scoped body**, broker-agnostic admin |
| Panel list filter `UPBIT` | UI filter only |

→ UI canonical도 **account/UBA 중심(OPTION A)** 이 정합.

---

## 8. Permission

| Menu leaf | permission |
|-----------|------------|
| 전체 계좌 `/admin/accounts` | `menu:accounts` |
| 업비트 계좌 `/admin/upbit` | `menu:upbit` |

- Admin role → `hasPermission` **bypass** (현재 운영자 대부분 양쪽 접근).
- 비admin이 `menu:upbit`만 가진 경우 OPTION A 시 LIVE UI 접근 손실 가능 → **M4-C 구현 전 접근 매트릭스 확인** (permission key 변경은 금지·후속).

Backend LIVE API는 menu permission이 아니라 **`require_admin`**.

---

## 9. Risk page classification

`risk/page.tsx` (WIP — **분석만**, 수정 금지):

- `setAdminLiveOrderEnabled` / `armAdminLiveOrder` / `disarmAdminLiveOrder` 사용
- Switch/Button UI — **panel의 preflight·scheduler UI gate·순서 enforce 약함**
- Trading Scheduler control **없음**

**`TRUE_DUPLICATE_LIVE_CONTROL`** (partial surface / weaker FE gates)

M4-C 범위에서 risk 정리 **DEFER** (별도 STEP 또는 risk WIP 정리 후).

---

## 10. Server gates

UI 중복 제거해도 server gate는 유지:

- LIVE ON/OFF: `LiveOrderApprovalService` + audit (`live_order_safety.py`, `require_admin`)
- ARM/DISARM: 동일 모듈 server gate + correlation
- Scheduler start: LIVE/ARM gate (STEP 9-5)

**UI canonicalization ≠ gate 약화.**  
Risk page의 약한 FE gate는 server가 최종 방어이나, FE 오조작 UX는 panel이 우수 → canonical은 panel 쪽.

---

## 11. Target UI (M4-C 설계)

**Canonical `/admin/accounts`:**

- 기존 `AdminUpbitLiveUbaPanel` **풀 유지** (CRUD+CONTROL)

**Secondary `/admin/upbit`:**

- `AdminUpbitLiveUbaPanel` **마운트 제거** (구현 시)
- 최소: Alert/Tags로 LIVE·ARM·Scheduler 요약 (기존 readiness/ops GET 재사용) + `Link` → `/admin/accounts`
- Scanner/Shadow/News/Ambiguous **불변**
- 대규모 shared component 신설 **금지**

**Status duplication:** secondary에서 LIVE OFF / ARM OFF / Scheduler PAUSED 표시 **허용**.  
**Control duplication:** mutation button **canonical 1곳만**.

---

## 12. Minimal implementation plan (M4-C, 미실행)

1. `/admin/upbit/page.tsx`에서 `<AdminUpbitLiveUbaPanel />` 제거
2. 짧은 READ summary + Link `/admin/accounts` 추가 (기존 API GET만)
3. focused vitest: mount count accounts=1, upbit=0; Scanner panels 존재
4. risk page · AuthGuard · permission · backend **무변경**
5. LIVE/ARM/Scheduler **실행 테스트 금지** (UI presence만)

**Implementation risk:** MEDIUM — upbit 운영 습관 회귀 · CRUD가 upbit에서만 쓰이던 경우 동선 변경.  
완화: summary에 “계좌 관리에서 UBA/LIVE 제어” 문구.

---

## 13. Regression protect (M4-C 전)

UBA CRUD · Credential · Connection · Risk · Recovery · LIVE · ARM · Trading Scheduler · Scanner · Shadow · News · Combined A/B

---

## 14. Safety state (본 STEP)

READ-ONLY. **상태 조회·변경 API 호출하지 않음.**  
코드 기본값 문서상 `UPBIT_LIVE_ORDER_ENABLED=false` (upbit page copy).  
실제 GLOBAL/UBA LIVE/ARM/Scheduler 런타임 값은 본 PRECHECK에서 probe하지 않음.

---

## 15. DEFER

- Risk page LIVE/ARM duplicate 제거
- Panel CRUD vs LIVE 분리 (fat panel split)
- OPTION C live-control page
- permission key 통합 (`menu:accounts` vs `menu:upbit`)
- Kiwoom LIVE panel (존재하지 않으면 후속)

---

## 16. Next STEP (exactly one)

**M4-C — LIVE/ARM control single-mount (OPTION A)** — 승인 후만. 자동 진행 금지.
