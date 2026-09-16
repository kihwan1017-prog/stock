# TECHNICAL TP ANALYSIS REOPEN PRECHECK

**MODE:** READ-ONLY PRECHECK · **no TP recompute · no TP/SL change · no OOS · no DB/policy write**  
**Date:** 2026-08-15  
**HEAD / runtime:** `5c6ad67` · health UP  
**Verdict:** **`TP_ANALYSIS_FREEZE_RELEASE_READY=YES`** · Candidate Search **`TP_CANDIDATE_REANALYSIS_RECOMMENDED`**  
**JSON:** [TECHNICAL_TP_ANALYSIS_REOPEN_PRECHECK.json](TECHNICAL_TP_ANALYSIS_REOPEN_PRECHECK.json)  
**Basis:** [TECHNICAL_COV_D_CLOSEOUT_NO_HISTORICAL_APPLY.md](TECHNICAL_COV_D_CLOSEOUT_NO_HISTORICAL_APPLY.md) · [TECHNICAL_TP_CANDIDATE_DEFINITION_REVIEW.md](TECHNICAL_TP_CANDIDATE_DEFINITION_REVIEW.md)

---

## 1. Freeze release checklist

| # | Condition | Status |
|---|-----------|--------|
| 1 | Coverage remediation closed | **PASS** |
| 2 | Historical integrity intact | **PASS** |
| 3 | Historical math delta = 0 | **PASS** |
| 4 | unresolved historical = 0 | **PASS** |
| 5 | source unavailable historical = 0 | **PASS** |
| 6 | post-COV runtime PASS evidence | **PASS** (53–58+ v2) |
| 7 | COV anomaly = 0 | **PASS** |
| 8 | TP/SL production policy unchanged | **PASS** (6% / 3%) |
| 9 | OOS not started | **PASS** |
| 10 | look-ahead violation 없음 (본 PRECHECK 설계) | **PASS** |

**TP_ANALYSIS_FREEZE_RELEASE_READY = YES**  
(본 STEP에서 config/status **미변경** — 해제 *준비*만 확인)

---

## 2. Original TP Discovery validity

| Item | Value |
|------|-------|
| Source | Candidate definition review · paired n=47 |
| Means (cite only) | 2% −0.0487 · 3% 0.0331 · 4% −0.0007 · 6% **0.0629** |
| Prior verdict | `CANDIDATE_EVIDENCE_INSUFFICIENT` · **KEEP_6** |
| FROZEN_CANDIDATE_TP | **null** |
| COV-D impact on inputs | Historical reconstruct math **unchanged** (ANY_MATH_CHANGED=0) |
| COV impact on narrative | Prior “DB coverage gap” → **SOURCE_ABSENT**; MARKET_LOW_MOVE 유지 |

**ORIGINAL_TP_ANALYSIS_VALID = PARTIAL**

- 수치·KEEP_6 결론의 **입력 math는 무효화되지 않음** (YES).  
- coverage 해석·high-coverage 진단 맥락은 remediation 후 **재서술 필요** → 전체 패키지 PARTIAL.  
- 재계산은 본 STEP에서 **미실행**.

---

## 3. Dataset groups (next analysis · no TP math)

Cutoff (original, frozen for design):  
`status=COMPLETED` ∧ `shadow_id ≤ 51` ∧ `completed_at ≤ 2026-08-14T23:25:40.424Z`

STRICT = `_is_valid_cohort_row` (return 5/15/30/60 · mfe/mae · tp/sl hit · no mismatch).

| Group | count | STRICT | notes |
|-------|------:|-------:|-------|
| **A DISCOVERY_FIXED** | **50** | **47** | ids ≤50 under cutoff; exclude return-window gaps **4,6,10** |
| **B POST_DISCOVERY_PRE_COV** | **1** | **1** | **51** KRW-ONG (µs past cutoff) |
| **C POST_COV** | **11** | **10** | **53–63** v2; **53** missing return_5m → not STRICT |
| **D EXCLUDED** | **1** | **0** | **52** LONG_ACTIVE_TARGET_BLOCKED |

### Symbols / concentration (DISCOVERY STRICT n=47)

unique symbols **23** · top: RE 5 · BTC/SOL/WLD 4 · ETH/ID/MOVE/ONDO/VIRTUAL 3 · …  
Concentration: **MEDIUM** (no single symbol dominates; RE ≤5/47).

### Provenance

| Group | path_quality v2 |
|-------|-----------------|
| DISCOVERY_FIXED | **0/50** on-row (COV-D reconstructable; historical integrity INTACT) |
| POST_DISCOVERY_PRE_COV | 0/1 on-row |
| POST_COV | **11/11** `technical_path_quality_v2` · unresolved=0 · unavailable=false |
| EXCLUDED 52 | v2 present · target ABSENT_CONFIRMED |

Runtime snapshot (READ, post-baseline growth): total **63** · ACTIVE **1** · COMPLETED **62** · completed_v2 **11**.

---

## 4. Look-ahead design

**PROPOSED_NEW_DISCOVERY_CUTOFF** (제안만 · DB/정책 미저장):

```text
ORIGINAL DISCOVERY CUTOFF 유지
  shadow_id ≤ 51
  AND completed_at ≤ 2026-08-14T23:25:40.424Z
  AND status = COMPLETED
```

- Discovery 확장으로 53+를 넣지 않음.  
- Structure: DISCOVERY → candidate definition → candidate freeze → OOS (OOS starts **strictly after** cutoff).  
**LOOK_AHEAD_SAFE_REANALYSIS_DESIGN = YES**

---

## 5. POST-COV 53–58 (+59–63) handling

| Option | Meaning |
|--------|---------|
| A | Discovery 확장 ~58 |
| **B (권고)** | Discovery 고정 · **53+ = future / OOS reserve** |
| C | 일부만 discovery |

**권고: Option B** — OOS 오염 방지 · runtime proof 표본을 candidate 선택에 재사용하지 않음.

---

## 6. Candidate Search 판정

**TP_CANDIDATE_REANALYSIS_RECOMMENDED**

이유: freeze가 coverage 대기로 잠겼고 해제 준비 완료 · FROZEN_CANDIDATE=null · SOURCE_ABSENT/path_quality guard를 반영한 **정식 재개**가 필요.  
Discovery KEEP_6 수치는 유효하나, remediation 이후 해석·가드 패키지 재확인 없이 KEEP_6 closeout으로 바로 닫지 않음.  
MORE_SAMPLE는 불필요(discovery STRICT 47 충분; 추가 표본은 OOS reserve).

본 STEP에서 candidate **미선택**.

---

## 7. Metrics (제안 확정 · 미실행)

| Role | Metric |
|------|--------|
| **Primary** | paired counterfactual exit return % (`compute_tp_sl` · SAME_CANDLE_SL_CONSERVATIVE) |
| **Guards** | median return · loss rate · MFE · MAE · TP hit · SL exit · timeout · symbol concentration · same-candle ambiguity · **path_quality provenance** (신규 권고) |
| **fee/slippage** | **미포함** (기존 분석·evaluator와 동일) — 변경 제안 없음 |

---

## 8. OOS

| Gate | Value |
|------|-------|
| OOS_DESIGN_READY | **NO** (single candidate 미동결 · freeze package 미완성) |
| OOS_START_READY | **NO** (candidate null → 필수) |

진입 조건(정의만): single candidate frozen · discovery cutoff frozen · metrics/guards frozen · OOS after cutoff · min sample rule · no OOS tuning.

---

## 9. shadow 52

**SHADOW_52_EXCLUDED_FROM_TP_ANALYSIS = YES** · hygiene follow-up 유지 · TP dataset 자동 포함 금지.

## 10. News (isolated READ)

MATCHED completed **3** · NO_NEWS completed **28** · NO_NEWS active **10** · EXCLUDED **5** · ACCUMULATING · **TP 분석 미사용**.

## 11. Safety

TradingOrder **241** · Outbox **52** · LIVE OFF · execution not running · outbox worker false.  
production/DB/TP/OOS/commit/push mutation = **0**.

## 12. Next STEP (exactly one)

**TECHNICAL TP CANDIDATE REANALYSIS**

## STOP

TP 계산 · TP/SL 변경 · candidate freeze · OOS · DB/production 수정 · LIVE/ARM/주문 · commit/push — **미실행**.
