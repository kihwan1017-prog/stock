# TECHNICAL OBSERVATION DATA REVIEW

**MODE:** READ-ONLY ONLY  
**Date:** 2026-08-15  
**Scope:** Discovery cohort timeout / observation contract / data quality — **not** TP re-optimization  
**Script:** `scripts/technical_observation_data_review.py`  
**JSON:** [TECHNICAL_OBSERVATION_DATA_REVIEW.json](TECHNICAL_OBSERVATION_DATA_REVIEW.json)

---

## 1. 최종 판정

**MULTIPLE_ISSUES_REQUIRE_REVIEW**

| 축 | 판정 |
|----|------|
| Timeout 주원인 | **정상 60m path에서 TP/SL 미도달** (MFE&lt;2% = 40/47) |
| 부차 이슈 | **minute bar coverage 불완전** (STRICT 중 coverage&lt;0.8 = 19/47; timeout B=16/43) |
| Observation window | **MIXED** — contract는 명확한 60m이나 일부 symbol은 bar 결손 |
| Evaluator contract | **CLEAR** — 모호성으로 timeout이 만들어진 것은 아님 |
| TP | **KEEP_6** / 신규 TP 제안 없음 |

---

## 2. Sample reconciliation

| 지표 | 과거 cohort review | Candidate definition (cutoff) | 본 STEP |
|------|-------------------|-------------------------------|---------|
| COMPLETED | 51 | 50 | 50 (cutoff) / DB 전체 51 |
| STRICT_VALID | 48 | 47 | 47 |
| PAIRED_VALID_N | — | 47 | **47** |

**SAMPLE_RECONCILIATION = PASS** (데이터 오류 아님 · cutoff 경계의 정상 차이)

### Excluded 1 row

| 항목 | 값 |
|------|-----|
| shadow_id | **51** |
| symbol | KRW-ONG |
| completed_at | `2026-08-14T23:25:40.424807+00:00` |
| cutoff | `2026-08-14T23:25:40.424Z` (= `.424000`) |
| 이유 | **마이크로초가 cutoff보다 807µs 큼** → `completed_at <= cutoff` 실패 |
| 기존 51/48 포함 | 예 (전체 COMPLETED·STRICT에 포함) |
| 데이터 오류 | **아니오** — 정상 cutoff 경계 |

Return-missing under cutoff (STRICT 제외): shadow_id **4, 6, 10** (기존과 동일 3건).

**LOOK_AHEAD_VIOLATION = 0** (cutoff 이후 COMPLETED / shadow_id&gt;51 미사용).

---

## 3–6. Counts

| # | 항목 | 값 |
|---|------|-----|
| 3 | COMPLETED (cutoff) | **50** |
| 4 | STRICT_VALID | **47** |
| 5 | PAIRED_VALID_N | **47** |
| 6 | excluded | shadow **51** (위) |

---

## 7. Observation contract (코드)

| 항목 | 내용 | 위치 |
|------|------|------|
| Windows | 5 / 15 / 30 / **60** 분 | `constants.EVALUATION_WINDOWS_MINUTES` |
| Start | `detected_at` | `evaluator._compute_payload` |
| Terminal / max duration | `detected_at + 60m` | 동일 |
| r60 / return_60m | target = detected+60m 에서의 **last_known_price_at_target_v1** return | `candle_path.observe_windows` · `DEFAULT_MAX_PRIOR_LAG_SECONDS=180` |
| Bar interval | **1m** (`market.candle_minute`) | `ensure_shadow_minute_bars` |
| Min bars for COMPLETED | 명시적 “N bars” 최소치 없음 — **window별 OK observation** + `evaluated_*m_at` stamp | `evaluator.py` ~197–285 |
| COMPLETED | `evaluated_60m_at` set + status ACTIVE → COMPLETED, `completed_at=now` | `evaluator.py` 279–285 |
| TP/SL | 1m high/low path; same-candle → **SL conservative** | `candle_path.compute_tp_sl` |
| Timeout (본 분석 정의) | 60m path 내 TP/SL `first_hit` 없음 → **마지막 in-window close**로 exit return | counterfactual (candidate review와 동일) |
| MFE/MAE | max(high)/min(low) vs `entry_price`; missing bar skip; **수수료·슬리피지 없음** | `candle_path.compute_mfe_mae` |

**주의:** `completed_at - detected_at`는 **평가 완료 지연(lag)** 이며 observation window 길이가 아님. Window는 항상 detected…+60m.

---

## 8. Observation duration (completion lag)

STRICT_VALID `completed_at - detected_at` (분):

| min | p25 | median | p75 | max |
|-----|-----|--------|-----|-----|
| 60.0 | 63.0 | 63.0 | 171.0 | **1431.0** |

- 다수는 ~63분(60m 성숙 + 스케줄 여유).
- 장시간(예: 49 GRVT ~1236m, 50 SHIB ~1431m) = **캔들 확보/평가 지연**이지 window 단축이 아님.
- **중간 종료로 window를 자른 흔적 없음** (contract상 terminal 고정).

---

## 9. Bar coverage

Expected slots ≈ **61** (floor(detected)…terminal inclusive minute count).

| | coverage ratio | actual bars |
|--|----------------|-------------|
| min | 0.3934 | 24 |
| p25 | 0.6721 | 41 |
| median | 0.9016 | 55 |
| p75 | 1.0 | 61 |
| max | 1.0 | 61 |
| mean | 0.8246 | 50.3 |

coverage &lt; 0.8: **19/47**. 신규 threshold 미도입(보고만).

---

## 10–13. Timeout

| 항목 | 값 |
|------|-----|
| Timeout count | **43 / 47** |
| Timeout rate | **91.5%** |

### Classification (TP6 counterfactual)

| Class | count | % of 43 | 대표 shadow_id |
|-------|------:|--------:|----------------|
| **A** 정상 observation 종료 (cov≥0.8, TP/SL 미도달) | 27 | 62.8% | 1, 2, 3, 5, 7 |
| **B** candle/bar 부족 (cov&lt;0.8) | 16 | 37.2% | 8, 13, 14, 15, 20 |
| C 부분 window 누락 | 0 | — | (B에 흡수) |
| D 수집 지연 | 0 | — | completion lag는 duration에만 반영 |
| E symbol 중단/비활성 | 0 | — | 증거 없음(얇은 분봉만) |
| F evaluator 종료 규칙으로 조기 timeout | 0 | — | COMPLETED≠timeout |
| G 기타 | 0 | — | |

### Timeout exit return

| mean | median | + rate | − rate | zero rate |
|-----:|-------:|-------:|-------:|----------:|
| 0.1385 | **0.0** | 0.4419 | 0.3953 | 0.1628 |

**median=0 원인:** timeout 43건 중 **정확히 0인 7건** + 좌우 대칭에 가까운 소폭 수익/손실 분포.  
FALLBACK/missing으로 0을 채운 흔적 **없음** (아래 zero 분류).

---

## 14–15. Zero returns (PAIRED 47)

| 항목 | 값 |
|------|-----|
| exit return == 0 | **7 / 47** (14.9%) |
| 분류 | **REAL_ZERO × 7** |
| ROUNDING / NO_BAR / MISSING_PRICE / FALLBACK_ZERO | **0** |

ids: 5 ONDO, 21 ETH, 23 SOL, 28 KAITO, 35 ID, 43 CAP, 44 DOS.  
모두 TIMEOUT · last close == entry · **stored `return_60m_pct`도 0**과 일치.  
MFE&gt;0인 건도 있음 → 경로상 올랐다 돌아와 entry 마감.

**성능 왜곡 위험:** LOW (fallback zero 아님). 다만 median 지표는 zero 비중(≈15%)에 민감.

---

## 16–17. MFE / MAE validity

| 확인 | 결과 |
|------|------|
| Bar 범위 | `floor_minute(detected)` … `end_at` (본 리뷰: full `detected+60m`) |
| Missing | skip (합성 봉 없음) |
| First/last | 범위 내 completed 1m bar 포함 |
| Entry | `row.entry_price` |
| Fee/slippage | **미포함** |
| 재정의 | **하지 않음** |

본 리뷰 STRICT mean MFE ≈ **0.78%**, mean MAE ≈ **−0.68%** 근처(기존 보고와 정합).  
**전체 intended 60m window 기준**이나, bar 결손 시 그 구간은 경로에 미반영.

---

## 18–22. MFE buckets (TP hit rarity)

| Bucket | count | rate |
|--------|------:|-----:|
| MFE &lt; 2% | **40** | **85.1%** |
| 2% ≤ MFE &lt; 3% | 2 | 4.3% |
| 3% ≤ MFE &lt; 4% | 3 | 6.4% |
| 4% ≤ MFE &lt; 6% | 1 | 2.1% |
| MFE ≥ 6% | **1** | 2.1% |

→ TP6 hit 1/47은 “TP만 높다”가 아니라 **대부분의 경로가 +2% 고점조차 못 찍음**.  
Window가 짧아서가 아니라(contract 60m), **관측된 가격 진폭 자체가 작음** + 일부 **bar 결손**.

유일한 ≥6%: shadow **49 KRW-GRVT** (coverage 0.39 · TP hit · 이상치 성격).

---

## 23. Symbol concentration

Timeout은 다수 symbol에 분산. **단일 symbol 독점 아님.**

| symbol | n | timeout_n | timeout_rate | zero_n | mean MFE | mean MAE |
|--------|--:|----------:|-------------:|-------:|---------:|---------:|
| KRW-RE | 5 | 4 | 0.80 | 0 | 0.33 | −1.58 |
| KRW-SOL | 4 | 4 | 1.00 | 1 | 0.21 | −0.23 |
| KRW-BTC | 4 | 4 | 1.00 | 0 | 0.14 | −0.23 |
| KRW-WLD | 4 | 4 | 1.00 | 0 | 0.61 | −1.14 |
| … | | | | | | |
| **KRW-GRVT** | 1 | 0 | 0 | 0 | **10.09** | +8.45 |

GRVT는 timeout 집중이 아니라 **희귀 TP + 낮은 bar coverage** 이상치.

---

## 24. Candle / data-quality anomalies

| 이상 | count | 해석 |
|------|------:|------|
| duplicate / out-of-order | 0 | — |
| price ≤ 0 | 0 | — |
| high &lt; low | 0 | — |
| entry 이전 candle | 40 | **의도적** `detected−1m` 로드 패딩 |
| observation end 이후 | 0 | — |
| missing interval &gt;1m (gap events) | 299 | 얇은/누락 분봉 누적 |
| timezone mismatch | 0 | UTC 일관 |

---

## 25. Observation window sufficiency

**MIXED**

- Contract 60m는 Technical path 평가에 **형식상 충분**하고, timeout의 다수(A)는 그 안에서 진폭이 작아 설명됨.
- 동시에 STRICT의 ~40%는 coverage&lt;0.8로 **데이터 불완전** → “window만 늘리면 해결”로 단정 불가.
- 이번 STEP에서 window **변경 안 함**.

---

## 26. Evaluator contract status

**CLEAR_NO_AMBIGUITY_FOR_60M_PATH**

COMPLETED = 60m window finalization stamp.  
Counterfactual “timeout” = TP/SL 미히트.  
정책 변경·코드 수정 없음.

---

## 27–30. Policy / News

| # | 항목 | 값 |
|---|------|-----|
| 27 | LOOK_AHEAD_VIOLATION | **0** |
| 28 | CURRENT_TP | **6.0%** |
| 29 | TP recommendation | **KEEP_6** (신규 TP 값 제안 금지) |
| 30 | News A/B | MATCHED **2/20** · NO_NEWS **22/20** · **NEWS_AB_SAMPLE_ACCUMULATING** (분석 미사용) |

---

## 31–35. Mutations

| 항목 | 값 |
|------|-----|
| production mutation | **0** |
| DB mutation | **0** |
| TradingOrder/Outbox | **0** |
| LIVE/ARM/Scheduler | **0** |
| commit/push | **0** (금지 준수) |

---

## 36. Limitations

- Bar coverage는 DB `candle_minute` 스냅샷 기준; Upbit 원장 재동기화는 하지 않음.
- Timeout class B의 “부족”은 **expected 61 slots 대비 존재 분봉** 휴리스틱(기존 contract에 고정 coverage threshold 없음).
- stored `return_60m`와 counterfactual TP/SL exit return은 정의가 다름(본 STEP는 후자 중심).
- News A/B 미포함.

---

## 37. Next STEP (exactly one)

**TECHNICAL OBSERVATION ROOT CAUSE REVIEW**

(판정 `MULTIPLE_ISSUES_REQUIRE_REVIEW`에 대응 — 소진폭 timeout vs bar 결손 기여도 분리·우선순위.)

---

## STOP

TP/SL 변경 · 새 candidate · OOS · production/DB/LIVE mutation · commit/push — **전부 금지·미실행**.
