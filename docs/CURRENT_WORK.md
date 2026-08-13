# CURRENT_WORK

**역할:** 현재 진행 중인 작업만 기록한다. 과거 완료 목록을 나열하지 않는다.  
**최종 갱신:** 2026-08-14

---

## Current Phase

**STEP N9 — UPBIT News Pipeline Latency Alignment** (`NEWS_PIPELINE_LATENCY_ALIGNED` / `NEWS_AB_SAMPLE_ACCUMULATING`)

| 항목 | 값 |
|------|-----|
| Branch | `release/v1.1.0` |
| Fix | N4 COMPLETED → N5 event-driven (fail-isolated) · N4 fresh-unprocessed priority |
| N4 interval/batch | **900s / ≤5 유지** (미변경) |
| Look-ahead | **유지** |
| CONTROL | Scanner/Shadow/Cohort/Trading **불변** |
| Apply | **금지** |

---

## 현황 요약 (추정)

개발 ~85% · Paper ~85% · LIVE ~58% · 운영 **NOT READY** · LIVE **NOT APPROVED**

## Next Gate

1. **STEP N10** — 사용자 승인 후에만 (자연 MATCHED 누적·Top-N Snapshot 후보; Scanner/Gate production 적용 금지)  
2. Cohort milestone READY  
3. LIVE 별도 승인  

→ [ROADMAP.md](ROADMAP.md)
