# CURRENT_WORK

**역할:** 현재 진행 중인 작업만 기록한다. 과거 완료 목록을 나열하지 않는다.  
**최종 갱신:** 2026-08-13

---

## Current Phase

**Ops continuity — Shadow cohort milestone watch**

| 항목 | 값 |
|------|-----|
| Branch | `release/v1.1.0` |
| Last ops STEP | Shadow Cohort Review Milestone Watch |
| Status | `SAMPLE_ACCUMULATING` (자동 관찰) |
| Gate | VALID≥30 ∧ new-policy MATCH≥10 ∧ mismatch=0 → `SHADOW_COHORT_30_REVIEW_READY` (1회 Audit/Telegram) |
| Policy | **변경 없음** (threshold/ranking/AI/SL/TP 유지) |
| Scanner | **SHADOW_ONLY** · 900s · Evaluator 180s |
| LIVE | all live flags **false** |

---

## 현황 요약 (추정)

개발 ~82% · Paper ~85% · LIVE ~58% · 운영 **NOT READY** · LIVE **NOT APPROVED** · Paper 무인 **조건부**

## Next Gate

1. Cohort 자동 축적 → milestone READY 알림 대기  
2. P0 잔여 워킹트리 정리·커밋 패키지  
3. LIVE는 별도 승인·ARM·실계좌 Gate  

→ [ROADMAP.md](ROADMAP.md)
