# TECHNICAL BAR COVERAGE REMEDIATION DESIGN

**MODE:** READ-ONLY DESIGN ONLY  
**Date:** 2026-08-15  
**Baseline:** Root cause `MIXED_MARKET_AND_DATA` · COVERAGE_IMPACT HIGH · **KEEP_6_AND_FIX_DATA_FIRST**  
**JSON:** [TECHNICAL_BAR_COVERAGE_REMEDIATION_DESIGN.json](TECHNICAL_BAR_COVERAGE_REMEDIATION_DESIGN.json)

**구현 · backfill · migration · TP 변경 · commit — 전부 금지 (본 STEP).**

---

## 1. 최종 판정

| 항목 | 값 |
|------|-----|
| Design verdict | **REMEDIATION_DESIGN_READY** |
| Recommended option | **OPTION E** (A+B realtime + C historical, phased) |
| Realtime first slice | **OPTION D** (= A+B) |
| Historical | **BACKFILL_AND_COMPARE** (default) · **REWRITE_HISTORY 비권장** |
| REALTIME_SCHEMA_CHANGE_REQUIRED | **NO** |
| CURRENT_TP | **6.0%** |
| TP_CANDIDATE_ANALYSIS | **FROZEN** |
| OOS | **NOT_STARTED** |
| Next | **TECHNICAL BAR COVERAGE REMEDIATION IMPLEMENTATION PRECHECK** |

---

## 2. Candle pipeline (E2E)

| Stage | File / symbol | In → Out | Notes |
|-------|---------------|----------|-------|
| Upbit source | REST `/v1/candles/minutes/{unit}` | market,to,count → raw JSON list | Public market data |
| Client | `broker/upbit/market/client.py` `UpbitQuotationClient.list_minute_candles` | unit∈{1,3,5,15}, count 1–200, `to` optional | `_rate_limiter.acquire`; 429/418 classify |
| Pagination | `collectors/upbit/minute_collector.py` `UpbitMinuteCollector.collect` | start/end → DTO list | cursor=`to` from end backward; count=200; max_pages=100; dedupe by `candle_at` |
| Rate | client + coordinator | before each GET | retryable 429/5xx; 418 no-retry |
| Normalize | `UpbitMinuteParser` | UTC `candle_date_time_utc` → `candle_at` tz-aware | OHLC + volume/trade_value |
| Persist service | `markets/service.py` `CandleMinuteService.save_many` | rows → upsert count | rejects high&lt;low |
| Persist repo | `markets/repository.py` `CandleMinuteRepository.upsert_many` | ON CONFLICT DO UPDATE | PK `(instrument_id, timeframe, candle_at)` |
| Table | `market.candle_minute` | OHLC + volume | UTC `candle_at` |
| Scheduler (shadow) | `evaluator_scheduler.py` interval **60–300s** (default 180) | tick → `evaluate_pending` | **no dedicated global minute sync job found** |
| Evaluator sync | `candle_loader.ensure_shadow_minute_bars` | DB first; if `len(bars) < expected_min` → sync(`resume=False`) | soft fill only |
| Target resolve | `resolve_missing_target_minutes` | exact target minutes only | absent vs source_unavailable |
| Path | `candle_path.observe_windows` / `compute_mfe_mae` / `compute_tp_sl` | bars + entry + window | missing bars **skipped** (no synthetic OHLC) |

**Critical asymmetry:** 5/15/30/60 **target** minutes can FINAL via exact or *confirmed-absent* last_known (≤180s lag). Intermediate minutes for MFE/TP/SL have **no completeness gate** → COMPLETED with sparse path is possible.

---

## 3. Source contract (code-first)

| Item | Implementation |
|------|----------------|
| Endpoint | `GET /v1/candles/minutes/{unit}` |
| Max rows/request | **200** (`count`) |
| `to` | cursor string `%Y-%m-%dT%H:%M:%SZ` (end-side) |
| Range filter | collector keeps `start_at <= candle_at <= end_at` (**inclusive both**) |
| Order | API returns newest-first; collector sorts ascending |
| Pagination | move cursor to oldest of page; stop when `oldest <= start_at` or empty |
| Termination | empty page · reached start · max_pages · cursor stuck → error |
| Duplicate timestamps | `rows_by_at[candle_at] = item` last-wins |
| Missing minute | **not synthesized** — simply absent from map |

---

## 4. Persistence contract

| Item | Value |
|------|-------|
| Schema/table | `market.candle_minute` |
| PK | `(instrument_id, timeframe, candle_at)` |
| Symbol | via `market.instrument` (exchange_code=UPBIT) |
| Interval | `timeframe` SmallInt ∈ {1,3,5,15} |
| Timestamp | `candle_at` timestamptz UTC (open time) |
| Insert | `INSERT … ON CONFLICT DO UPDATE` (full OHLC refresh) |
| Transaction | repo `commit()` per upsert_many |
| Retention/delete | **no candle_minute purge** found (job retention ≠ candles) |

### API→DB loss paths (조사)

| Path | Risk |
|------|------|
| Sync never called (no global job; only evaluator soft-sync) | **HIGH / POSSIBLE** |
| `resume=True` on other callers advancing past holes | **POSSIBLE** (shadow path uses `resume=False`) |
| Sync exception swallowed (`shadow_candle_sync_failed`) | **POSSIBLE** |
| Pagination max_pages / cursor stuck | **POSSIBLE** (60m alone ≪ 200; multi-symbol contention more relevant) |
| Rate limit interrupting sync mid-window | **POSSIBLE** |
| Upsert rejection (high&lt;low) drops row | **POSSIBLE** rare |
| Intentional no-trade (Upbit omits minute) | **POSSIBLE** — indistinguishable without API confirm |
| Post-save delete | **NOT_FOUND** |

---

## 5. Sync contract

| Trigger | Frequency | Lookback | Notes |
|---------|-----------|----------|-------|
| Shadow evaluator tick | ~180s | `detected−1m` … `min(now, detected+60m)` | `ensure_shadow_minute_bars`; `expected_min ≈ span−2` |
| Manual Admin evaluate / evaluate-now | on demand | same | API `POST …/shadows/evaluate*` |
| Startup dedicated minute sync | — | — | **NOT_FOUND** |
| Periodic global candle sync | — | — | **NOT_FOUND** |
| Target minute resolve | per missing matured target | ±2m narrow | API confirm absent |

Failure: log warning, continue evaluate with whatever DB has. No infinite retry. No coverage block.

---

## 6. Low-coverage root-cause classification (n=19)

Per-row API replay **미실행** (본 STEP 금지). Classification from code + prior DB absence evidence:

| Class | Verdict | Notes |
|-------|---------|-------|
| PERSISTENCE_MISSING | **CONFIRMED** (all 19) | expected slots absent in `candle_minute` |
| SYMBOL_NO_TRADE | **POSSIBLE** | Upbit often omits zero-trade minutes; DB vol=0 rows rare |
| SYNC_NOT_RUN / incomplete soft-sync | **POSSIBLE** | no global sync; evaluator sync best-effort |
| SYNC_LATE | **POSSIBLE** | long completion lag; corr with coverage inconclusive |
| EVALUATOR_QUERY_RANGE | **POSSIBLE** | path uses available bars only after FINAL targets OK |
| FETCH_RANGE_GAP / PAGINATION_GAP / RATE_LIMIT | **POSSIBLE** | not row-proven |
| SOURCE_NOT_RETURNED | **POSSIBLE** | needs live API compare |
| UNKNOWN | residual if API confirms trades existed but DB empty after sync |

**대표:** GRVT#49 cov0.39 DISTRIBUTED; ONDO#34 consec gap max9 MIDDLE — pattern fits thin/`no-trade` **or** sync holes; **not** CONFIRMED collection-only.

---

## 7. NO_TRADE_DISTINGUISHABLE

**PARTIAL**

| What exists | Limit |
|-------------|-------|
| Target windows: `resolve_missing_target_minutes` can mark `absent_by_target` after API | Only 5/15/30/60 targets |
| Intermediate minutes | **No** absent-confirm loop |
| Volume=0 placeholder candles | Not used as no-trade markers (recent sample vol0≈0) |

Needed for full distinction: per-missing-minute API existence check **or** exchange “empty candle” contract (Upbit does not persist empty 1m).

---

## 8. COVERAGE_METRIC_SEMANTICS

**OVERSTATES_MISSING** (with **AMBIGUOUS** operational reading)

Diagnostic coverage = `actual_stored / expected_clock_minutes` (~61).  
Clock-empty no-trade minutes inflate “deficiency.” Still useful as **upper-bound data-completeness stress**, not pure outage meter.  
**Formula change forbidden this STEP.**

---

## 9–12. Defects

| Defect | Verdict | Evidence |
|--------|---------|----------|
| BOUNDARY_DEFECT | **NOT_FOUND** (minor **POSSIBLE** off-by-one on inclusive +60) | `floor_minute(detected)`…`detected+60m`; load pad `−1m`; expected≈61 |
| PAGINATION_DEFECT | **NOT_APPLICABLE** for single 60m window alone; **POSSIBLE** under multi-symbol sync load | count=200 ≫ 60 |
| API_LIMIT_DEFECT | **POSSIBLE** | count cap 200; not proven on Discovery |
| RATE_LIMIT_DEFECT | **POSSIBLE** | client 429 path; sync failure → partial DB |
| EVALUATOR_BEFORE_CANDLE_COMPLETE | **YES** | Race: targets FINAL (exact/last_known) while intermediate minutes still missing → COMPLETED + sparse MFE/TP path |

Race detail: `_apply_timeseries` stamps windows independently; COMPLETED when `evaluated_60m_at` set; **no** check that `[detected, terminal]` bar density meets path quality.

---

## 13–15. Re-eval & existing gate

| Item | Verdict |
|------|---------|
| COMPLETED_REEVALUATION | **MANUAL** — `dry_recompute` READ-ONLY; `ReconciliationService` preview/apply allowlist; scheduler **does not** rewrite COMPLETED |
| Auto re-eval after late candle fill | **NONE** → incomplete COMPLETED can **permanently freeze** wrong MFE/returns |
| EXISTING_COVERAGE_GATE | **NONE** (only soft `expected_min` sync trigger — **PARTIAL** at best) |

---

## 16–20. Options

| Opt | Summary | Correctness | Complexity | DB | Scheduler | Look-ahead | Hist compat | Ops risk |
|-----|---------|-------------|------------|-----|-----------|------------|-------------|----------|
| **A** | Completeness check + defer before COMPLETED | High | Med | Low | Med (longer ACTIVE) | Low if defer bounded | Good | Med |
| **B** | Sync overlap/lookback/reliability | Med | Med | Med writes | Low–Med | Low | Good | Med (rate) |
| **C** | Post-COMPLETED re-eval path | High for repair | Med–High | Low if compare-only | Low | **High if silent rewrite** | Needs fingerprint | High if auto-apply |
| **D** | A+B | High | Med–High | Med | Med | Low | Good | Med |
| **E** | A+B+C | Highest | High | Med | Med | Controlled if C=compare | Best if phased | Med if C gated |

### Recommended

**OPTION E (phased)**  
1. Realtime ship **D (A+B)** first.  
2. Historical **C** as **BACKFILL_AND_COMPARE** / read-only recompute — apply only under existing reconciliation fingerprint gate.  
3. Never silent REWRITE_HISTORY.

---

## 21–24. Realtime / historical / schema

### Realtime (신규 ACTIVE)

```text
ACTIVE
  → ensure bars + (proposed) path-completeness audit fields in evaluation_detail
  → targets may still use last_known_absent
  → if path coverage / max_gap fail → DEFER (stay ACTIVE; bounded retries in detail)
  → if pass → evaluate → COMPLETED
  → if defer exhausted → TERMINAL_INCOMPLETE marker in evaluation_detail
     (do NOT stamp as normal COMPLETED) — status remains ACTIVE or operator CANCELLED
```

기존 상태 `ACTIVE`/`COMPLETED`/`CANCELLED`로 표현 가능 → **새 status enum 추가 금지.**  
**REALTIME_SCHEMA_CHANGE_REQUIRED = NO** (detail JSON + metrics audit 우선; DB 컬럼은 이후 optional).

### Historical (Discovery 47)

**권장: BACKFILL_AND_COMPARE**  
1. Optional candle backfill (별도 승인 STEP).  
2. `dry_recompute` / mismatch compare.  
3. Apply only via reconciliation allowlist.  

**KEEP_HISTORY** alone insufficient (distorted cohort).  
**REWRITE_HISTORY** 기본 비권장.  
**실행 본 STEP에서 금지.**

---

## 25. Proposed quality metrics

| Metric | Storage |
|--------|---------|
| bar_count / expected_bar_count / coverage_ratio | **audit compute first**; optional later `evaluation_detail.coverage` |
| max_gap / first_bar_at / last_bar_at | audit / detail |
| evaluation_lag | derived `completed_at - detected_at` |
| completeness_reason | detail enum: OK / DEFERRED / NO_TRADE_CONFIRMED / SYNC_FAIL / EXHAUSTED |

**DB schema change: not required for COV-A observability wave.**

---

## 26. Acceptance gate design

| Gate | Grounded now | PROPOSED (not ratified) |
|------|--------------|-------------------------|
| Path coverage | H/L split @0.8 diagnostic only | PROPOSED: defer below diagnostic band **after** no-trade-adjusted metric exists |
| Max consecutive gap | L: med4 max9 observed | PROPOSED: defer if max_gap ≥ N (N TBD in precheck) |
| Window boundary | contract clear | exact floor/inclusive checklist in tests |
| Late final candle | last_known ≤180s | keep; do not equate to full-path OK |
| Re-eval consistency | mismatch watch exists | PROPOSED: post-remediation MATCH rate on new cohort |

**Do not freeze numeric production thresholds in this STEP.**

---

## 27–30. Freeze / News

| Item | Value |
|------|-------|
| CURRENT_TP | **6.0%** |
| TP_CANDIDATE_ANALYSIS | **FROZEN** (until clean cohort post-remediation) |
| OOS | **NOT_STARTED** |
| High-cov n=28 2/3% direction | **ignored for apply** |
| News | MATCHED **2/20** · NO_NEWS **22/20** · **NEWS_AB_SAMPLE_ACCUMULATING** |

---

## 31–35. Safety

production / DB / TradingOrder / Outbox / create_order / POST /orders / LIVE / ARM / Scheduler / commit·push = **0 / unchanged**

---

## 36. Limitations

- No live Upbit replay for the 19 low-cov rows.  
- No-trade vs outage still entangled.  
- Coverage metric overstates missing.  
- Design only — no implementation.

---

## 37. Implementation waves (제안 · 자동 구현 금지)

| Wave | Scope |
|------|-------|
| **COV-A** | Coverage observability in audit/`evaluation_detail` (no policy block yet) |
| **COV-B** | Realtime completeness/defer before COMPLETED (Option A) |
| **COV-C** | Sync reliability: retry/backoff, `resume=False` hole fill, rate-aware batching (Option B) |
| **COV-D** | Historical backfill + read-only recompute / compare (Option C gated) |
| **COV-E** | Post-remediation validation gate + unfreeze TP analysis criteria |

---

## 38. Next STEP (exactly one)

**TECHNICAL BAR COVERAGE REMEDIATION IMPLEMENTATION PRECHECK**

---

## STOP

production 수정 · DB mutation · migration · candle backfill · TP/SL · Scanner/Gate · OOS · LIVE/ARM/Scheduler · 주문 · commit/push — **전부 미실행**.
