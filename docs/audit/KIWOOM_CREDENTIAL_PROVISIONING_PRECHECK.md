# KIWOOM CREDENTIAL PROVISIONING PRECHECK

**STEP:** K-PROV-0 · **MODE:** PRECHECK ONLY · **Date:** 2026-08-16  
**Verdict:** **`KIWOOM_CREDENTIAL_PROVISIONING_READY`**  
**JSON:** [KIWOOM_CREDENTIAL_PROVISIONING_PRECHECK.json](KIWOOM_CREDENTIAL_PROVISIONING_PRECHECK.json)

실제 secret 입력 · token 발급 · UBA mutation · commit **금지**.

---

## K-1 Auth type

**KIWOOM_AUTH_IMPLEMENTATION_TYPE = REST OAuth token (KiwoomTokenClient.issue)**

Evidence: `credential_vault_service._verify_kiwoom` → `KiwoomOrderConfig` + `KiwoomTokenClient(config).issue()`  
Base URL: mockapi vs api.kiwoom.com (`is_mock` / `settings.kiwoom_use_mock`).  
Not OpenAPI+ desktop COM in this vault path.

---

## K-2 Required fields (no values)

| Field | Class |
|-------|--------|
| `app_key` | **REQUIRED_SECRET** |
| `secret_key` | **REQUIRED_SECRET** |
| `account_number` | **REQUIRED_NON_SECRET** (mask in reports) |
| `account_product_code` | **OPTIONAL** |
| `is_mock` | **OPTIONAL** (default → settings.kiwoom_use_mock) |
| access token | **DERIVED** (verify-time only · not stored as user input) |

---

## K-3 Storage

- Table: `trading.broker_account_credential`  
- Encrypted payload + nonce · `verification_status` · `masked_identifier`  
- Link: `user_broker_account_id`  
- Plaintext persistence: **NO** (vault encrypt)  
- Current linked Kiwoom active rows: **0**

---

## K-4 Entry points

| Path | Exists |
|------|--------|
| **CURRENT_PROVISIONING_UI** | **YES** — User `BrokerCredentialPanel` (KIWOOM app_key/secret) · Admin account credential register/replace |
| **CURRENT_PROVISIONING_API** | **YES** — `POST/PUT /api/v1/user/accounts/{uba_id}/credentials` · verify/revoke · Admin equivalents |

**KIWOOM_CREDENTIAL_UI_MISSING = NO**

Recommend next: **A existing UI/API provisioning** (no new UI first).

---

## K-5 Ownership

`assert_broker_account_access` + vault `owner_user_id` vs `uba.user_id` → **server-side fail-closed**.

---

## K-6 Verify lifecycle (planned · not executed)

```
input (UI/API) → validate fields → encrypt → vault row
→ KiwoomTokenClient.issue (verify) → VERIFIED
→ UBA connection_status=CONNECTED
→ readiness
```

Verify failure → CREDENTIAL_FAILED · not CONNECTED.

---

## K-7 Mock / Real

| Mode | Status |
|------|--------|
| `use_mock=true` | **MOCK_READY** |
| REAL credential | **NOT READY** (0 links) |
| UBA **1381** CONNECTED w/o credential | interpret as **MOCK_CONNECTED / STALE** — REAL gate **fail-closed** (`credential_alignment`) |

---

## K-8 Provisioning safety gate (future APPLY)

Before real provision/verify:

- LIVE OFF · ARM OFF · execution false · outbox worker false  
- correct owner UBA · vault available · encryption key present  
- verification success **before** treating as REAL CONNECTED  

---

## K-9 Masking

Account / keys: mask in audits (`****` / `credential_alignment.mask_kiwoom_credential_fields`). Full account numbers not in this report.

---

## K-11 Actual provisioning plan (user-operated · not Cursor paste)

1. Pick target Kiwoom UBA (owner-correct)  
2. Open User Accounts → Broker Credential (or Admin credential register)  
3. Enter app_key / secret_key / account_number (`is_mock` explicit for REAL)  
4. Register → Verify  
5. Confirm vault status VERIFIED · UBA CONNECTED · recovery credential_missing cleared  
6. Re-run alignment classifier · REAL ready  

Do **not** paste secrets into chat.

---

## K-12 Shared

**SHARED_CHANGE_REQUIRED = false** — existing vault/UBA/API/UI sufficient.

---

## Verdict / Next

**`KIWOOM_CREDENTIAL_PROVISIONING_READY`**

**Next K:** `KIWOOM CREDENTIAL PROVISIONING`  
(승인 후 UI/API · Cursor에 secret 입력 금지)
