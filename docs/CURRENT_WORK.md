# CURRENT_WORK

**역할:** 현재 진행 중인 작업만 기록한다. 과거 완료 목록을 나열하지 않는다.  
**최종 갱신:** 2026-08-14

---

## Current Phase

**STEP M3-A — LOW-RISK Menu Cleanup** — baseline 커밋 (`MENU_LOW_RISK_CLEANUP_READY_WITH_LIMITATIONS`)

| 항목 | 값 |
|------|-----|
| Branch | `release/v1.1.0` |
| 범위 | sidebar label / 순서 / `/admin/monitoring` 중복 노출 제거만 |
| 금지 | route·page·API·AuthGuard·permission·IA 10→9/12→8 미적용 |
| Evidence | [audit/MENU_LOW_RISK_CLEANUP_M3A.md](audit/MENU_LOW_RISK_CLEANUP_M3A.md) |
| commit | **본 커밋으로 baseline 고정** (push 없음) |

병렬 트랙 (본 STEP과 혼합 금지):

- Technical Shadow: VALID≈50 재리뷰 대기 · TP apply **금지**
- News A/B: `NEWS_AB_SAMPLE_ACCUMULATING`

---

## 현황 요약 (추정)

개발 ~85% · Paper ~85% · LIVE ~58% · 운영 **NOT READY** · LIVE **NOT APPROVED**

## Next Gate

1. **M3-B** — Strategy Request / Draft / Portfolio Validation 메뉴 승격 (**M3-A 승인 후**, 자동 진행 금지)  
2. Technical VALID cohort **≈50** 재리뷰 (자동 변경 금지)  
3. News A/B 자연 누적 → `NEWS_AB_REVIEW_READY`  

→ [ROADMAP.md](ROADMAP.md)
