# CURRENT_WORK

**역할:** 현재 진행 중인 작업만 기록한다. 과거 완료 목록을 나열하지 않는다.  
**최종 갱신:** 2026-08-14

---

## Current Phase

**STEP N7 완료 — UPBIT News Combined Experiment Observation & Sample Accumulation** (`NEWS_AB_SAMPLE_ACCUMULATING`)

| 항목 | 값 |
|------|-----|
| Branch | `release/v1.1.0` |
| Last STEP | N7 sample accumulation / diagnostics |
| Sample | MATCHED_done **0**/20 · NO_NEWS_done **12**/20 |
| Root cause | **MIXED** (TIMESTAMP_OVERLAP_LOW + SOURCE_COVERAGE_LOW + EXPERIMENT_SOURCE_TOO_NARROW) |
| Top N history | **not reusable** (HOLD 미저장) |
| Scheduler | `UPBIT_NEWS_COMBINED_SHADOW_ENABLED=false` (default OFF) |
| N4/N5 | 자동 ON **금지** (유지 OFF) |
| CONTROL | Shadow/Scanner/Cohort mutation **0** |
| LLM | **0** |
| LIVE | fail-closed 유지 |

---

## 현황 요약 (추정)

개발 ~85% · Paper ~85% · LIVE ~58% · 운영 **NOT READY** · LIVE **NOT APPROVED**

## Next Gate

1. **STEP N8** — 사용자 승인 후에만 (표본 누적·N4/N5 수집 승인 검토; Scanner/Gate production 적용 금지)  
2. Cohort milestone READY  
3. LIVE 별도 승인  

→ [ROADMAP.md](ROADMAP.md)
