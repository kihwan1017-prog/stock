# UPBIT TERMINATION SELECTIVE COMMIT PRECHECK

**STEP:** U-TERM-C0 · **MODE:** PRECHECK ONLY · **Date:** 2026-08-16  
**HEAD:** `3bbf0cd` · **Verdict:** **`UPBIT_TERMINATION_SELECTIVE_COMMIT_READY`**  
**JSON:** [TECHNICAL_SHADOW_TERMINATION_SELECTIVE_COMMIT_PRECHECK.json](TECHNICAL_SHADOW_TERMINATION_SELECTIVE_COMMIT_PRECHECK.json)

commit/push **금지** (본 PRECHECK).

---

## U-1 Inventory

| Path | Class |
|------|-------|
| `src/.../termination.py` (new) | **U_TERM** |
| `src/.../evaluator.py` (+52 lines TERM only) | **U_TERM** |
| `tests/test_upbit_shadow_long_active_termination.py` | **U_TERM** |
| `docs/audit/TECHNICAL_SHADOW_*TERMINATION*` / `SHADOW_52_*` / `TERMINATION_RUNTIME_*` | **U_TERM** |
| Canonical CURRENT_WORK / ROADMAP / STEP_MASTER / IMPLEMENTATION / audit README | **U_TERM** (next-step 갱신 포함) |
| FE / broker / ops / Upbit Ambiguous / NewsCollector / P0 residual | **PREEXISTING_WIP** — **EXCLUDE** |
| K-only (`credential_alignment`, fill_position_write, KIWOOM_* audits except if mixed) | **EXCLUDE** from U commit |

`UNEXPECTED` / `UNKNOWN` = **0** (TERM file set)

---

## U-2 Evaluator hunks

| Field | Value |
|-------|-------|
| Diff vs `3bbf0cd` | **+52 / −0** only |
| Content | import `apply_permanent_absence_termination` + PATH PASS terminate/grace block |
| **EVALUATOR_FULL_FILE_SAFE** | **YES** |
| **HUNK_SPLIT_REQUIRED** | **NO** |

---

## U-3 Dependency closure

`termination.py` imports: `get_settings`, `candle_path` (lag/ABSENT/as_utc), `constants` — all **COMMITTED_BASELINE** @ HEAD.  
New module is self-contained; evaluator only adds call site.

**U_DEPENDENCY_CLOSURE = PASS**

---

## U-4 Runtime proof (not a code commit artifact)

| Item | Value |
|------|-------|
| shadow52 | ACTIVE → **CANCELLED** |
| natural tick | **YES** |
| forced evaluate | **0** |
| manual DB mutation | **0** |
| idempotency | **PASS** |
| **shadow70** | same predicate · MISSING+ABSENT_CONFIRMED · unresolved=0 · unavailable=false · grace elapsed → **EXPECTED** |

---

## U-5 prior_lag null

| Field | Value |
|-------|--------|
| Classification | **PROVENANCE_GAP** (display) · **not LOGIC_GAP** |
| Logic | `lag is not None and lag <= 180` → block; **lag null = no prior within fallback → candidate True** (`termination.py`) |
| Commit blocker? | **NO** |

---

## U-6 Focused tests (executed this PRECHECK)

`test_upbit_shadow_long_active_termination` + path_defer + source_reconcile + path_quality → **PASS** (31)

---

## U-7 Staging plan

| Flag | Value |
|------|-------|
| FULL_FILE_SAFE | **YES** |
| HUNK_SPLIT_REQUIRED | **NO** |
| OPTIONAL_DOCS | `PARALLEL_TRACK_U_TERM_A0_K_G0_PRECHECK.md` (historical parallel) |
| EXCLUDED_WIP | all FE/broker/ops/Ambiguous/NewsCollector/K production · tmp_* · .run |

**Expected staged classes:** preexisting/unexpected/unknown = **0**

### Proposed stage list

```
src/stock_platform/operation/upbit_opportunity_shadow/termination.py
src/stock_platform/operation/upbit_opportunity_shadow/evaluator.py
tests/test_upbit_shadow_long_active_termination.py
docs/audit/TECHNICAL_SHADOW_52_LONG_ACTIVE_PRECHECK.{md,json}
docs/audit/TECHNICAL_SHADOW_LONG_ACTIVE_TERMINATION_DESIGN.{md,json}
docs/audit/TECHNICAL_SHADOW_LONG_ACTIVE_TERMINATION_IMPL_PRECHECK.{md,json}
docs/audit/TECHNICAL_SHADOW_LONG_ACTIVE_TERMINATION_IMPL.{md,json}
docs/audit/TECHNICAL_SHADOW_TERMINATION_RUNTIME_OBSERVATION.{md,json}
docs/audit/TECHNICAL_SHADOW_TERMINATION_SELECTIVE_COMMIT_PRECHECK.{md,json}
docs/audit/README.md
docs/CURRENT_WORK.md
docs/ROADMAP.md
docs/STEP_MASTER_STATUS.md
docs/PROJECT_IMPLEMENTATION_STATUS.md
```

---

## U-8 Commit strategy

Single atomic U commit (not executed now):

```
fix(technical): terminate permanently unresolved shadows
```

---

## Verdict / Next

**`UPBIT_TERMINATION_SELECTIVE_COMMIT_READY`**

**Next U:** `UPBIT TERMINATION SELECTIVE COMMIT`
