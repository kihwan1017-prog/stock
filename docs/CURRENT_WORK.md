# CURRENT_WORK

**역할:** 현재 진행 중인 작업만 기록한다. 과거 완료 목록을 나열하지 않는다.  
**최종 갱신:** 2026-08-15

---

## Current Phase

**STEP M5-A — Upbit Hub Tab Shell** — baseline 커밋 (`UPBIT_HUB_TAB_SHELL_READY_WITH_LIMITATIONS`)

| 항목 | 값 |
|------|-----|
| Branch | `release/v1.1.0` |
| 변경 | `/admin/upbit` in-page Tabs · N6→News 뒤 · Ops로 page ops 이동 |
| 미변경 | panel 내부 로직 · Ambiguous/Collector WIP 파일 · API/LIVE |
| Evidence | [audit/MENU_M5A_UPBIT_HUB_TAB_SHELL.md](audit/MENU_M5A_UPBIT_HUB_TAB_SHELL.md) |
| commit | **본 커밋으로 baseline 고정** (push 없음 · Ambiguous/Collector/risk WIP 잔여 WT) |

병렬 트랙 (본 STEP과 혼합 금지):

- Technical Shadow: VALID≈50 재리뷰 대기 · TP apply **금지**
- News A/B: `NEWS_AB_SAMPLE_ACCUMULATING`
- Risk page title/ops-link WIP · Ambiguous/Collector WIP — 별도 선별

---

## 현황 요약 (추정)

개발 ~85% · Paper ~85% · LIVE ~58% · 운영 **NOT READY** · LIVE **NOT APPROVED**

## Next Gate

1. **M5-B** Technical 섹션 정리 (**승인 후** · policy 금지)  
2. Technical VALID cohort **≈50** 재리뷰 (자동 변경 금지)  
3. News A/B 자연 누적 → `NEWS_AB_REVIEW_READY`  

→ [ROADMAP.md](ROADMAP.md)
