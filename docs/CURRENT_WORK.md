# CURRENT_WORK

**역할:** 현재 진행 중인 작업만 기록한다. 과거 완료 목록을 나열하지 않는다.  
**최종 갱신:** 2026-08-15

---

## Current Phase

**STEP M5-B — Technical SECTION_REORGANIZE** — baseline 커밋 (`TECHNICAL_SECTION_REORGANIZE_READY_WITH_LIMITATIONS`)

| 항목 | 값 |
|------|-----|
| Branch | `release/v1.1.0` |
| Baseline | M5-A `285b521` · M5-B0 SECTION_REORGANIZE |
| 변경 | `UpbitOpportunityScannerPanel` UI 순서만 (Scanner→Candidates→Shadow→Evaluate→Cohort) |
| 미변경 | API/mutation/policy · component split 없음 |
| Evidence | [audit/MENU_M5B_TECHNICAL_SECTION_REORGANIZE.md](audit/MENU_M5B_TECHNICAL_SECTION_REORGANIZE.md) |
| commit | **본 커밋으로 baseline 고정** (push 없음 · Ambiguous/Collector/risk WIP 잔여 WT) |

병렬 트랙 (본 STEP과 혼합 금지):

- Technical Shadow: VALID≈50 재리뷰 · TP apply **금지**
- News A/B: `NEWS_AB_SAMPLE_ACCUMULATING`
- Ambiguous/Collector/risk WIP — 별도 선별

---

## 현황 요약 (추정)

개발 ~85% · Paper ~85% · LIVE ~58% · 운영 **NOT READY** · LIVE **NOT APPROVED**

## Next Gate

1. **M5-C0** News Pipeline tab PRECHECK (**승인 후**)  
2. Technical VALID cohort **≈50** 재리뷰 (자동 변경 금지)  
3. News A/B 자연 누적 → `NEWS_AB_REVIEW_READY`  

→ [ROADMAP.md](ROADMAP.md)
