# Alembic Multi-Head + AntD Drawer Cleanup

**Date (KST):** 2026-08-25  
**FINAL_VERDICT:** `ALEMBIC_GRAPH_REPAIR_BLOCKED`

## Summary

- AntD Drawer `width` → `size` (antd 6.5.1 types) **FIXED** and committed separately below.
- Alembic **merge NOT performed** — graph is corrupt (`CycleDetected`, duplicate revision id).

## ALEMBIC

### HEADS_BEFORE (claimed / file-regex earlier)

`g9h0i1j2k3l4`, `m9a0b1c2d3e4`, `perf_acs_obs_20260825`, `u1v2w3x4y5z6`

### CURRENT_BEFORE (LIVE `alembic_version`)

| version_num |
|-------------|
| n1b2c3d4e5f6 |
| ntpl_ko_20260821a |
| p7q8r9s0t1u2 |

`alembic current` / `alembic heads` via ScriptDirectory: **FAILED**  
`CycleDetected` + warning `Revision n1b2c3d4e5f6 is present more than once`.

### BLOCKER — DUPLICATE REVISION ID

| revision | files |
|----------|-------|
| **n1b2c3d4e5f6** | `n1b2c3d4e5f6_live_unattended_authorization.py` (down=`o6p7q8r9s0t1`) |
| **n1b2c3d4e5f6** | `n1b2c3d4e5f6_grant_trading_write_to_viewer.py` (down=`m9a0b1c2d3e4`) |

Same revision id, different parents/purpose → Alembic revision map unusable → **MERGE_SAFE=NO**.

### HEAD_AUDIT (target 4)

| revision | purpose | DDL sample in DB | db_applied |
|----------|---------|------------------|------------|
| g9h0i1j2k3l4 | order strategy provenance | `trading.trading_order.strategy_id` / `runtime_scope_hash` | APPLIED_IN_DB (partial sample YES; `indicator_parameter_config` table NO) |
| m9a0b1c2d3e4 | paper_account.deleted_at | column exists | APPLIED_IN_DB |
| perf_acs_obs_20260825 | asset_context observed_at index | `ix_upbit_asset_ctx_observed_at` | APPLIED_IN_DB (CONCURRENTLY earlier; IF NOT EXISTS) |
| u1v2w3x4y5z6 | unattended auto_renew_enabled | column exists | APPLIED_IN_DB |

### MERGE_SAFE

**NO** — do not stamp; do not create merge revision until duplicate `n1b2c3d4e5f6` is renamed/rewired and cycle is cleared.

### MERGE_REVISION

NONE

### HEADS_AFTER / CURRENT_AFTER

UNCHANGED (no migration metadata mutation)

### LIVE_INDEX_PRESERVED

YES — `ix_upbit_asset_ctx_observed_at` untouched (DROP=0, REBUILD=0)

### DUPLICATE_DDL_OCCURRED

NO (no upgrade run)

### DB_BUSINESS_DATA_MUTATION

0

## ANTD

| | |
|--|--|
| DRAWER_WIDTH_BEFORE | 2 (`UpbitResearchDetailWorkspace` RAG, `KiwoomResearchRagFeedback`) |
| DRAWER_WIDTH_AFTER | 0 |
| REPLACEMENT_API | `size={720}` (`DrawerProps.size?: "default" \| "large" \| number \| string`) |
| PROJECT_WIDE_DEPRECATED_DRAWER_REMAINING | 0 (`Drawer`+`width=` grep) |

Note: Modal `width=` 등은 Drawer deprecation과 무관 → 미변경.

## FRONTEND

| Gate | Result |
|------|--------|
| check:frontend | PASS |
| AUTH_BROWSER_VERIFY | DONE |
| UPBIT research Drawer open | YES (0 antd warnings) |
| KIWOOM research Drawer open | SKIPPED (no table row / empty RAG) — source fixed |
| CONSOLE_ERRORS | 0 |
| CONSOLE_WARNINGS | 0 |
| ANTD_WARNINGS | 0 |
| REACT_WARNINGS | 0 |
| HYDRATION_WARNINGS | 0 |

## SAFETY

REAL_ORDER_MUTATION=0 · LIVE_ARM_MUTATION=0 · RISK/SLOT/POLICY=0  
Backend restart=0

## SYSTEM_BUG_ACTIVE

1. Duplicate Alembic revision `n1b2c3d4e5f6`
2. Alembic CycleDetected (full graph unloadable)
3. LIVE `alembic_version` rows ≠ script leaf heads (P0-4 drift)

## LIMITATIONS

- Cannot produce single head without dedicated revision-id repair STEP
- KIWOOM Drawer open not exercised (empty list)

## NEXT_ACTION

`REPAIR_DUPLICATE_ALEMBIC_REVISION_N1B2C3D4E5F6`

## Evidence

`.run/k_alembic_multihead_antd_drawer_cleanup.json`  
`.run/k_alembic_multihead_antd_drawer_cleanup.md`
