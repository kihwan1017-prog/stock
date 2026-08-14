# CURRENT_WORK

**역할:** 현재 진행 중인 작업만 기록한다. 과거 완료 목록을 나열하지 않는다.  
**최종 갱신:** 2026-08-14

---

## Current Phase

**STEP M3-B — Promote Hidden Active Strategy Workflows** — baseline 커밋 (`MENU_M3B_READY_WITH_LIMITATIONS`)

| 항목 | 값 |
|------|-----|
| Branch | `release/v1.1.0` |
| Baseline | M3-A `bab25d36577f817138830fbb13e78e6af6e401c9` |
| 범위 | Strategy Request / Draft / Portfolio Validation **사이드바 노출만** |
| 금지 | route·page·API·AuthGuard·신규 permission 키·User 12→8 |
| Evidence | [audit/MENU_M3B_HIDDEN_WORKFLOW_PROMOTION.md](audit/MENU_M3B_HIDDEN_WORKFLOW_PROMOTION.md) |
| commit | **본 커밋으로 baseline 고정** (push 없음) |

병렬 트랙 (본 STEP과 혼합 금지):

- Technical Shadow: VALID≈50 재리뷰 대기 · TP apply **금지**
- News A/B: `NEWS_AB_SAMPLE_ACCUMULATING`

---

## 현황 요약 (추정)

개발 ~85% · Paper ~85% · LIVE ~58% · 운영 **NOT READY** · LIVE **NOT APPROVED**

## Next Gate

1. **M4** — Operations Consolidation (**M3-B 승인 후**, 자동 진행 금지)  
2. Technical VALID cohort **≈50** 재리뷰 (자동 변경 금지)  
3. News A/B 자연 누적 → `NEWS_AB_REVIEW_READY`  

→ [ROADMAP.md](ROADMAP.md)
