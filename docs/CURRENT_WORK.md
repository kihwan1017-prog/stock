# CURRENT_WORK

**역할:** 현재 진행 중인 작업만 기록한다. 과거 완료 목록을 나열하지 않는다.  
**최종 갱신:** 2026-08-14

---

## Current Phase

**STEP N10 — UPBIT News A/B Natural Sample Accumulation & Coverage Decision** (`NEWS_AB_SAMPLE_ACCUMULATING`)

| 항목 | 값 |
|------|-----|
| Branch | `release/v1.1.0` |
| Mode | 관찰/coverage 판정 (정책·threshold·look-ahead **미변경**) |
| MATCHED | **1/20** completed (자연, experiment_id=16 KRW-BTC) |
| NO_NEWS | **13/20** completed |
| Top-N Snapshot | **OBSERVE_MORE** (A∧B 충족, C source-gap **미증명** → 구현 금지) |
| CONTROL | Scanner/Shadow/Cohort/Trading **불변** |
| Apply | **금지** |

---

## 현황 요약 (추정)

개발 ~85% · Paper ~85% · LIVE ~58% · 운영 **NOT READY** · LIVE **NOT APPROVED**

## Next Gate

1. **자연 누적 지속** — MATCHED_COMPLETED≥20 ∧ NO_NEWS_COMPLETED≥20 ∧ mismatch=0 → `NEWS_AB_REVIEW_READY`  
2. Top-N Snapshot은 A+B+C 증명 시에만 별도 STEP 설계·구현  
3. Scanner/Gate production 적용 금지 · LIVE 별도 승인  

→ [ROADMAP.md](ROADMAP.md)
