# CURRENT_WORK

**역할:** 현재 진행 중인 작업만 기록한다. 과거 완료 목록을 나열하지 않는다.  
**최종 갱신:** 2026-08-15

---

## Current Phase

**STEP M5-E — Ops SECTION_REORGANIZE** — baseline 커밋 (`OPS_RECONCILIATION_SECTION_REORGANIZE_READY_WITH_LIMITATIONS`)

| 항목 | 값 |
|------|-----|
| Branch | `release/v1.1.0` |
| 변경 | Ops Status→Sync→Rate→Snapshot→Reconcile→Ambiguous |
| Evidence | [audit/MENU_M5E_OPS_RECONCILIATION_SECTION_REORGANIZE.md](audit/MENU_M5E_OPS_RECONCILIATION_SECTION_REORGANIZE.md) |
| commit | **본 커밋으로 baseline 고정** (push 없음) |
| residual | Ambiguous 한글 WIP · NewsCollector rowKey WIP — WT 유지 |

병렬 트랙:

- News A/B MATCHED 누적 · Technical VALID≈50
- Ambiguous/risk/rowKey WIP — 별도 선별

---

## 현황 요약 (추정)

개발 ~85% · Paper ~85% · LIVE ~58% · 운영 **NOT READY** · LIVE **NOT APPROVED**

## Next Gate

1. **M5-F** Upbit Hub Final Regression Audit (**승인 후**)  
2. News A/B MATCHED≥20 · Technical VALID≈50  
3. Ambiguous/rowKey WIP 별도 처리  

→ [ROADMAP.md](ROADMAP.md)
