# TECHNICAL TP KEEP_6 CLOSEOUT

**MODE:** CLOSEOUT / READ-ONLY · **no TP/SL config write · no OOS · no DB mutation**  
**Date:** 2026-08-16  
**HEAD / runtime:** `5c6ad67` · health UP  
**Verdict:** **`KEEP_6_CONFIRMED`** · `TP_ANALYSIS = CLOSED_KEEP_6`  
**Basis:** [TECHNICAL_TP_CANDIDATE_REANALYSIS.md](TECHNICAL_TP_CANDIDATE_REANALYSIS.md)  
**JSON:** [TECHNICAL_TP_KEEP_6_CLOSEOUT.json](TECHNICAL_TP_KEEP_6_CLOSEOUT.json)

---

## 1. FINAL_DECISION

| Field | Value |
|-------|-------|
| FINAL_DECISION | **KEEP_6_SUPERIOR** |
| KEEP_6_CONFIRMED | **YES** |
| TP_ANALYSIS_FINAL_STATUS | **CLOSED_KEEP_6** |
| CURRENT_TP / SL | **6%** / **3%** (production already; **WRITE=0**) |
| FROZEN_CANDIDATE_TP | **null** |
| candidate gates 2/3/4 | **FAIL / FAIL / FAIL** |
| OOS | **NOT_STARTED** |
| OOS_CANDIDATE_FREEZE_READY | **NO** |
| OOS_START_READY | **NO** |

Discovery: COMPLETED **50** · STRICT **47** · PAIRED **47** · SAMPLE_RECONCILIATION **PASS**.

---

## 2. Fixed paired means (n=47)

| TP | mean exit return |
|---:|-----------------:|
| 2% | −0.0487 |
| 3% | 0.0331 |
| 4% | −0.0007 |
| **6%** | **0.0629** |

| vs 6% | Δ mean |
|------|-------:|
| 2% | −0.1116 |
| 3% | −0.0298 |
| 4% | −0.0636 |

PRIMARY = paired counterfactual exit return.  
TP-hit는 2/3/4가 더 높지만 mean 열세 → **TP-hit-only optimization = REJECTED**.

---

## 3. Coverage remediation relationship

| Item | Value |
|------|-------|
| COVERAGE_REMEDIATION_CLOSE | **YES** |
| HISTORICAL_DATA_INTEGRITY | **INTACT** |
| HISTORICAL_APPLY_REQUIRED | **NO** |
| HISTORICAL_DB_REWRITE_REQUIRED | **NO** |

Raw coverage holes → **SOURCE_ABSENT** (not DB persistence loss).  
Remediation 이후에도 discovery paired math 유지 · KEEP_6를 뒤집을 근거 **없음**.

---

## 4. TP Analysis status (Canonical only)

| Prior | Final (docs) |
|-------|----------------|
| `FROZEN_PENDING_COVERAGE_REMEDIATION` | **`CLOSED_KEEP_6`** |

- DB runtime status 컬럼 **미생성**  
- production settings **미수정** (`upbit_scanner_shadow_tp_pct=6.0` 이미 일치)

---

## 5. OOS / POST_COV

| Item | Value |
|------|------:|
| POST_COV_ROWS_USED_FOR_SELECTION | **0** |
| OOS_CONTAMINATION | **0** |

53+ = **future reserve** only (새 가설 전까지 자동 재탐색 금지).

---

## 6. Reopen policy (no auto re-open)

TP candidate search **자동 재개 금지**. 별도 승인 근거 예:

- 충분한 신규 Technical observation  
- market regime 변화  
- 새 candidate hypothesis  
- fee/slippage 포함 분석  
- TP/SL joint optimization  

표본 수 증가만으로 2/3/4/6 grid 반복 최적화 **금지**.

---

## 7. shadow 52

**LONG_ACTIVE_TARGET_BLOCKED** · TP closeout **blocker 아님**.  
**SHADOW_52_FOLLOWUP_REQUIRED = YES** · 본 STEP에서 UPDATE/강제 eval/삭제 **금지**.

---

## 8. News (isolated)

MATCHED completed **3** · NO_NEWS completed **30** · NO_NEWS active **10** · EXCLUDED **5** · milestone **ACCUMULATING** · TP 판단 **미사용**.

---

## 9. Safety

TradingOrder **241** · Outbox **52** · LIVE OFF · execution false · outbox worker false.  
production / DB / TP·SL / Historical APPLY / LIVE mutation = **0**.

---

## 10. Selective commit note (not this STEP)

Uncommitted (ownership candidates for next PRECHECK):

- COV-D0 / COV-D CLOSEOUT audits  
- TP REOPEN PRECHECK / REANALYSIS / KEEP_6 CLOSEOUT audits  
- Canonical 4 + `docs/audit/README.md`  
- optional scripts: `technical_cov_d0_*`, `technical_tp_candidate_reanalysis.py`  

**commit/push = NO** this STEP. Protect residual FE/broker/ops WIP.

## 11. Next STEP (exactly one)

**TECHNICAL COVERAGE + TP CLOSEOUT SELECTIVE COMMIT PRECHECK**

## STOP

TP/SL/OOS/POST_COV reanalysis · DB · LIVE · commit/push — **미실행**.
