# CURRENT_WORK

**역할:** 현재 진행 중인 작업만 기록한다. 과거 완료 목록을 나열하지 않는다.  
**최종 갱신:** 2026-08-15

---

## Current Phase

**STEP M4-C — LIVE/ARM Single-Mount (OPTION A)** — baseline 커밋 (`LIVE_CONTROL_SINGLE_MOUNT_READY_WITH_LIMITATIONS`)

| 항목 | 값 |
|------|-----|
| Branch | `release/v1.1.0` |
| Baseline | M4-B `e045c63` |
| canonical | `/admin/accounts` (panel full) |
| secondary | `/admin/upbit` (READ summary + link) |
| panel mounts | 2 → **1** |
| 금지 | risk page · backend · accounts panel 수정 · LIVE 실행 |
| Evidence | [audit/MENU_M4C_LIVE_CONTROL_SINGLE_MOUNT.md](audit/MENU_M4C_LIVE_CONTROL_SINGLE_MOUNT.md) |
| commit | **본 커밋으로 baseline 고정** (push 없음) |

병렬 트랙 (본 STEP과 혼합 금지):

- Technical Shadow: VALID≈50 재리뷰 대기 · TP apply **금지**
- News A/B: `NEWS_AB_SAMPLE_ACCUMULATING`

---

## 현황 요약 (추정)

개발 ~85% · Paper ~85% · LIVE ~58% · 운영 **NOT READY** · LIVE **NOT APPROVED**

## Next Gate

1. **M4-C commit** 승인 후 선별 커밋 · **Risk LIVE duplicate (M4-C2)** 는 별도  
2. Technical VALID cohort **≈50** 재리뷰 (자동 변경 금지)  
3. News A/B 자연 누적 → `NEWS_AB_REVIEW_READY`  

→ [ROADMAP.md](ROADMAP.md)
