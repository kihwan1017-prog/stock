# TECHNICAL OBSERVATION ROOT CAUSE REVIEW

**MODE:** READ-ONLY ONLY  
**Date:** 2026-08-15  
**Purpose:** Separate **MARKET_LOW_MOVE** vs **BAR-COVERAGE DEFICIENCY**  
**Script:** `scripts/technical_observation_root_cause_review.py`  
**JSON:** [TECHNICAL_OBSERVATION_ROOT_CAUSE_REVIEW.json](TECHNICAL_OBSERVATION_ROOT_CAUSE_REVIEW.json)

**Diagnostic split:** coverage threshold **0.8** = analysis only · **not** production policy.

---

## 1. 최종 판정

**MIXED_MARKET_AND_DATA**

| 축 | 판정 |
|----|------|
| MARKET_LOW_MOVE | **SUPPORTED** |
| DATA_COVERAGE_ISSUE | **SUPPORTED** |
| COVERAGE_IMPACT | **HIGH** (performance deltas material) |
| Policy implication | **KEEP_6_AND_FIX_DATA_FIRST** |
| CURRENT_TP | **6.0%** (변경 없음) |
| Next | **TECHNICAL BAR COVERAGE REMEDIATION DESIGN** |

---

## 2–3. Dual-axis verdict

### MARKET_LOW_MOVE = SUPPORTED

- High-coverage (n=28) 중 **MFE&lt;2% = 23/28 (82%)**
- 질문 *“충분한 bar coverage에서도 MFE&lt;2%가 지배적인가?”* → **YES**

### DATA_COVERAGE_ISSUE = SUPPORTED

- Low-coverage n=**19/47** (40%)
- Group L mean coverage **0.63**, median **0.64**
- Group L mean exit return **−0.16** vs Group H **+0.22** (부호 반대)

---

## 4–8. Group H / L

| | Group H (cov≥0.8) | Group L (cov&lt;0.8) | FULL |
|--|------------------:|-------------------:|-----:|
| n | **28** | **19** | **47** |
| coverage mean / median | 0.96 / 0.98 | 0.63 / 0.64 | 0.82 / 0.90 |
| timeout n / rate | 27 / **96.4%** | 16 / 84.2% | 43 / 91.5% |
| TP hit n / rate | 0 / **0%** | 1 / 5.3% | 1 / 2.1% |
| SL exit n / rate | 1 / 3.6% | 2 / 10.5% | 3 / 6.4% |
| mean / median exit return | **0.22 / 0.09** | **−0.16 / −0.45** | 0.06 / 0 |
| positive / loss / zero | 0.54 / 0.25 / 0.21 | 0.26 / 0.68 / 0.05 | — |
| mean / median MFE | 0.88 / 0.28 | 0.61 / 0.11 | — |
| mean / median MAE | −0.65 / −0.37 | −0.73 / −1.24 | — |

HIGH_COVERAGE_N = **28** · LOW_COVERAGE_N = **19** · FULL_N = **47**

---

## 9. 2×2 LOW-MOVE × COVERAGE

| Cell | n | % | mean ret | median ret | timeout rate |
|------|--:|--:|---------:|-----------:|-------------:|
| **A** cov≥0.8 ∧ MFE&lt;2% | **23** | 48.9% | −0.09 | 0 | 0.96 |
| **B** cov≥0.8 ∧ MFE≥2% | 5 | 10.6% | 1.65 | 1.44 | 1.00 |
| **C** cov&lt;0.8 ∧ MFE&lt;2% | **17** | 36.2% | −0.83 | −0.67 | 0.88 |
| **D** cov&lt;0.8 ∧ MFE≥2% | 2 | 4.3% | 5.49 | 5.49 | 0.50 |

**Sufficient coverage에서도 low-move 지배: YES** (A = 23/28 of H).

---

## 10. High-coverage MFE buckets (diagnostic)

| Bucket | count | rate |
|--------|------:|-----:|
| &lt;2% | **23** | **82.1%** |
| 2–3% | 2 | 7.1% |
| 3–4% | 2 | 7.1% |
| 4–6% | 1 | 3.6% |
| ≥6% | **0** | 0% |

TP6 on H: hit **0** · SL **1** · timeout **27** · mean ret **0.22** · median **0.09** · +rate **0.54** · loss **0.25**

---

## 11–12. FULL vs HIGH deltas · COVERAGE_IMPACT

HIGH − FULL:

| Δ | value |
|---|------:|
| mean return | **+0.154** |
| median return | +0.086 |
| positive rate | +0.110 |
| loss rate | **−0.176** |
| mean MFE | +0.109 |
| mean MAE | +0.032 |
| TP hit rate | −0.021 |
| timeout rate | +0.049 |

**COVERAGE_IMPACT = HIGH**  
근거: low-cov 제거 시 mean return이 ~0.06 → ~0.22로 바뀌고 loss rate가 크게 하락.  
즉 coverage 결손은 **timeout 설명의 주원인(소진폭)을 뒤집지 않지만**, 전체 성과 지표를 **유의미하게 왜곡**.

---

## 13–15. Correlations (n=47, 인과 금지)

| pair | Pearson | Spearman |
|------|--------:|---------:|
| coverage ↔ MFE | −0.09 | **0.21** |
| coverage ↔ MAE | −0.13 | **0.36** |
| coverage ↔ exit return | −0.01 | **0.26** |

약한 양의 Spearman — 낮은 coverage일수록 MFE/return이 다소 낮게 관측되는 경향. **인과로 해석하지 않음.**

---

## 16–17. Missing bar position / consecutive gap (Group L only)

| gap class | count |
|-----------|------:|
| DISTRIBUTED_GAP | **11** |
| MIDDLE_GAP | 5 |
| EARLY_GAP | 2 |
| LATE_GAP | **1** |

Consecutive missing (L): min **2** · median **4** · max **9**  
→ 주로 **산발/중반 분포** + 짧은 연속 gap. LATE_GAP=1 → 말단 전용 왜곡은 **소수**.

---

## 18. Data source root-cause matrix

| locus | verdict | ref / note |
|-------|---------|------------|
| candle source | **CONFIRMED_CAUSE** | gaps = absent `market.candle_minute` |
| persistence | **CONFIRMED_CAUSE** | expected minute slots missing in DB |
| fetch range | **POSSIBLE** | `detected..min(now, +60m)` |
| pagination | **POSSIBLE** | `minute_collector` count=200, max_pages=100 |
| API limit | **POSSIBLE** | sync path; API not called this pass |
| retry | **NOT_SUPPORTED** | no evidence |
| rate limit | **POSSIBLE** | unconfirmed |
| scheduler delay | **POSSIBLE** | lag exists; corr weak |
| timezone | **NOT_SUPPORTED** | UTC consistent |
| symbol availability | **POSSIBLE** | multi-symbol thinness |
| evaluator fetch timing | **POSSIBLE** | COMPLETED with partial intermediate bars |

---

## 19. Evaluation lag vs coverage

| | Pearson | Spearman |
|--|--------:|---------:|
| lag ↔ coverage | −0.34 | **−0.15** |
| lag ↔ missing_n | +0.34 | +0.15 |

**늦게 평가될수록 coverage가 나쁜가?** → **INCONCLUSIVE**  
(피어슨은 이상치 lag에 민감, 스피어만 약함.)

---

## 20–21. Symbol · KRW-GRVT

**SYMBOL_COVERAGE_CONCENTRATION = MEDIUM**  
low-cov top3 (RE+MOVE+WLD) = 9/19 ≈ 47% — 지배적 단일 symbol 아님.

**KRW-GRVT (49):** coverage **0.39** · MFE **10.1%** · TP hit · gap DISTRIBUTED (early/late miss high) · **이상치** (전체 low-move 결론을 뒤집지 않음).

---

## 22. HIGH_COVERAGE TP grid (diagnostic only · 미적용)

| TP | mean exit | median | TP hit rate | loss rate |
|----|----------:|-------:|------------:|----------:|
| 2% | **0.28** | 0.11 | 0.18 | 0.25 |
| 3% | **0.35** | 0.11 | 0.11 | 0.25 |
| 4% | 0.22 | 0.09 | 0.00 | 0.25 |
| 6% | 0.22 | 0.09 | 0.00 | 0.25 |

**HIGH_COVERAGE_CANDIDATE_RESULT = CANDIDATE_DIRECTION_CHANGED**  
(고coverage n=28에서 2/3% mean이 6% 상회 — **진단만**. TP 변경·동결·OOS **금지**. 정책은 여전히 **KEEP_6** + 데이터 선행.)

---

## 23–25. Threshold sensitivity (diagnostic)

| thr | n | mean MFE | mean exit | TP6 hit | timeout |
|-----|--:|---------:|----------:|--------:|--------:|
| ≥0.7 | 34 | 0.72 | 0.06 | 0.00 | 0.94 |
| ≥0.8 | 28 | 0.88 | 0.22 | 0.00 | 0.96 |
| ≥0.9 | 25 | 0.83 | 0.20 | 0.00 | 0.96 |

threshold 최적화 **하지 않음**.

---

## 26–28. Policy / News

| 항목 | 값 |
|------|-----|
| CURRENT_TP | **6.0%** |
| policy implication | **KEEP_6_AND_FIX_DATA_FIRST** |
| News A/B | MATCHED **2/20** · NO_NEWS **22/20** · **NEWS_AB_SAMPLE_ACCUMULATING** (미분석) |

---

## 29–34. Safety

| 항목 | 값 |
|------|-----|
| LOOK_AHEAD_VIOLATION | **0** |
| production / DB / TradingOrder / Outbox / create_order / POST /orders | **0** |
| LIVE / ARM / Scheduler | **unchanged** |
| commit / push | **0** |

---

## 35. Limitations

- Coverage는 현재 DB 스냅샷; Upbit 원장 재동기화·API 호출 없음.
- 0.8은 diagnostic split only.
- HIGH_COVERAGE TP 방향 변화는 n=28·진단용 — Discovery 전체 KEEP_6와 병기.
- Gap class는 thirds 휴리스틱.
- News 미포함.

---

## 36. Next STEP (exactly one)

**TECHNICAL BAR COVERAGE REMEDIATION DESIGN**

(판정 `MIXED_MARKET_AND_DATA` 대응 — 설계만, 구현/적용 금지.)

---

## STOP

TP/SL · window · production · DB · OOS · LIVE/ARM/Scheduler · 주문 · commit/push — **전부 미실행**.
