# CURRENT_WORK

**역할:** 현재 진행 중인 작업만 기록한다. 과거 완료 목록을 나열하지 않는다.  
**최종 갱신:** 2026-08-15

---

## Current Phase

**STEP M5-F — Upbit Hub Final Regression Audit** — docs baseline (`UPBIT_HUB_CONSOLIDATION_COMPLETE_WITH_LIMITATIONS` · **M5_CLOSE=YES**)

| 항목 | 값 |
|------|-----|
| Branch | `release/v1.1.0` @ `21632e6` + 본 docs 커밋 |
| 산출물 | [audit/MENU_M5F_UPBIT_HUB_FINAL_REGRESSION_AUDIT.md](audit/MENU_M5F_UPBIT_HUB_FINAL_REGRESSION_AUDIT.md) · JSON |
| production mutation | **0** |
| commit | **본 커밋으로 감사 docs 고정** (push 없음) |
| next | **M6-0** PRECHECK (승인 후 · READ-ONLY) |

병렬 트랙 (Hub 밖):

- NewsCollector rowKey WIP · Ambiguous WIP · risk/RuntimePreflight WIP  
- News A/B MATCHED 누적 · Technical VALID≈50  

---

## 현황 요약 (추정)

개발 ~85% · Paper ~85% · LIVE ~58% · 운영 **NOT READY** · LIVE **NOT APPROVED**

## Next Gate

1. **M6-0** Shared component consolidation PRECHECK (**승인 후 · READ-ONLY**)  
2. Hub 구조 추가 변경 — **별도 요구 없는 한 종료**  
3. residual WIP 별도 선별  

→ [ROADMAP.md](ROADMAP.md)
