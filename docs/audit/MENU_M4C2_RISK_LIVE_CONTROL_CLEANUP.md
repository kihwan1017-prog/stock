# MENU M4-C2-APPLY — Risk LIVE/ARM Control Single-Surface

**Mode:** APPLY · **Verdict:** `RISK_LIVE_CONTROL_SINGLE_SURFACE_READY_WITH_LIMITATIONS`  
**Date:** 2026-08-15  
**Baseline:** M4-C `85c3552` · M4-C2 `RISK_LIVE_DUPLICATE_CONFIRMED`  
**Commit readiness:** **`COMMIT_REQUIRES_WIP_SPLIT` → selective commit applied**  
(title/ops cross-links는 working tree residual로 유지)

> Risk page LIVE/ARM **mutation UI 제거**. Kill · settings · limits · status · accounts 링크 유지.  
> commit/push 하지 않음.

---

## Control matrix (after)

| Page | LIVE mut | ARM mut | Scheduler mut | Kill mut |
|------|----------|---------|---------------|----------|
| `/admin/accounts` | YES | YES | YES | — |
| `/admin/upbit` | NO | NO | NO | — |
| `/admin/risk` | **NO** | **NO** | NO | **YES** |

Panel mounts: **1** (accounts)

---

## Risk page changes (M4C2_APPLY)

REMOVE:
- `toggleLive` → `setAdminLiveOrderEnabled`
- `armLive` / `disarmLive`
- LIVE Switch / ARM·DISARM Buttons

KEEP:
- LIVE/ARM **Tag/text status**
- `updateAdminLiveRiskLimits` (한도 재적용)
- Kill Switch ON/OFF
- system/user risk save · trading flags · `account_paused`

ADD:
- Alert + `Link` → `/admin/accounts` (“계좌 LIVE 제어”)

---

## Diff classification

### PREEXISTING_WIP (시작 전 risk/page dirty)

- `import Link` / `adminRoutes`
- title/description “리스크 관리” 문구
- extra links: 거래 운영 현황 · 시스템 운영
- (제거됨) LIVE/ARM reason·correlation_id WIP — mutation 삭제와 함께 소멸

### M4C2_APPLY_DIFF

- LIVE/ARM mutation handlers·UI 제거
- status Tag / ARMED text
- Alert + accounts link
- `Alert`/`Tag` import

### UNEXPECTED_DIFF

없음 (accounts/upbit/backend 미변경)

---

## Commit note

동일 파일에 PREEXISTING_WIP(operations cross-links 등)와 M4-C2 변경이 혼재.  
선별 commit 시 interactive hunk split 또는 WIP 분리 후 재적용 필요 → **`COMMIT_REQUIRES_WIP_SPLIT`**.

---

## Next

승인 후 WIP split → 선별 commit. M5 금지.
