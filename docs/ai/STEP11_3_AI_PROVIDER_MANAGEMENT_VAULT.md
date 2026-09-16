# STEP 11-3 — AI Provider 관리센터 및 Credential Vault

## Architecture

```
Admin UI / Admin API
        │
AIProviderManagementService
        ├── ai.provider_configuration
        ├── ai.provider_credential (AES-256-GCM)
        └── ai.provider_configuration_history
        │
registry_loader (DB SoT → env bootstrap → Fail Closed Mock)
        │
AIManager / Registry (atomic reload)
```

**금지:** 저장만으로 enable, 저장만으로 외부 AI 호출, AI→주문/LIVE/ARM/Scheduler, 전략 생성.

## Source of Truth

| 우선순위 | 조건 |
|----------|------|
| 1. DB | `ai.provider_configuration` 행 존재 |
| 2. ENV bootstrap | DB 비어 있을 때만 (개발/비상) |
| 3. Fail Closed | DB 로드 실패 → **Mock only** |

정책:

- DB가 있으면 env가 임의 overwrite 금지
- Secret env → DB 자동 복사 금지
- Migration 중 Secret 이동 금지
- Seed: Mock만 `enabled=true`, `is_default=true`
- Startup: `bootstrap_ai_manager_from_db()` (외부 AI 호출 없음)

개발: env bootstrap 가능. 운영: DB SoT, Fail Closed 시 Mock only.

## DB Schema (Migration `u1b2c3d4e5f6`)

- `ai.provider_configuration`
- `ai.provider_credential`
- `ai.provider_configuration_history`

Constraints / Index:

- `provider_code` CHECK enum
- partial unique: 단일 default (`is_default=true`)
- partial unique: 단일 active credential
- CHECK: default이면 enabled 필수
- FK: credential/history → configuration CASCADE

## Credential Vault

- Broker `credential_crypto` AES-256-GCM **재사용** (테이블은 AI 전용)
- Master Key: `BROKER_VAULT_MASTER_KEY_FILE`
- 평문 DB/로그/응답 금지
- fingerprint (SHA-256), status: PENDING / VERIFIED / INVALID / REVOKED / EXPIRED
- Ollama / Mock: Secret 불필요
- Compatible: api_key optional, custom header allowlist only
- Authorization / Cookie / Host 등 위험 Header 거부

## Enable 흐름

1. Config 저장 (enable 아님)
2. Credential 저장 (PENDING, inactive)
3. Verify (명시, 저비용 probe)
4. Enable (`confirm=true`, VERIFIED 또는 Secret 불필요)
5. Reload (명시, commit 이후)

저장/Enable 시 **자동 Test 호출 없음**.

## Credential Rotation

1. 새 Credential PENDING 저장  
2. Verify  
3. 성공 시 atomic active switch + 이전 REVOKED  
4. 실패 시 기존 active 유지, 신규 INVALID  

## Registry Reload

- DB commit과 동일 Transaction에 묶지 않음
- atomic swap, 실패 시 기존 Manager 유지
- Metrics/Circuit 가능하면 유지
- Config Drift = `reload_required` 또는 DB version ≠ runtime version

## Admin API

Prefix: `/api/v1/admin/ai/provider-configurations`

CRUD + credentials store/verify/rotate/revoke + enable/disable/set-default/reload + history

보안: `require_admin`, reason, correlation_id, rate limit, optimistic version, Audit, Secret 미반환.

## Frontend

`/admin/ai/providers` — 목록·상세·Credential·Enable Modal·Set Default·수동 Test

- Secret 재노출 금지 / password 입력
- 빈 endpoint·api_key는 기존 값 삭제 금지

## Dashboard / Telegram

- Source / Credential / Drift / DB·Runtime version / Reload
- `/providers`, `/provider_health`, `/provider`, `/provider_config` 조회만
- Telegram에서 Secret·enable·test·rotate 금지
- 조회 시 외부 AI 호출 0

## Audit (요약)

CONFIGURATION_CREATED/UPDATED, CREDENTIAL_STORED/VERIFY_*/ROTATED/REVOKED,
ENABLE_*/ENABLED/DISABLED, DEFAULT_CHANGED, RELOAD_*/RELOADED/RELOAD_FAILED

Secret·encrypted_payload·전체 Header·Prompt 제외.

## Rollback

1. Provider disable  
2. Credential revoke  
3. Migration downgrade `u1b2c3d4e5f6`  
4. env Mock bootstrap  

## 장애 대응

| 증상 | 대응 |
|------|------|
| Master Key 없음 | Credential 저장 Fail Closed |
| DB 로드 실패 | Mock only |
| Reload 실패 | 기존 Runtime 유지, Drift 표시 |
| Verify 실패 | 기존 Credential 유지 |

## 테스트 (실 AI 호출 없이)

```bash
pytest tests/test_step11_3_ai_provider_management_vault.py -q
alembic upgrade head && alembic downgrade -1 && alembic upgrade head
```

Mock HTTP / crypto unit. `live_ai` Marker는 기본 제외.
