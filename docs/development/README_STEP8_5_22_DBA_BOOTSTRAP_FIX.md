# STEP 8-5-22-DBA-FIX — 빈 DB Alembic Bootstrap Schema

## 발견된 오류

빈 DB에서 `alembic upgrade head` 실행 시:

```text
InvalidSchemaName: "operation" 스키마 없음
CREATE TABLE operation.alembic_version (...)
```

## 원인

1. `database/alembic/env.py` 가 Version Table을 `operation.alembic_version` 으로 설정한다 (`version_table_schema="operation"`).
2. Alembic은 Migration revision보다 먼저 Version Table을 만들므로, 빈 DB에서는 `operation` 스키마가 아직 없어 실패한다.
3. 부가: 최초 revision `21ef733dc7ca` 가 no-op(`pass`) 이라 `market` 등 플랫폼 스키마도 Migration 초기에 생성되지 않는다. Version Table 문제만 고치면 다음으로 `market` 스키마 부재가 드러난다.

## 수정 방식

신규 Migration **없음**. Bootstrap만 추가·확장.

| 파일 | 역할 |
|------|------|
| `database/alembic/bootstrap.py` | `PLATFORM_SCHEMAS`에 대해 `CREATE SCHEMA IF NOT EXISTS` (PostgreSQL, 멱등) |
| `database/alembic/env.py` | Online: Context 전에 `ensure_platform_schemas` / Offline: SQL 선두에 동일 DDL |

순서: 연결 → 플랫폼 스키마 보장(commit) → Context → `operation.alembic_version` → 전체 Migration.

스키마 목록은 STEP57 `_SCHEMAS` + `notification` (운영 DB 집합과 정합).

## 신규 설치 동작

수동 `CREATE SCHEMA` 없이 `alembic upgrade head` 가능. Version Table·조기 테이블 DDL이 참조하는 스키마가 선행 생성된다.

## 기존 운영 DB 영향

- `IF NOT EXISTS` 멱등
- Version Table 위치 유지 (`operation.alembic_version`)
- Head 분기 없음 (`j3d4e5f6a7b8`)
- down/up 검증: `i2c3d4e5f6a7` → `head` 정상

## Offline Migration

`--sql` 선두에 플랫폼 `CREATE SCHEMA IF NOT EXISTS …` 가 Version Table DDL보다 먼저 출력된다.  
(전체 `upgrade head --sql` 은 기존 revision offline 비호환(`fetchall`)으로 중단될 수 있음 — bootstrap과 무관한 기존 제약.)

## 권한 Fail Closed

스키마 생성 실패 시 `RuntimeError` — 필요 스키마·`current_user`·CREATE 권한 안내. Secret/DSN 미포함.

## 빈 DB 검증 결과

- DB: `stock_platform_rc_verify_20260726_101410` (수동 스키마 생성 없음)
- Head: `j3d4e5f6a7b8`
- `operation.alembic_version` 단일
- 스키마: ai,auth,backtest,broker,common,disclosure,market,news,notification,operation,public,strategy,trading
- 리포트: `E:\StockTrading\backups\verification\rc22_empty_db_upgrade_report.json`

## Restore 검증

`python scripts/rc22_db_verify.py restore` 는 `PGPASSWORD_ADMIN` 필요. 에이전트 세션에 미설정 시 Fail Closed (`PGPASSWORD_ADMIN required`).  
검증 스크립트에 스키마 선생성 우회는 넣지 않음.

## 운영 적용 절차

1. 코드 배포 (`bootstrap.py` / `env.py`)
2. (선택) 운영 DB에서 `alembic current` 확인 — 변경 없음 예상
3. 신규/복구 DB: `alembic upgrade head` 또는 `python scripts/rc22_db_verify.py empty-upgrade`

## Rollback

`bootstrap.py` 호출 제거 및 `env.py` 원복. DB 스키마 변경(신규 revision) 없음.
