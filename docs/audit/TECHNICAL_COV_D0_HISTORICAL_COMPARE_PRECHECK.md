# TECHNICAL COV-D0 — HISTORICAL BACKFILL AND COMPARE PRECHECK

**MODE:** READ-ONLY · **NO APPLY** · **NO DB MUTATION**  
**Date:** 2026-08-15  
**Verdict:** **COMPARE_ONLY_SUFFICIENT**  
**JSON:** [TECHNICAL_COV_D0_HISTORICAL_COMPARE_PRECHECK.json](TECHNICAL_COV_D0_HISTORICAL_COMPARE_PRECHECK.json)

---

## 1. 최종 판정

Historical candle path holes are overwhelmingly **SOURCE_ABSENT_CONFIRMED**.  
In-memory recompute on DB bars vs stored COMPLETED metrics: **ANY_MATH_CHANGED = 0**.  
Therefore **historical row APPLY is not required** for math remediation.

| Item | Value |
|------|-------|
| HEAD / runtime | `5c6ad67` |
| PRE_COV_COMPLETED | **51** |
| POST_COV_V2_COMPLETED | **5** (53–57 · exclude from APPLY) |
| TARGET_BLOCKED (ACTIVE) | **1** (`52`) |
| ACTIVE (other) | **0** |
| RECONSTRUCTABLE | **51 / 51** |
| PATH_QUALITY_PASS (v2 dry) | **51** |
| UNRESOLVED / UNAVAILABLE | **0 / 0** |
| db_missing_source_present minutes | **0** |
| absent_confirmed minutes sum | **627** |
| ANY_MATH_CHANGED | **0** |
| changed_rate | **0.0** |
| SCHEMA_CHANGE_REQUIRED | **NO** |
| Historical APPLY | **COMPARE_ONLY_SUFFICIENT** (미실행) |

## 2. Coverage

| | raw | resolved |
|--|-----:|---------:|
| mean | 0.798 | **1.0** |
| median | 0.869 | **1.0** |
| lt 0.8 | **23** | **0** |

Low-raw 23/51 reclass: **A_SOURCE_ABSENT = 23** (B DB missing / C unavailable / D unresolved = 0).  
(Discovery N=47의 “19 low coverage”와 동일 성격 — source absent.)

## 3. TP

- CURRENT_TP **6%** · SL **3%**  
- TP_ANALYSIS **FROZEN_PENDING_COVERAGE_REMEDIATION** (유지)  
- OOS **NOT_STARTED**  
- Metric impact of remediation: **NO** (math delta 0)  
- Framing: coverage holes ≠ recoverable missing bars → TP reopen은 **별도 PRECHECK**  

## 4. APPLY design (if ever needed)

Not required now. If provenance-only attach later:

- selector: `PRE_COV_COMPLETED` without v2  
- write only `evaluation_detail.path_quality` / `source_reconcile`  
- never overwrite return/MFE/TP columns  
- dry-run + backup + idempotent by version key  
- SCHEMA_CHANGE_REQUIRED = **NO** (JSONB)

## 5. Safety

TradingOrder 241 · Outbox 52 · Δ0 · LIVE false · execution false · DB UPDATE 0 · commit/push 0

## 6. Next STEP (exactly one)

**COV-D CLOSEOUT — NO HISTORICAL APPLY**  
(또는 승인 시 TP freeze revisit PRECHECK — APPLY 아님)

## STOP

Historical APPLY · DB mutation · TP/SL · OOS · LIVE · commit/push — **미실행**.
