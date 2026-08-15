# CURRENT_WORK

**역할:** 현재 진행 중인 작업만 기록한다. 과거 완료 목록을 나열하지 않는다.  
**최종 갱신:** 2026-08-15

---

## Current Phase

**STEP M6-B — COMMON_READ Order Columns Shared** — baseline 커밋 (`ORDER_READ_COLUMNS_SHARED_READY_WITH_LIMITATIONS`)

| 항목 | 값 |
|------|-----|
| Branch | `release/v1.1.0` · M6-A `239550d` |
| shared | `frontend/src/shared/orders/orderReadColumns.ts` · **7** keys |
| Evidence | [audit/MENU_M6B_ORDER_READ_COLUMNS_SHARED.md](audit/MENU_M6B_ORDER_READ_COLUMNS_SHARED.md) |
| mutation/query/API | **0** |
| commit | **본 커밋으로 baseline 고정** (push 없음) |
| next | **M6-C0** Strategy Request READ presentation PRECHECK (승인 후 · READ-ONLY) |

병렬: residual WIP **미수정** · Admin dataHelpers shim 유지

---

## 현황 요약 (추정)

개발 ~85% · Paper ~85% · LIVE ~58% · 운영 **NOT READY** · LIVE **NOT APPROVED**

## Next Gate

1. **M6-C0** Strategy Request READ presentation PRECHECK (**승인 후 · READ-ONLY**)  
2. Order query/filter/hook/mutation 공용화 **금지**  
3. residual WIP 별도  

→ [ROADMAP.md](ROADMAP.md)
