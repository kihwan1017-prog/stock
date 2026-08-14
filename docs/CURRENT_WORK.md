# CURRENT_WORK

**역할:** 현재 진행 중인 작업만 기록한다. 과거 완료 목록을 나열하지 않는다.  
**최종 갱신:** 2026-08-15

---

## Current Phase

**STEP M4-B — Admin Operations Menu Regroup** — baseline 커밋 (`MENU_M4B_READY_WITH_LIMITATIONS`)

| 항목 | 값 |
|------|-----|
| Branch | `release/v1.1.0` |
| Baseline | M4-A `62bd783` |
| 범위 | Admin Sidebar 운영 메뉴 regroup만 |
| 금지 | page/route/CONTROL/API · User UI · UBA · Strategy 위치 |
| Evidence | [audit/MENU_M4B_OPERATIONS_MENU_REGROUP.md](audit/MENU_M4B_OPERATIONS_MENU_REGROUP.md) |
| commit | **본 커밋으로 baseline 고정** (push 없음) |
| top-level | 10 → **11** (M2 target 9 — 억지 병합 안 함) |

병렬 트랙 (본 STEP과 혼합 금지):

- Technical Shadow: VALID≈50 재리뷰 대기 · TP apply **금지**
- News A/B: `NEWS_AB_SAMPLE_ACCUMULATING`

---

## 현황 요약 (추정)

개발 ~85% · Paper ~85% · LIVE ~58% · 운영 **NOT READY** · LIVE **NOT APPROVED**

## Next Gate

1. **M4-C** — LIVE/ARM control canonicalization precheck (**M4-B 승인 후**, 자동 진행 금지)  
2. Technical VALID cohort **≈50** 재리뷰 (자동 변경 금지)  
3. News A/B 자연 누적 → `NEWS_AB_REVIEW_READY`  

→ [ROADMAP.md](ROADMAP.md)
