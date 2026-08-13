# CURRENT_WORK

**역할:** 현재 진행 중인 작업만 기록한다. 과거 완료 목록을 나열하지 않는다.  
**최종 갱신:** 2026-08-14

---

## Current Phase

**Technical Shadow Cohort REVIEW_READY Performance Review v2** — 완료 (`TECHNICAL_COHORT_REVIEW_COMPLETE_CHANGE_CANDIDATES`)

| 항목 | 값 |
|------|-----|
| Branch | `release/v1.1.0` |
| Milestone | `SHADOW_COHORT_30_REVIEW_READY` (VALID=32, NEW_POLICY MATCH=16, mismatch=0) |
| 판정 | CHANGE_CANDIDATE=TP만 (적용 **금지**) · next gate **n≈50** |
| Evidence | `docs/audit/TECHNICAL_SHADOW_COHORT_REVIEW_READY_V2_20260814.*` |
| News A/B | 별도 자연 누적 (`NEWS_AB_SAMPLE_ACCUMULATING`) — Technical과 미혼합 |
| CONTROL / Apply | **불변 / 금지** |

---

## 현황 요약 (추정)

개발 ~85% · Paper ~85% · LIVE ~58% · 운영 **NOT READY** · LIVE **NOT APPROVED**

## Next Gate

1. Technical VALID cohort **≈50** 재리뷰 (TP candidate 재평가; 자동 변경 금지)  
2. News A/B 자연 누적 → `NEWS_AB_REVIEW_READY`  
3. Scanner/Gate/TP/SL production 적용 · LIVE — 별도 승인  

→ [ROADMAP.md](ROADMAP.md)
