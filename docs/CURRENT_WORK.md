# CURRENT_WORK

**역할:** 현재 진행 중인 작업만 기록한다. 과거 완료 목록을 나열하지 않는다.  
**최종 갱신:** 2026-08-15

---

## Current Phase

**STEP M4-C2-APPLY — Risk LIVE/ARM Control Single-Surface** — baseline 커밋 (`RISK_LIVE_CONTROL_SINGLE_SURFACE_READY_WITH_LIMITATIONS`)

| 항목 | 값 |
|------|-----|
| Branch | `release/v1.1.0` |
| Baseline | M4-C `85c3552` |
| 변경 | Risk LIVE/ARM mutation UI 제거 · status+accounts 링크 |
| 유지 | Kill · risk settings · limits · account_paused |
| Evidence | [audit/MENU_M4C2_RISK_LIVE_CONTROL_CLEANUP.md](audit/MENU_M4C2_RISK_LIVE_CONTROL_CLEANUP.md) |
| commit | **본 커밋으로 baseline 고정** (push 없음 · risk WIP 잔여 working tree) |

병렬 트랙 (본 STEP과 혼합 금지):

- Technical Shadow: VALID≈50 재리뷰 대기 · TP apply **금지**
- News A/B: `NEWS_AB_SAMPLE_ACCUMULATING`

---

## 현황 요약 (추정)

개발 ~85% · Paper ~85% · LIVE ~58% · 운영 **NOT READY** · LIVE **NOT APPROVED**

## Next Gate

1. Risk page WIP split 후 M4-C2 선별 commit (**승인 후**)  
2. Technical VALID cohort **≈50** 재리뷰 (자동 변경 금지)  
3. News A/B 자연 누적 → `NEWS_AB_REVIEW_READY`  

→ [ROADMAP.md](ROADMAP.md)
