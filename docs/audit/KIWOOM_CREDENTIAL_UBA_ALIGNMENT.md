# KIWOOM CREDENTIAL / UBA ALIGNMENT

**STEP:** K-CRED · **Date:** 2026-08-16  
**Verdict:** **`KIWOOM_CREDENTIAL_PROVISIONING_REQUIRED`**  
**JSON:** [KIWOOM_CREDENTIAL_UBA_ALIGNMENT.json](KIWOOM_CREDENTIAL_UBA_ALIGNMENT.json)

---

## Inventory (no secrets)

| UBA | user | connection | active_cred_n | recovery | trading_paused |
|-----|------|------------|---------------|----------|----------------|
| 1338 | 427 | DISCONNECTED | **0** | FAILED credential_missing | true |
| 1349 | 433 | DISCONNECTED | **0** | FAILED credential_missing | true |
| 1381 | 61 | **CONNECTED** | **0** | FAILED credential_missing | true |

Kiwoom credential rows linked: **0** · `kiwoom_use_mock=true`

## Mismatch root cause

| Code | Where |
|------|-------|
| **NO_CREDENTIAL_ROW** | all 3 UBAs |
| **MOCK_CONNECTION_WITHOUT_CREDENTIAL** | UBA **1381** CONNECTED without credential |

## MOCK vs REAL

| Flag | Value |
|------|-------|
| KIWOOM_MOCK_READY | **YES** (use_mock + UBA active) |
| KIWOOM_REAL_CREDENTIAL_READY | **NO** |
| KIWOOM_CREDENTIAL_PROVISIONING_REQUIRED | **YES** |

## Implementation (K_ONLY)

- `broker/kiwoom/credential_alignment.py` — classify / mask / assert (no vault schema WRITE)  
- `tests/test_kiwoom_credential_alignment.py` — A–I  
- SHARED Credential/UBA model **not** modified  
- Actual credential upsert **not** performed  

## P0-2

Position WRITE status **unchanged** (prior K-B).

## Next K

**KIWOOM CREDENTIAL PROVISIONING PRECHECK**
