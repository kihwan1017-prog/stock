# Alembic Duplicate Revision Repair — n1b2c3d4e5f6

**Date (KST):** 2026-08-25  
**FINAL_VERDICT:** `ALEMBIC_DUPLICATE_REVISION_REPAIRED`

## DUPLICATE_REVISION = n1b2c3d4e5f6

### DUPLICATE_FILES

| | FILE_A (non-canonical) | FILE_B (canonical) |
|--|--|--|
| FILE | `n1b2c3d4e5f6_live_unattended_authorization.py` → renamed `n7u8n9a0t1e2_live_unattended_authorization.py` | `n1b2c3d4e5f6_grant_trading_write_to_viewer.py` |
| FIRST_COMMIT | `6ce5035` 2026-08-20 `feat(trading): support unattended live authorization renewal` | `3554ef8` 2026-07-28 `STEP11 completed` |
| CREATE_DATE (doc) | — | 2026-07-22 |
| DOWN_REVISION | `o6p7q8r9s0t1` | `m9a0b1c2d3e4` |
| PURPOSE | `operation.live_unattended_authorization` table + indexes | grant `viewer`→`trading:write` RBAC row |
| RELATED_FEATURE | Unattended LIVE lease | Viewer paper/self-service trading write |

### DB_APPLIED

| File | Result | Evidence |
|------|--------|----------|
| FILE_A unattended | **FULLY_APPLIED** | table + `ix_op_live_unatt_uba` + `uq_op_live_unatt_uba_active` exist |
| FILE_B grant | **PARTIALLY_APPLIED / superseded** | `viewer` role gone (RBAC rename); `user` has `trading:write` |

### CANONICAL DECISION

| | |
|--|--|
| **CANONICAL_FILE** | `n1b2c3d4e5f6_grant_trading_write_to_viewer.py` |
| **CANONICAL_REASON** | Git first-owner (Jul 28 STEP11) before Aug 20 accidental ID reuse; RBAC downstream `o2c3d4e5f6a7` Create Date 2026-07-22 revises this ID |
| **NON_CANONICAL_FILE** | live_unattended_authorization |
| **NEW_REVISION_ID** | `n7u8n9a0t1e2` |

### DOWNSTREAM_REFERENCES_UPDATED

| Migration | Before | After | Intent |
|-----------|--------|-------|--------|
| `o2c3d4e5f6a7_rbac_admin_user_roles_only.py` | `n1b2c3d4e5f6` | **unchanged** | RBAC chain → grant |
| `p7q8r9s0t1u2_upbit_full_market_assignment.py` | `n1b2c3d4e5f6` | **`n7u8n9a0t1e2`** | trading/ops → unattended |

### DB_ALEMBIC_VERSION

| version_num | FOUND_IN_SCRIPT | Notes |
|-------------|-----------------|-------|
| n1b2c3d4e5f6 | YES | Now resolves to **grant** file |
| p7q8r9s0t1u2 | YES | Parent is now **n7u8n9a0t1e2** (not stamped in DB) |
| ntpl_ko_20260821a | YES | head |

**n1b2c3d4e5f6_MEANS_CANONICAL = NO/UNKNOWN** — LIVE row was recorded alongside full-market/unattended ops branch; after repair the same id means grant.  
**DB_VERSION_RECONCILIATION_REQUIRED = YES** — need next STEP to stamp `n7u8n9a0t1e2` (DDL already applied, stamp only) without blind stamp of unrelated heads.

### GRAPH

| | |
|--|--|
| GRAPH_PARSE | **PASS** |
| CYCLE_DETECTED_AFTER | **NO** |
| DUPLICATE_REVISION_COUNT_AFTER | **0** |
| SCRIPT_HEADS_AFTER | `ntpl_ko_20260821a`, `perf_acs_obs_20260825`, `symown_20260821a` |
| ALEMBIC_CURRENT | parses; reports `ntpl_ko_20260821a` (multi-row version table still present) |

### SAFETY

DB_BUSINESS_DATA_MUTATION=0 · LIVE_SCHEMA_DDL=0 · ALEMBIC_STAMP=0 · ALEMBIC_MERGE=0  
LIVE_INDEX_DROP=0 · LIVE_INDEX_REBUILD=0 · REAL_TRADING_MUTATION=0 · backend restart=0

### FILES_CHANGED

1. `database/alembic/versions/n7u8n9a0t1e2_live_unattended_authorization.py` (renamed + revision id)
2. `database/alembic/versions/p7q8r9s0t1u2_upbit_full_market_assignment.py` (down_revision rewire)
3. Evidence `.run/k_alembic_duplicate_revision_n1b2c3d4e5f6_repair.*`

### NEXT_ACTION

`RECONCILE_DB_ALEMBIC_VERSION_AND_MERGE_HEADS`
