# CURRENT_WORK

**역할:** 현재 진행 중인 작업만 기록한다. 과거 완료 목록을 나열하지 않는다.  
**최종 갱신:** 2026-08-13

---

## Current Phase

**STEP N2 완료 — UPBIT News/Notice Collector v0** (`UPBIT_NEWS_NOTICE_COLLECTOR_READY`)

| 항목 | 값 |
|------|-----|
| Branch | `release/v1.1.0` |
| Last STEP | N2 COLLECT→NORMALIZE→DEDUP→STORE |
| News track | **병렬** (Scanner/Shadow/Gate 미연동) |
| Scheduler | 기본 **OFF** (`UPBIT_NOTICE_COLLECTION_ENABLED=false`) |
| Sources | UPBIT official notice + CRYPTO_NEWS(Naver, 기본 OFF) |
| Cohort | `SAMPLE_ACCUMULATING` 유지 (수집과 격리) |
| Scanner | **SHADOW_ONLY** · threshold/TopN 동결 |
| LIVE | all live flags **false** |

---

## 현황 요약 (추정)

개발 ~82% · Paper ~85% · LIVE ~58% · 운영 **NOT READY** · LIVE **NOT APPROVED** · Paper 무인 **조건부**

## Next Gate

1. **STEP N3** — Symbol Mapping (뉴스→종목, AI/Gate 아직 금지)  
2. Cohort 자동 축적 → milestone READY 알림 대기  
3. LIVE는 별도 승인·ARM·실계좌 Gate  

→ [ROADMAP.md](ROADMAP.md)
