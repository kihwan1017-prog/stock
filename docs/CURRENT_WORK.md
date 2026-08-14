# CURRENT_WORK

**역할:** 현재 진행 중인 작업만 기록한다. 과거 완료 목록을 나열하지 않는다.  
**최종 갱신:** 2026-08-14

---

## Current Phase

**STEP M4-A — READ-ONLY Operations Status / Dashboard Consolidation** — baseline 커밋 (`MENU_M4A_READY_WITH_LIMITATIONS`)

| 항목 | 값 |
|------|-----|
| Branch | `release/v1.1.0` |
| Baseline | M3-B `90bbaef` |
| 범위 | Admin 운영 화면 라벨·교차링크·READ summary |
| 금지 | CONTROL 이동 · UBA 패널 단일 마운트 · 메뉴 그룹 재배치 · API/backend |
| Evidence | [audit/MENU_M4A_OPERATIONS_READONLY_CONSOLIDATION.md](audit/MENU_M4A_OPERATIONS_READONLY_CONSOLIDATION.md) |
| commit | **본 커밋으로 baseline 고정** (push 없음) |
| deferred | `/admin/risk` heading/links — 기존 LIVE/ARM WIP와 분리 불가, 이번 커밋 제외 |

병렬 트랙 (본 STEP과 혼합 금지):

- Technical Shadow: VALID≈50 재리뷰 대기 · TP apply **금지**
- News A/B: `NEWS_AB_SAMPLE_ACCUMULATING`

---

## 현황 요약 (추정)

개발 ~85% · Paper ~85% · LIVE ~58% · 운영 **NOT READY** · LIVE **NOT APPROVED**

## Next Gate

1. **M4-B** — Operations 메뉴 재배치 (**M4-A 승인 후**, 자동 진행 금지)  
2. Technical VALID cohort **≈50** 재리뷰 (자동 변경 금지)  
3. News A/B 자연 누적 → `NEWS_AB_REVIEW_READY`  

→ [ROADMAP.md](ROADMAP.md)
