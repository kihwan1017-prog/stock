# MENU M4-C2 — Risk Page LIVE Duplicate Control Precheck

**Mode:** PRECHECK / DESIGN ONLY · **Verdict:** `RISK_LIVE_DUPLICATE_CONFIRMED`  
**Date:** 2026-08-15  
**Baseline:** M4-C `85c35523f10407b2a3f54912b3d410d47ced0345`  
**Source:** `frontend/src/app/(admin)/admin/risk/page.tsx` (working tree, **미수정**)

> Production mutation = **0**. risk/page.tsx · accounts panel · API · LIVE 상태 **변경 없음**.  
> 구현(버튼 삭제) 자동 진행 금지.

---

## 1. Risk page primary role

**`RISK_CONFIG_AND_KILL_CONTROL`**

Canonical 책임으로 자연스러운 것:

- Kill Switch ON/OFF
- 시스템/회원 리스크 설정 저장
- 거래 플래그 (`buy_enabled` / `sell_only` / `auto_trading_enabled`)
- `account_paused` (회원 리스크 설정)
- LIVE **한도** 재적용 (`updateAdminLiveRiskLimits`)
- daily-loss / policies / dashboard **READ**

LIVE ON/OFF · ARM/DISARM는 **계좌 실행 활성화**이며 Risk domain의 핵심이 아님.  
Accounts panel이 이미 Resume→Preflight→LIVE→ARM→Scheduler 순서를 enforce.

---

## 2. Inventory

### READ

| Feature | Source |
|---------|--------|
| Kill Switch status | `GET` kill-switch |
| Daily loss | `GET` daily-loss |
| Risk policies | `GET` risk-policies |
| Risk dashboard | `GET` dashboard/risk |
| System/user risk resolved | `GET` risk-settings |
| LIVE accounts list (per userId) | `GET /admin/live-order/users/{userId}/accounts` |
| LIVE / ARM / arm_expires status | table columns |
| Live risk limits display | row.risk |

### CONTROL

| Feature | API | Class |
|---------|-----|-------|
| Kill Switch ON/OFF | activate/deactivate Kill Switch | **KEEP** (Risk canonical) |
| System risk save | PUT system risk-settings | KEEP |
| User risk save | PUT user risk-settings | KEEP |
| Trading flags | setAdminUserTradingFlags | KEEP (user-level, ≠ UBA LIVE) |
| account_paused Switch | via user risk save | KEEP (risk pause flag) |
| **LIVE Switch** | `PUT /admin/live-order/accounts/{uba}` | **DUPLICATE** |
| **ARM Button** | `POST .../arm` | **DUPLICATE** |
| **DISARM Button** | `POST .../disarm` | **DUPLICATE** |
| LIVE limits reapply | `PUT .../risk-limits` | KEEP (risk limits — distinct from LIVE toggle) |
| Trading Scheduler | — | **`SCHEDULER_CONTROL_NOT_PRESENT`** |

---

## 3. LIVE / ARM UI detail

| UI | Handler | API | Payload | Scope |
|----|---------|-----|---------|-------|
| Switch `live_order_enabled` | `toggleLive` | `setAdminLiveOrderEnabled` → PUT live-order | `live_order_enabled`, `reason=ADMIN_RISK_PAGE_LIVE_*`, `correlation_id=risk-live-…` | per UBA (any broker in list) |
| Button ARM | `armLive` | `armAdminLiveOrder` → POST arm | `reason=ADMIN_RISK_PAGE_ARM`, `correlation_id=risk-arm-…` | per UBA |
| Button DISARM | `disarmLive` | `disarmAdminLiveOrder` → POST disarm | `turn_live_off=false`, `reason=ADMIN_RISK_PAGE_DISARM`, `correlation_id=…` | per UBA |

Confirmation: **없음** (Switch/Button 즉시 mutate).  
Warning: 카드 설명 문구만 (LIVE만으로 주문 불가 · ARM 필요).

---

## 4. Endpoint 비교 (Accounts canonical)

| | Accounts panel | Risk page | Match |
|--|----------------|-----------|-------|
| LIVE | PUT `/api/v1/admin/live-order/accounts/{uba}` | **동일** | YES |
| ARM | POST `.../arm` | **동일** | YES |
| DISARM | POST `.../disarm` | **동일** | YES |
| Scheduler | POST trading-scheduler start/pause | **없음** | — |
| reason | `ADMIN_UI_LIVE_*` / ARM_* | `ADMIN_RISK_PAGE_*` | 문자열만 다름 |
| correlation_id | `newCorrelationId(action)` | `risk-live-{uba}-{ts}` 등 | 형식만 다름 |
| UBA scope | UPBIT list filter in panel | userId의 live-order accounts (broker 컬럼 표시) | **UBA-level 동일 API** |

**분류: `TRUE_DUPLICATE_LIVE_CONTROL` + `TRUE_DUPLICATE_ARM_CONTROL`**

---

## 5. FE gate 비교 (HIGH priority)

| Gate | Accounts panel | Risk page |
|------|----------------|-----------|
| Modal.confirm | YES | **NO** |
| Preflight READY+FRESH | YES (LIVE ON) | **NO** |
| Scheduler must PAUSE | YES | **NO** |
| trading_paused / Resume | YES | **NO** |
| ARM ON requires LIVE | YES | partial (`disabled={!live}`) |
| LIVE OFF requires DISARM+PAUSE | YES | **NO** |
| Credential/recovery/conflict | panel context | **NO** |
| disabled reason messaging | rich | minimal |

→ Risk FE gate가 **현저히 약함** → **HIGH priority duplicate**.

Server gate: 동일 endpoint → `LiveOrderApprovalService` + `require_admin` + audit **유지**.  
UI에서 Risk mutation을 제거해도 server safety **약화되지 않음**.

---

## 6. Kill Switch vs LIVE

| | Kill Switch | LIVE |
|--|-------------|------|
| 목적 | 비상 전역 차단 | 계좌 실행 활성화 |
| Risk page | **canonical CONTROL** | duplicate shortcut |
| 혼동 | 같은 화면에 두면 “리스크 설정”과 “실거래 켜기”가 인접 | 운영자 오조작 위험 |

권장 분리: Kill은 Risk · LIVE/ARM은 Accounts.

---

## 7. Permission

| Page | menu permission |
|------|-----------------|
| `/admin/risk` | `menu:risk` |
| `/admin/accounts` | `menu:accounts` |
| Backend LIVE API | `require_admin` (menu key 무관) |

Admin role → permission bypass.  
현재 Admin-only 운영이면 Risk LIVE 제거 후 Accounts로 유도해도 실제어 가능.  
비admin이 `menu:risk`만 갖는 미래 role은 **accounts 링크 + 접근 매트릭스 확인** 필요 (permission redesign은 M4-C2 구현 범위 밖).

---

## 8. Operator flow

```text
계좌/Credential → Recovery → Risk(limits/Kill) → Preflight → LIVE → ARM → Scheduler
```

Risk의 LIVE Switch는 **shortcut / 약한 경로**이며 Accounts 순서 enforce를 우회할 수 있음 → 제거 후보가 타당.

---

## 9. 제거 후보 분류

| Surface | Class |
|---------|-------|
| LIVE Switch mutation | **A. REMOVE_CONTROL_CANDIDATE** |
| ARM/DISARM Buttons | **A. REMOVE_CONTROL_CANDIDATE** |
| LIVE/ARM status columns | **B. KEEP_STATUS_ONLY** |
| LIVE risk-limits 재적용 | **C. KEEP_CONTROL** (limits ≠ activation) |
| Kill Switch / risk settings / flags | **C. KEEP_CONTROL** |
| Scheduler | not present |

Overall: **REMOVE_CONTROL_CANDIDATE** (LIVE/ARM mutation) + status keep.

---

## 10. Target Risk UI (설계만)

```text
/admin/risk
  CONTROL: Kill Switch · risk settings · flags · account_paused · LIVE limits
  READ: LIVE/ARM status tags (mutation 없음)
  LINK: → /admin/accounts (계좌 LIVE/ARM 제어)
```

Control surface count:

| | before | target |
|--|--------|--------|
| UBA LIVE mutation surfaces | accounts panel + risk = **2** | **1** (accounts) |
| UBA ARM mutation surfaces | accounts + risk = **2** | **1** |
| Scheduler | accounts = **1** | **1** |
| AdminUpbitLiveUbaPanel mounts | **1** (M4-C) | **1** |

---

## 11. Implementation risk (후속 STEP)

**MEDIUM** — risk/page.tsx는 기존 WIP(reason/correlation)와 혼재.  
후속 구현 시 **LIVE/ARM mutation UI만** 제거하고 status+link 유지.  
한도 재적용·Kill·settings는 유지.  
**이번 PRECHECK에서 수정 금지.**

---

## 12. Safety / regression

- M4-C single-mount: accounts=1, upbit=0 — **유지** (본 STEP 무변경)
- TradingOrder / Outbox / create_order / POST orders — **0** (미호출)
- production code mutation — **0**

---

## 13. Next STEP (exactly one)

**M4-C2-APPLY — Risk page LIVE/ARM mutation removal (status+link keep)**  
승인 후만. 자동 진행 금지.
