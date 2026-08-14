# CURRENT_WORK

**역할:** 현재 진행 중인 작업만 기록한다. 과거 완료 목록을 나열하지 않는다.  
**최종 갱신:** 2026-08-15

---

## Current Phase

**STEP M6-A — Shared Formatters / Utils** — baseline 커밋 (`SHARED_FORMATTERS_UTILS_READY_WITH_LIMITATIONS`)

| 항목 | 값 |
|------|-----|
| Branch | `release/v1.1.0` |
| 변경 | `shared/utils` · user→admin dataHelpers **0** · Request/Draft/Risk formatters |
| Evidence | [audit/MENU_M6A_SHARED_FORMATTERS_UTILS.md](audit/MENU_M6A_SHARED_FORMATTERS_UTILS.md) |
| commit | **본 커밋으로 baseline 고정** (push 없음) |
| next | **M6-B0** Order RO shared columns PRECHECK (승인 후 · READ-ONLY) |

병렬:

- Admin dataHelpers shim 잔존 (~56 admin files)  
- residual WIP (Ambiguous/News rowKey/RuntimePreflight/portfolio rowKey/MarketExplorer 등) **WT 유지**

---

## 현황 요약 (추정)

개발 ~85% · Paper ~85% · LIVE ~58% · 운영 **NOT READY** · LIVE **NOT APPROVED**

## Next Gate

1. **M6-B0** Order RO shared columns PRECHECK (**승인 후 · READ-ONLY**)  
2. Admin shim bulk migrate — 선택 후속  
3. residual WIP 별도  

→ [ROADMAP.md](ROADMAP.md)
