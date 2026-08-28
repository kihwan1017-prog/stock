# UPBIT STALE_PRE_RESTORE_WAITING Root-Cause Audit

**Verdict:** ACTUAL_WAITING_LIFECYCLE_BUG=true  
**Change History:** UPBIT_WAITING_RESTORE_ENTRY_RELIABILITY_FIX  
**Base:** e71e638

## Root cause

`mark_restored` + `force_waiting_revalidation_after_restore` produced **identical** timestamps:

- `restored_at` = `2026-08-28T09:28:25.635609+00:00`
- `waiting_updated_at` = same instant

Gate used `waiting <= cutoff` → restored/nudged WAITING rejected as STALE until a later bump (~09:37 watchdog).

Not TTL/supersession/owner mismatch. Not regression of 337a6c6 (None waiting_at path).

## Cases

| Sel | Sym | Class |
|-----|-----|-------|
| 277 | XPL | E BUG equal-epoch after nudge |
| 285 | CHIP | E BUG (later ACCEPTED after bump) |
| 287 | MINA | E BUG (later ACCEPTED after bump) |
| 282 | LINK | H no STALE post-restart (superseded) |

POST_RESTORE_NEW_WAITING_REJECTED_AS_STALE=0

## Fix

1. Compare with `waiting < cutoff` (equal = release)
2. Nudge forces `updated_at > restored_at` (+1µs if needed)

## Intended semantics

- INTENDED_PROTECTION: block pre-restore WAITING BUY after restart
- EXPECTED_RELEASE: post-restore nudge / updated_at >= restored_at
- TRUE PASS ≠ lifecycle revalidation proof (separate epoch/nudge)
