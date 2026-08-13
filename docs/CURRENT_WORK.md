# CURRENT_WORK

**역할:** 현재 진행 중인 작업만 기록한다. 과거 완료 목록을 나열하지 않는다.  
**최종 갱신:** 2026-08-14

---

## Current Phase

**STEP N5 완료 — UPBIT News Signal Standardization v0** (`UPBIT_NEWS_SIGNAL_READY`)

| 항목 | 값 |
|------|-----|
| Branch | `release/v1.1.0` |
| Last STEP | N5 News Signal (`upbit_news_signal_v1`) |
| 결과 성격 | **INFORMATIONAL / OBSERVATION ONLY** |
| 입력 | N4 COMPLETED + TRUSTED mapping만 |
| LLM | **0 calls** (deterministic) |
| Scheduler | `UPBIT_NEWS_SIGNAL_ENABLED=false` |
| Cohort | `SAMPLE_ACCUMULATING` (VALID 25 / MATCH 9 / mismatch 0) |
| Scanner | **SHADOW_ONLY** · News Signal 미연동 |
| LIVE | all live flags **false** |

---

## 현황 요약 (추정)

개발 ~84% · Paper ~85% · LIVE ~58% · 운영 **NOT READY** · LIVE **NOT APPROVED** · Paper 무인 **조건부**

## Next Gate

1. **STEP N6** — Combined Shadow 등 (사용자 승인 후만; Scanner/Gate 연결 금지까지 N5 STOP)  
2. Cohort 자동 축적 → milestone READY  
3. LIVE는 별도 승인  

→ [ROADMAP.md](ROADMAP.md)
