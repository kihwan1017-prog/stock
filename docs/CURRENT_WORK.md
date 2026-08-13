# CURRENT_WORK

**역할:** 현재 진행 중인 작업만 기록한다. 과거 완료 목록을 나열하지 않는다.  
**최종 갱신:** 2026-08-14

---

## Current Phase

**STEP N6 완료 — UPBIT Technical + News Combined Shadow A/B v0** (`READY_WITH_LIMITATIONS`)

| 항목 | 값 |
|------|-----|
| Branch | `release/v1.1.0` |
| Last STEP | N6 Combined Shadow Experiment (`upbit_news_combined_shadow_v1`) |
| CONTROL | Scanner/Shadow/Cohort **불변** |
| EXPERIMENT | `operation.upbit_news_combined_shadow` only |
| LLM | **0** |
| Scheduler | `UPBIT_NEWS_COMBINED_SHADOW_ENABLED=false` |
| Dry run | 5 runs / 8 rows · NEWS_MATCHED 0 · EXCLUDED_ONLY 2 · NO_NEWS 6 |
| Cohort | VALID 25 / MATCH 9 / mismatch 0 (unchanged) |
| LIVE | all live flags **false** |

---

## 현황 요약 (추정)

개발 ~85% · Paper ~85% · LIVE ~58% · 운영 **NOT READY** · LIVE **NOT APPROVED**

## Next Gate

1. **STEP N7** — 사용자 승인 후에만 (N6 누적·검토 후; Scanner/Gate production 적용 금지)  
2. Cohort milestone READY  
3. LIVE 별도 승인  

→ [ROADMAP.md](ROADMAP.md)
