# STEP 8-5-18 — Account Identity Hardening

## 기존 계좌 식별 구조

- LIVE Snapshot은 STEP 8-5-17에서 `user_broker_account_id`(UBA) 바인딩을 도입했다.
- 그러나 Daily Loss·Risk Order Guard·Recovery SYSTEM 슬롯·일부 Admin Risk API는 여전히 `account_number` / 환경변수 단일 계좌 / `SYSTEM_SHARED` 휴리스틱에 의존했다.
- 내부 식별자가 UBA ID, paper `account_id`, `account_number`, `account_ref_hash`, MAIN, SYSTEM_SHARED 로 혼재했다.

## 문제점

- 동일 계좌번호 문자열을 가진 서로 다른 회원 데이터가 섞일 위험
- UBA 없는 Snapshot/Sync/Recovery 경로
- ORPHAN Snapshot 3건이 Settlement/Risk 휴리스틱에 노출될 여지
- Kill Switch가 GLOBAL만 사용하고 계좌 키가 account_number 문자열에 의존

## UBA 중심 구조 (LIVE)

내부 소유권·조회·정산·리스크 식별자 = **`user_broker_account_id`**

필수 컨텍스트: `user_id` + `user_broker_account_id` + `broker_code` + market + currency

## Paper Account 구조

내부 식별자 = **`paper_account_id`** (`PaperAccount.account_id`)

## SYSTEM_SHARED 허용 범위

허용(시장 공통): 종목/호가/체결/캔들/거래소 상태/세션/공시/뉴스

금지(회원 계좌): Snapshot/Balance/Position/Settlement/Risk/Daily Loss/Reconciliation

Scheduler는 `validate_scheduler_account_payload` 로 Fail Closed.

## 제거한 account_number 레거시 경로

- Daily Loss 환경변수 `KIWOOM_ACCOUNT_NUMBER` 단일 계좌 루프
- Daily Loss `(broker_code, account_number)` Snapshot 조회
- Risk Order Guard LIVE의 account_number Snapshot load
- Admin realtime-risk `/{account_number}/...` (400 LEGACY)
- Recovery `KIWOOM-SYSTEM` 환경변수 슬롯
- Kiwoom/Upbit Sync의 `account_ref_hash` 자동 매칭 폴백

## 유지한 외부 Broker Adapter 경로

- Kiwoom/Upbit Adapter가 외부 API 호출 시 복호화된 계좌번호 사용
- 응답 저장 시 다시 UBA ID 바인딩
- 화면/로그는 마스킹만

## Daily Loss 변경

- `check_uba(user_broker_account_id)` 전용
- Runtime이 활성 UBA 전수 순회
- Kill Switch는 `UBA:{id}` scope 활성화
- account_number-only `check()` 는 `AccountIdentityError`

## Risk Engine 변경

- LIVE: UBA 없으면 `UBA_REQUIRED` / `LEGACY_ACCOUNT_NUMBER_ONLY`
- Paper: `paper_account_id` 없으면 `PAPER_ACCOUNT_REQUIRED`
- LIVE 상태 로드는 `load_by_uba` (ACTIVE only)

## Kill Switch 변경

- scope: `GLOBAL` | `UBA:{id}` | `PAPER:{id}`
- Guard가 주문 시 GLOBAL+계좌 scope 검사
- account_number를 키로 사용하지 않음

## Position/Balance/PnL

- LIVE Snapshot/Position은 UBA FK + ACTIVE만 운영 사용
- ORPHAN/RETIRED는 Settlement·Risk·Recovery 조회에서 제외 (`NON_OPERATIONAL_SNAPSHOT_STATUSES`)

## Scheduler Payload

회원 계좌 Job 필수: `user_broker_account_id` 또는 `paper_account_id`, `job_type`, `requested_by`, `correlation_id` (+ LIVE `broker_code`)

금지: account_number-only, broker-only, SYSTEM_SHARED 회원 Job

## Adapter 경계

`user_broker_account_id` → UBA 조회 → (필요 시) 복호화 → Broker API → 저장은 UBA

## ORPHAN 3건 처리 결과

| ID | Broker | 결과 |
|----|--------|------|
| 1 | KIWOOM | RETIRED (UBA 테이블 비어 매칭 불가) |
| 2 | KIWOOM | RETIRED |
| 3 | UPBIT (MAIN) | RETIRED |

- 재바인딩: 0
- 폐기(RETIRED): 3
- 미처리: 0
- 물리 삭제 없음

## Migration

- ID: `f9a0b1c2d3e4`
- Revises: `e8f9a0b1c2d3`
- Snapshot status 확장: REBIND_PENDING, REBOUND, RETIRED, PURGED
- Kill Switch `scope_code` 길이 40
- Unmatchable ORPHAN → RETIRED backfill

## Health

- `account_identity_consistency`
- orphan/uba_missing/legacy/system_shared 지표

## Audit

- ORPHAN_SNAPSHOT_REBIND_REQUESTED / REBOUND / RETIRED
- (코드) UBA_REQUIRED, LEGACY_ACCOUNT_NUMBER_ONLY, SYSTEM_SHARED_ACCOUNT_BLOCKED

## Admin API

- `GET /api/v1/admin/broker-snapshots/orphans`
- `POST .../{id}/rebind`
- `POST .../{id}/retire`

## Frontend

- BrokerSnapshotsPanel ORPHAN Queue (Rebind/Retire)

## 운영 적용

```bash
python -m alembic upgrade head
# 필요 시 Admin에서 잔여 ORPHAN rebind/retire
```

## Rollback

```bash
python -m alembic downgrade e8f9a0b1c2d3
```

RETIRED → ORPHAN 으로 복귀(확장 상태 일괄).

## 남은 Technical Debt

- Position limit / risk_event 테이블 UK가 여전히 account_number 문자열 포함
- Paper Daily Loss 전용 테이블 Unique Index는 미도입 (Paper는 PaperPosition 기반)
- Kill Switch BROKER 전체 scope UI는 후속
- 레거시 `RiskAccountStateService.load(account_number=...)` Deprecated 유지 (운영 경로 차단)
