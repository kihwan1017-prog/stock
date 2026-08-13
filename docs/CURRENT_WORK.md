# CURRENT_WORK

**역할:** 현재 진행 중인 작업만 기록한다. 과거 완료 목록을 나열하지 않는다.  
**최종 갱신:** 2026-08-14

---

## Current Phase

**STEP N4 완료 — UPBIT AI News Analysis v0** (`READY_WITH_LIMITATIONS`)

| 항목 | 값 |
|------|-----|
| Branch | `release/v1.1.0` |
| Last STEP | N4 AI News Analysis (`upbit_news_analysis_v1`) |
| 결과 성격 | **INFORMATIONAL ONLY** (주문/Gate/Scanner 비연동) |
| 입력 | TRUSTED mapping만 · 1 Article = 1 AI Call |
| Scheduler | `UPBIT_NEWS_AI_ANALYSIS_ENABLED=false` (DEFAULT OFF) |
| Cohort | `SAMPLE_ACCUMULATING` 유지 |
| Scanner | **SHADOW_ONLY** |
| LIVE | all live flags **false** |

---

## 현황 요약 (추정)

개발 ~83% · Paper ~85% · LIVE ~58% · 운영 **NOT READY** · LIVE **NOT APPROVED** · Paper 무인 **조건부**

## Next Gate

1. **STEP N5** — 사용자 승인 후에만 (News Signal / Combined Score / Scanner 연동 금지까지 N4 STOP)  
2. Cohort 자동 축적 → milestone READY  
3. LIVE는 별도 승인  

→ [ROADMAP.md](ROADMAP.md)
