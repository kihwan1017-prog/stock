# CURRENT_WORK

**역할:** 현재 진행 중인 작업만 기록한다. 과거 완료 목록을 나열하지 않는다.  
**최종 갱신:** 2026-08-15

---

## Current Phase

**STEP M5-C — News Pipeline SECTION_REORGANIZE** — baseline 커밋 (`NEWS_PIPELINE_SECTION_REORGANIZE_READY_WITH_LIMITATIONS`)

| 항목 | 값 |
|------|-----|
| Branch | `release/v1.1.0` |
| 변경 | NewsCollector UI N2→N3→N4→N5 · action 분리 |
| Evidence | [audit/MENU_M5C_NEWS_PIPELINE_SECTION_REORGANIZE.md](audit/MENU_M5C_NEWS_PIPELINE_SECTION_REORGANIZE.md) |
| commit | **본 커밋으로 baseline 고정** (push 없음) |
| residual | NewsCollector **rowKey WIP**는 WT에 재적용 (commit 제외) |

병렬 트랙:

- Technical cohort 재리뷰 · TP apply **금지**
- News A/B 누적
- Ambiguous/risk/rowKey WIP — 별도 선별

---

## 현황 요약 (추정)

개발 ~85% · Paper ~85% · LIVE ~58% · 운영 **NOT READY** · LIVE **NOT APPROVED**

## Next Gate

1. **M5-D0** A/B Experiment tab PRECHECK (**승인 후**)  
2. Technical VALID≈50 재리뷰  
3. NewsCollector rowKey WIP 별도 처리  

→ [ROADMAP.md](ROADMAP.md)
