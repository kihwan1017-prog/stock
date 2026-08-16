# TECHNICAL SHADOW LONG_ACTIVE TERMINATION — IMPLEMENTATION PRECHECK

**MODE:** READ-ONLY · **STEP U-TERM-A0**  
**Date:** 2026-08-16  
**HEAD:** `3bbf0cd`  
**Basis:** [TECHNICAL_SHADOW_LONG_ACTIVE_TERMINATION_DESIGN.md](TECHNICAL_SHADOW_LONG_ACTIVE_TERMINATION_DESIGN.md)  
**Verdict:** **`TERMINATION_IMPLEMENTATION_READY_TARGET_ONLY`**  
**JSON:** [TECHNICAL_SHADOW_LONG_ACTIVE_TERMINATION_IMPL_PRECHECK.json](TECHNICAL_SHADOW_LONG_ACTIVE_TERMINATION_IMPL_PRECHECK.json)

DESIGN을 재작성하지 않음. Coverage/TP reopen **NO**.

---

## 1. Insertion point

| Field | Value |
|-------|-------|
| **TERMINATION_INSERTION_FUNCTION** | `UpbitOpportunityShadowEvaluator._apply_timeseries` |
| **TERMINATION_INSERTION_LOCATION** | `persist=True` 경로에서 `_compute_payload` 완료 직후 · `path_quality`/`source_reconcile`/`windows` 가용 · **path_pass 분기 이후** · 60m final column/`COMPLETED` write **직전** |
| **BEFORE_COMPLETION_WRITE** | **YES** |
| **AFTER_RECONCILIATION** | **YES** (reconcile은 `_compute_payload` 내부) |

Lifecycle (확인됨):

`ACTIVE select` → maturity/candle load → source reconcile → target resolve → path_quality → (여기서 termination) → completion/defer → DB finalize.

권장 helper: `_maybe_terminate_permanent_absence(row, computed, detail) -> bool`  
`path_quality.py` 수정 **불필요**.

---

## 2. Predicate input availability

| Input | Status | Notes |
|-------|--------|-------|
| status | **AVAILABLE** | row.status |
| 60m maturity | **DERIVABLE** | `windows["60"].target_candle_end` ≤ now |
| 60m target status | **AVAILABLE** | `windows["60"].status` / `fallback_reason` |
| source absence confirmed | **AVAILABLE** | `TARGET_CANDLE_ABSENT_CONFIRMED` |
| reconcile result | **AVAILABLE** | `path_quality` / `source_reconcile` |
| unresolved_missing | **AVAILABLE** | path_quality |
| source_unavailable | **AVAILABLE** | path_quality |
| nearest_prior_at | **DERIVABLE** | target resolve / recompute (stored window may null lag) |
| prior_lag_seconds | **DERIVABLE** | same |
| fallback_limit | **AVAILABLE** | `max_prior_lag_seconds` / DEFAULT 180 |
| grace start | **MISSING → WRITE** | `evaluation_detail.termination.first_blocked_at` (or bootstrap) |
| evaluator interval | **AVAILABLE** | `settings.upbit_scanner_shadow_evaluator_interval_seconds` (180) |

---

## 3. Grace

| Field | Value |
|-------|--------|
| **GRACE_START_SEMANTICS** | `first_blocked_at` = 영구부재 후보( grace 제외) 최초 관측 시각. **기존 ACTIVE** 는 bootstrap: `first_blocked_at = target_candle_end(60m)` (이미 mature + ABSENT_CONFIRMED) |
| **FIRST_BLOCKED_AT_WRITE_REQUIRED** | **YES** (JSON only · **no schema column**) |
| **GRACE_FORMULA** | `now >= first_blocked_at + 3 × evaluator_interval_seconds` (default **540s**) |

기각: `detected_at + 60m`만으로 grace 시작(너무 이른 종료 가능).  
채택: maturity + ABSENT 확정 후 first_blocked / bootstrap.

---

## 4. SOURCE_UNAVAILABLE max-age

| Field | Value |
|-------|--------|
| **SOURCE_UNAVAILABLE_MAX_AGE_IMPLEMENT_READY** | **NO** |

근거 숫자(운영 측정 threshold) 없음 → **가짜 max-age 금지**.  
이번 TERM-A 구현 범위: **`TARGET_PERMANENTLY_UNRESOLVABLE`만**.  
`SOURCE_UNAVAILABLE` → 기존 **ACTIVE retry** 유지.

---

## 5. CANCELLED write contract (최소)

```text
status = CANCELLED
evaluated_60m_at / completed_at / return / MFE / MAE / TP / SL  — 쓰지 않음
evaluation_detail.termination = {
  version, reason, terminated_at,
  target_window, target_at,
  nearest_prior_at, prior_lag_seconds, fallback_limit_seconds,
  first_blocked_at, last_checked_at
}
```

`reason = TARGET_PERMANENTLY_UNRESOLVABLE`  
금지: `evaluated_60m_at` · return · MFE/MAE · TP/SL hit fake.

---

## 6. Isolation

| Consumer | Result |
|----------|--------|
| COMPLETED filter | **PASS** |
| STRICT_VALID / cohort | **PASS** (`_is_valid_cohort_row` COMPLETED only) |
| cohort_n / REVIEW_READY | **PASS** |
| TP analysis scripts | **PASS** (COMPLETED only) |
| candidate analysis | **PASS** |
| next tick ACTIVE select | **PASS** (ACTIVE only → no rewrite) |

**ISOLATION_BLOCKER = NO**

---

## 7. Shadow 52 dry (no UPDATE)

| Condition | Value |
|-----------|-------|
| status ACTIVE | **true** |
| 60m mature | **true** (end `2026-08-13T22:20:00Z`) |
| 60m MISSING + ABSENT_CONFIRMED | **true** |
| source_unavailable | **false** |
| unresolved_missing | **0** |
| reconcile OK / check performed | **true** |
| prior_lag (60m) | **360 > 180** (PRECHECK nearest `22:13`) |
| grace elapsed (bootstrap from candle_end) | **true** (≫540s) |
| termination detail today | **null** |

**SHADOW_52_WOULD_TERMINATE = YES** (bootstrap grace)  
실제 UPDATE **금지** (본 STEP).

---

## 8. File matrix

| Path | Role |
|------|------|
| `src/.../upbit_opportunity_shadow/evaluator.py` | production insert |
| `src/.../upbit_opportunity_shadow/termination.py` **또는** `constants.py` 확장 | helper/constants (prefer small helper) |
| `tests/test_upbit_shadow_long_active_termination.py` | dedicated |

**제외 (이번):** `path_quality.py` · API · FE · stats (필수 아님)

---

## 9. Test plan (구현 STEP용)

| ID | Scenario | Expect |
|----|----------|--------|
| A | source present | COMPLETED |
| B | absent + prior ≤180 | LAST_KNOWN → COMPLETED |
| C | absent + prior >180 + grace not elapsed | ACTIVE |
| D | absent + prior >180 + grace elapsed | CANCELLED |
| E | source unavailable | ACTIVE |
| F | CANCELLED next tick | no process / no rewrite |
| G | CANCELLED | cohort/STRICT/TP 제외 |
| H | shadow52 equivalent | CANCELLED |
| I | TradingOrder/Outbox | delta 0 |

---

## 10. Verdict

**`TERMINATION_IMPLEMENTATION_READY_TARGET_ONLY`**

| Item | Value |
|------|-------|
| Schema | **NO** |
| Migration | **NO** |
| U blocker | none for TARGET_ONLY |
| **Next U STEP** | **`SHADOW LONG_ACTIVE TERMINATION IMPLEMENTATION (TARGET_ONLY)`** |

---

## Safety (this STEP)

production mutation **0** · DB mutation **0** · commit **NO** · push **NO**
