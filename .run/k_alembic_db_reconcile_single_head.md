# Alembic DB Reconcile + Single-Head Merge

**Date (KST):** 2026-08-25  
**FINAL_VERDICT:** `ALEMBIC_DB_RECONCILED_SINGLE_HEAD`

## BEFORE

| | |
|--|--|
| SCRIPT_HEADS | `ntpl_ko_20260821a`, `perf_acs_obs_20260825`, `symown_20260821a` |
| DB_CURRENT / ALEMBIC_VERSION_ROWS | `n1b2c3d4e5f6`, `ntpl_ko_20260821a`, `p7q8r9s0t1u2` |
| tables / indexes | 233 / 713 |

## BRANCH_AUDIT (schema)

| revision | purpose | db_schema_state |
|----------|---------|-----------------|
| n7u8n9a0t1e2 | unattended lease table | FULLY_APPLIED |
| p7q8r9s0t1u2 | full-market assignment | FULLY_APPLIED |
| ntpl_ko_20260821a | KO notification templates | FULLY_APPLIED |
| symown_20260821a | symbol ownership hold/exclusion | FULLY_APPLIED |
| perf_acs_obs_20260825 | asset_context observed_at index | FULLY_APPLIED |
| n1b2c3d4e5f6 (grant) | viewer trading:write | PARTIALLY_APPLIED/superseded (`user.trading:write`, no viewer) |

## SEMANTICS

| Field | Value |
|-------|-------|
| OLD_N1B2_SEMANTIC | **B** — old unattended duplicate meaning (co-stamped with p7q8/ntpl ops tip; unattended DDL FULLY_APPLIED; not a grant-branch tip) |
| N7U8_APPLIED | YES |
| P7Q8_APPLIED | YES |
| SYMOWN_APPLIED | YES |
| NTPL_APPLIED | YES |
| PERF_INDEX_APPLIED | YES |

## RECONCILIATION_CASE = **A**

Schema already at all three heads; only version metadata drifted after duplicate-id repair.

### VERSION_RECONCILIATION_PERFORMED = YES

```text
alembic stamp --purge ntpl_ko_20260821a symown_20260821a perf_acs_obs_20260825
```

Reason: purge ambiguous `n1b2`/`p7q8` rows; stamp exact applied head tips (no DDL).

| | |
|--|--|
| ALEMBIC_VERSION_BEFORE | n1b2c3d4e5f6, ntpl_ko_20260821a, p7q8r9s0t1u2 |
| ALEMBIC_VERSION_AFTER_STAMP | ntpl_ko_20260821a, perf_acs_obs_20260825, symown_20260821a |
| MISSING_DDL_APPLIED | none (`upgrade heads` no-op) |

## MERGE

| | |
|--|--|
| MERGE_SAFE | YES |
| MERGE_REVISION | `a8105aa410f9` (DDL empty `pass`) |
| Applied | `alembic upgrade head` |

## FINAL

| | |
|--|--|
| SCRIPT_HEADS | `a8105aa410f9` |
| HEAD_COUNT | **1** |
| DB_CURRENT | `a8105aa410f9` |
| GRAPH_PARSE | PASS |
| CYCLE_COUNT | 0 |
| DUPLICATE_REVISION_COUNT | 0 |
| UNKNOWN_REVISION_COUNT | 0 |
| tables/indexes | 233 / 713 (unchanged) |
| LIVE_INDEX_PRESERVED | YES `ix_upbit_asset_ctx_observed_at` |
| LIVE_INDEX_REBUILT | 0 |
| DUPLICATE_DDL_ERRORS | 0 |

## SAFETY

DB_BUSINESS_DATA_MUTATION=0  
ALEMBIC_VERSION_METADATA_MUTATION=YES (stamp --purge + merge upgrade)  
REAL_TRADING_MUTATION=0  
BACKEND_RESTART_COUNT=0

## TESTS

- pytest `test_frontend_db_perf_asset_context_list` PASS  
- API smoke: health/live, version, asset-context, ops-status OK  

## GIT_COMMIT

(see commit after this report)

## NEXT_ACTION

`CONTINUE_NORMAL_OPERATION`
