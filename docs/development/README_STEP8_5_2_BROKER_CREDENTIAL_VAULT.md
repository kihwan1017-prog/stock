# STEP 8-5-2 — UserBrokerAccount Credential Vault

UBA별 암호화 Credential 저장·조회·검증·교체·폐기.  
사용자 실계좌 LIVE 주문/Recovery는 환경변수 공용 키로 자동 대체하지 않는다.

---

## 1. 기존 Credential 구조

- `trading.user_broker_account`: 계좌번호 **해시·마스킹만** 저장. Secret 컬럼 없음.
- 키움/업비트 Adapter·Factory·Recovery는 `Settings`(환경변수)의 단일 APP/ACCESS KEY에 의존.
- Outbox payload의 `credential_ref`가 LIVE UBA여도 `SYSTEM_SHARED:{broker}`로 표기되던 상태.
- 프로젝트 내 기존 AES Vault / Credential 테이블 **없음** → 신규 도입.

## 2. 환경변수 단일 Credential 문제

- 모든 사용자 주문이 동일 브로커 키를 공유하면 계좌 격리·감사·폐기 불가.
- Secret 교체·사용자별 연결 검증·Recovery 계정 단위 실패 격리가 불가능.
- 평문 env는 운영 공용/개발 호환용으로만 남기고, **사용자 LIVE에는 fallback 금지**.

## 3. 선택한 Vault 구조

```text
USER → UserBrokerAccount → BrokerAccountCredential → Encrypted Payload
                                              ↓
                                    Kiwoom / Upbit Adapter
```

단일 진입점: `BrokerCredentialVaultService`  
Adapter 빌더: `credential_adapter_factory.py`

## 4. 암호화 방식

- **AES-256-GCM** (인증 암호화)
- Nonce 12바이트 난수, AAD에 `key_version` 포함
- 단순 Base64/해시 저장 금지
- 의존성: `cryptography==44.0.2`

단기 Access Token은 Vault에 장기 저장하지 않음 (기존 Kiwoom Token Cache 유지).

## 5. Master Key 관리

| 항목 | 내용 |
|------|------|
| 파일 예 | `E:\StockTrading\secrets\broker-vault-master.key` |
| 환경변수 | `BROKER_VAULT_MASTER_KEY_FILE` (경로만) |
| 생성 | `ops/generate_broker_vault_key.ps1` |
| 정책 | 기존 파일 덮어쓰기 금지, 콘솔에 원문 미출력, Git 경로 생성 금지 |
| 부재 시 | Paper/일반 조회 가능. **LIVE 주문·UBA Recovery·Credential 등록 차단** |

Master Key는 소스/DB/로그/테스트 fixture에 원문 저장 금지.

## 6. DB 설계

테이블: `trading.broker_account_credential`

주요 컬럼: `encrypted_payload`, `nonce_b64`, `encryption_algorithm`, `key_version`,  
`is_active`, `verification_status`, `masked_identifier`, `last_verified_at`, `last_used_at`,  
`revoked_at`, …

**활성 Unique (Partial):**

```sql
UNIQUE (user_broker_account_id, credential_type) WHERE is_active = true
```

이유: 현재 Credential 타입은 `BROKER_API` 단일. 계좌당 활성 1개.  
향후 타입이 늘면 동일 제약으로 타입별 1개 활성 유지.

## 7. Credential Lifecycle

1. **등록**: 소유권 → 필수값 → 암호화 → 저장 → 외부 검증  
   - 검증 실패해도 저장 유지 (`verification_status=FAILED`), LIVE 주문 차단
2. **교체**: 기존 `is_active=false` + `revoked_at` → 신규 활성 (트랜잭션 + Unique)
3. **폐기**: 비활성 + 연결 상태 DISCONNECTED + (ADMIN 시) `account_paused=true`
4. **검증**: Broker API 호출 (Kiwoom token / Upbit accounts). Secret 미포함 메시지만 저장

## 8. USER API

| Method | Path |
|--------|------|
| POST | `/api/v1/user/accounts/{uba_id}/credentials` |
| PUT | `/api/v1/user/accounts/{uba_id}/credentials` |
| DELETE | `/api/v1/user/accounts/{uba_id}/credentials` |
| POST | `/api/v1/user/accounts/{uba_id}/credentials/verify` |
| GET | `/api/v1/user/accounts/{uba_id}/credentials/status` |

- 본인 UBA만 (`assert_broker_account_access`)
- 응답: 상태·마스킹만 (원문 금지)
- Secret 조회 API 없음

## 9. ADMIN API

| Method | Path |
|--------|------|
| GET | `/api/v1/admin/accounts/{uba_id}/credentials/status` |
| POST | `/api/v1/admin/accounts/{uba_id}/credentials/verify` |
| POST | `/api/v1/admin/accounts/{uba_id}/credentials/revoke` |

- `require_admin`
- 원문/복호화/Export 불가
- revoke 시 Credential 폐기 + UBA risk `account_paused=true`

## 10. Kiwoom 연결

- LIVE Adapter: Vault `app_key`/`secret_key`로 `KiwoomOrderConfig` 구성
- Recovery(UBA): Vault 계정 클라이언트 + payload `account_number`
- Token 발급은 런타임 Cache (장기 Vault와 분리)

## 11. Upbit 연결

- LIVE Adapter / Private Client: Vault `access_key`/`secret_key`로 Settings 복사본
- Recovery(UBA): Vault private client (env fallback 금지)

## 12. Recovery 연결

- UBA 경로: Vault 필수. 실패 시 `credential_*` 코드, `trading_should_remain_paused=true`
- 다른 계좌 Recovery는 독립 (계좌 단위 실패)
- 시스템 공용(UBA 없음)만 env 허용

## 13. 주문 안전 처리

순서:

```text
주문 요청 → UBA/상태 → Vault Credential 검사 → Risk → Outbox → Adapter
```

차단 사유 예: `CREDENTIAL_MISSING`, `CREDENTIAL_UNVERIFIED`, `CREDENTIAL_DECRYPTION_FAILED`, …

Outbox `credential_ref`: `USER_BROKER_ACCOUNT:{uba_id}`  
`uses_system_shared_credential`: 사용자 LIVE에서 **false**

## 14. Frontend USER

- 계좌 목록 「API Credential」→ 등록/교체/검증/폐기 모달
- 저장 후 Form 초기화, Secret 재표시 없음
- localStorage 등에 Secret 미저장

## 15. Frontend ADMIN

- 계좌관리 화면 `AdminBrokerCredentialCard`
- 상태/재검증/폐기만. 복호화 UI 없음

## 16. 로그 마스킹

`security_mask.py`에 `app_key`, `access_key`, `credential`, `encrypted_payload`, `nonce_b64` 등 추가.  
계좌번호는 `mask_account_number`.

## 17. 감사 로그

이벤트: `BROKER_CREDENTIAL_REGISTER|REPLACE|REVOKE|VERIFY(|_FAILED)`,  
`ADMIN_BROKER_CREDENTIAL_*`  
detail: `before_status` / `after_status` / `key_version` 등 메타만.

## 18. Migration ID

- Revision: **`t7a8b9c0d1e2`**
- Down: `s6f7a8b9c0d1`
- 파일: `database/alembic/versions/t7a8b9c0d1e2_broker_account_credential_vault.py`
- **env Credential 자동 Backfill 없음** (소유자 불명·평문 위험)

## 19. 변경 파일 (주요)

- `src/stock_platform/broker/credential_*.py`
- `src/stock_platform/broker/factory.py`, recovery adapters, order execution/outbox
- `src/stock_platform/api/v1/user_broker_credentials.py`, `admin_broker_credentials.py`
- `ops/generate_broker_vault_key.ps1`
- Frontend: `BrokerCredentialPanel`, `AdminBrokerCredentialCard`, API clients
- `requirements.txt` (`cryptography`)
- tests: `test_credential_crypto.py`, `test_step8_5_2_credential_vault.py`

## 20. 테스트 결과

| 항목 | 결과 |
|------|------|
| Backend vault/crypto unit | 통과 |
| Alembic upgrade/downgrade/upgrade | 통과 (`t7a8b9c0d1e2`) |
| Frontend Vitest | 75/75 |
| TypeScript `tsc --noEmit` | 통과 |
| ESLint | 오류 0 / Warning 6 (기존) |
| Production Build | 성공 |

## 21. 운영 적용 방법

1. DB 백업
2. `alembic upgrade head` (`t7a8b9c0d1e2`)
3. `ops/generate_broker_vault_key.ps1` 로 Master Key 생성 (없을 때만)
4. `BROKER_VAULT_MASTER_KEY_FILE` 설정 (`stock-platform.env`)
5. 서버 재시작
6. 사용자별 UBA Credential 등록·검증
7. `VERIFIED` 계좌만 LIVE 재개
8. 기존 env 키는 시스템 공용/레거시 점검용으로만 유지 (사용자 LIVE fallback 금지)
9. Master Key를 DB 백업과 **별도**로 안전한 위치에 백업
10. Key 분실 시: 기존 암호문 복호화 불가 → Credential 재등록 필요
11. Rotation: 새 키 생성 → (향후) re-encrypt 작업 → `key_version` 갱신 (현재 v1)
12. DB 백업본에도 암호문만 포함 — Master Key 없으면 무용
13. 감사 로그에서 REGISTER/VERIFY/REVOKE 확인

## 22. Key Rotation

현재 `key_version=1` 고정.  
Rotation 절차(운영):

1. 새 Master Key를 별도 파일로 생성 (기존 덮어쓰기 금지)
2. 애플리케이션에 dual-read(구·신) 지원 배포 후 재암호화 배치
3. 구 키 폐기  
(배치 도구는 후속 STEP에서 보강 가능)

## 23. 남은 문제

- Master Key dual-read / 자동 re-encrypt 배치 미구현
- Kiwoom 단기 Token의 UBA별 영속 Cache 테이블 미분리 (메모리 Cache)
- 기존 env 기반 관리자 동기화 API는 공용 키 경로 잔존 (사용자 LIVE와 분리)
- 검증 시 외부 Broker 실호출 필요 (오프라인 CI는 mock/unit 위주)
- STEP 8-5-3 이후 작업은 본 STEP 범위 밖

## 24. 기존 Lint Warning 6건 상태

변경 없음 (의도적 비수정):

- onboarding (`Result` unused)
- watchlist (useMemo deps)
- AuthGuard (`adminRoutes` unused)
- tokenStorage (`_persist` ×3)

이번 STEP에서 신규 Lint **error 0**, Warning 추가 없음.
