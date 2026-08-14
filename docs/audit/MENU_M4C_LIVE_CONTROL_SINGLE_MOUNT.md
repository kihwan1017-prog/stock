# MENU M4-C — LIVE/ARM Single-Mount Canonicalization (OPTION A)

**Mode:** APPLY · **Verdict:** `LIVE_CONTROL_SINGLE_MOUNT_READY_WITH_LIMITATIONS`  
**Date:** 2026-08-15  
**Baseline:** M4-B `e045c63` · M4-C0 design  
**Choice:** OPTION A

> `/admin/accounts` = FULL CONTROL · `/admin/upbit` = READ + link  
> Risk page LIVE duplicate = **DEFER** · commit/push 없음

---

## Mounts

| | before | after |
|--|--------|-------|
| `/admin/accounts` | `AdminUpbitLiveUbaPanel` | **유지** |
| `/admin/upbit` | `AdminUpbitLiveUbaPanel` | **제거** → `UpbitLiveStatusReadSummary` |
| total panel mounts | 2 | **1** |

---

## Ownership

| Surface | Owner |
|---------|-------|
| LIVE/ARM/Scheduler CONTROL | `/admin/accounts` panel |
| UBA CRUD / Credential / Resume / Recovery ops | `/admin/accounts` panel |
| LIVE/ARM/Scheduler READ summary | `/admin/upbit` summary (GET only) |
| Scanner / Shadow / News / Ambiguous | `/admin/upbit` (불변) |
| Recovery CONTROL page | `/admin/recovery` (+ summary link) |
| Risk page LIVE toggle | **DEFER** (미수정) |

---

## /admin/upbit READ fields

- Credential registered
- LIVE ON/OFF
- ARM ON/OFF
- Trading paused
- Live-ops readiness
- Trading Scheduler desired/actual
- Links: 계좌 관리 · 장애 복구

Mutation: LIVE/ARM/Scheduler/UBA CRUD/Credential — **없음**

---

## Preserved on /admin/upbit

Scanner · Combined Shadow · News Collector · Ambiguous · connection/sync/rate-limit UI

---

## Limitations / DEFER

- Risk page `TRUE_DUPLICATE_LIVE_CONTROL` 미해소
- Fat panel CRUD는 accounts-only (upbit에서 CRUD UI 제거 — 의도)
- Permission key `menu:accounts` vs `menu:upbit` redesign 없음

---

## Next

승인 후 선별 commit. **M5 / risk LIVE cleanup 자동 진행 금지.**
