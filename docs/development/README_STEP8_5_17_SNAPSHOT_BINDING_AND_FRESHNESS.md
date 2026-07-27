# STEP 8-5-17 — LIVE Account Binding & Broker Snapshot Freshness

## 1. 기존 구조

- `trading.broker_account_snapshot` / `broker_position_snapshot`는 `(broker_code, account_number)` UK만 존재
- `user_broker_account_id` FK **없음**
- Settlement LIVE adapter가 **broker_code 최신 1건** 휴리스틱 사용
- Upbit는 다수 UBA가 `MAIN` account_ref를 공유할 위험
- `SETTLEMENT_PRICE_MAX_AGE_SECONDS`는 설정만 있고 freshness 미적용

## 2. 변경 구조

```text
Broker API → UBA 확인 → Snapshot 저장(UBA FK) → Settlement/Recovery/Risk는 UBA로만 조회
```

## 3. Binding

- Snapshot 저장 시 `user_broker_account_id` **또는** `paper_account_id` 필수 (XOR)
- ACTIVE Snapshot은 UBA당 1건 (partial unique index)
- Binding 없는 저장 → `BrokerSnapshotBindingError`
- 운영 조회에서 ORPHAN/STALE/SUPERSEDED 사용 금지

## 4. Freshness

검사: 존재, UBA 일치, Broker 일치, ACTIVE, age ≤ `SETTLEMENT_PRICE_MAX_AGE_SECONDS`

실패 시 Settlement `sync_ok=False` + `STALE_BROKER_SNAPSHOT` / `BROKER_DATA_UNAVAILABLE` 등

## 5. Dependency

`KRX_EQUITY_SNAPSHOT` → `KRX_SETTLEMENT` (`depends_on_job_id`)

Settlement Handler는 Snapshot Job 미완료 시 RETRY, 실패 시 SKIPPED_DEPENDENCY

## 6–8. Recovery / Risk / Realtime

- Recovery sync에 `user_broker_account_id` 전달
- Risk: `load_by_uba` 추가, 레거시 load도 ACTIVE+UBA 바인딩만
- Realtime 주문 경로는 account_number를 쓰더라도 Snapshot 테이블 휴리스틱 제거(Risk/Settlement 경로)

## 9. Health

`snapshot_binding` 컴포넌트: by_status, orphan, stale, generation, age

## 10. Admin / USER API

Admin:

- `GET /api/v1/admin/broker-snapshots`
- `GET /api/v1/admin/broker-snapshots/health`
- `GET /api/v1/admin/broker-snapshots/{id}`
- `POST .../verify`
- `GET /api/v1/admin/user-broker-accounts/{uba}/snapshots`
- `POST .../refresh-snapshot`
- `POST .../release-stale`

Kiwoom/Upbit sync: `user_broker_account_id` Query **필수**

USER: `GET /api/v1/user/broker-snapshots` — `정상` / `동기화 중` / `오래됨`만

## 11. Frontend

- Admin Batch: `BrokerSnapshotsPanel`
- Kiwoom/Upbit/Accounts: UBA ID 입력 후 Sync
- User Reports: Snapshot 상태 Tag

## 12. Audit

`SNAPSHOT_CREATED`(저장 경로), `SNAPSHOT_REFRESHED`, `SNAPSHOT_VERIFY`, `SNAPSHOT_STALE`, `SNAPSHOT_BINDING_FAILED`

## 13. Migration

- ID: `e8f9a0b1c2d3` (revises `d7e8f9a0b1c2`)
- 컬럼: uba_id, paper_account_id, status, generation, version, hash, snapshot_time, broker_server_time, created_at
- Backfill: `account_ref_hash` 매칭 → ACTIVE 바인딩, 실패 → **ORPHAN**

## 14. 테스트 / 운영

```text
Backend pytest: 801 passed / 0 failed / 3 skipped
STEP 8-5-17 tests: 8 passed
Frontend Vitest: 98/98
TypeScript: 통과
Lint: 0/0
Production Build: 성공
Alembic down/up: 성공
Head: e8f9a0b1c2d3
Backfill: bound=0 orphaned=3
```

```bash
alembic upgrade head
# SETTLEMENT_PRICE_MAX_AGE_SECONDS 확인
# Kiwoom/Upbit sync 시 user_broker_account_id 필수
```

## 15. 남은 문제

- SYSTEM_SHARED env Credential Sync도 UBA ID 필수 — 운영 절차에 UBA 지정 필요
- Upbit Snapshot account_number는 `UBA:{id}` 형태로 저장 (평문 MAIN 공유 제거)
- Paper Snapshot 테이블 통합은 기존 `portfolio_snapshot` 유지 (paper_account_id 경로)
- Daily Loss Monitor 등 일부 레거시 account_number 경로는 후속 hardening 여지
