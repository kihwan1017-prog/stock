# Quarantined Alembic Migrations

Active `database/alembic/versions/` 그래프에서 격리한 migration 증거 보관소입니다.

**이 디렉터리의 파일을 `versions/`로 되돌리거나 `alembic upgrade`로 실행하지 마십시오.**

---

## h1a2b3c4d5e6 — Broker external order/trade history

| 항목 | 값 |
|------|-----|
| revision | `h1a2b3c4d5e6` |
| down_revision | `j4k5l6m7n8o9` |
| branch_labels | `None` |
| depends_on | `None` |
| 원래 위치 | `database/alembic/versions/h1a2b3c4d5e6_broker_external_order_history.py` |
| quarantine 위치 | `docs/audit/quarantined_migrations/h1a2b3c4d5e6_broker_external_order_history.py` |
| git (격리 전) | **untracked WIP** |
| SHA256 (격리 시) | `3AC369CB4D4BCE6F483696BDB90CD30949F59112C821C5977A277BCB1C4ADC82` |
| 격리일 | 2026-08-13 |
| STEP | P0-4A ALEMBIC UNTRACKED WIP MIGRATION QUARANTINE |

### Quarantine 이유

- tracked head `k2l3m4n5o6p7`와 동일 branchpoint `j4k5l6m7n8o9`에서 갈라져 **Alembic dual-head** 발생
- DB `operation.alembic_version`에는 `k2l3m4n5o6p7`만 기록됨 (`h1a` 미기록)
- 그러나 아래 테이블은 **이미 DB에 존재** (스키마 적용됨, version stamp 없음):
  - `operation.broker_external_order_history`
  - `operation.broker_external_trade_history`
- 이 파일을 `versions/`에 복원 후 `upgrade`하면 `create_table` **DuplicateTable** 실패가 확정됨

### 격리 스냅샷 (2026-08-13, 변경 없음 확인용)

| Object | 존재 | row count |
|--------|------|-----------|
| `operation.broker_external_order_history` | yes | 21 |
| `operation.broker_external_trade_history` | yes | 0 |

**h1a가 생성하는 DB object 목록**

- Tables: `operation.broker_external_order_history`, `operation.broker_external_trade_history`
- PK: `pk_broker_external_order_history`, `pk_broker_external_trade_history`
- Unique: `uq_broker_ext_order_broker_uuid` `(broker_code, external_order_id)`, `uq_broker_ext_trade_broker_uuid` `(broker_code, external_trade_id)`
- Indexes: `ix_broker_ext_order_uba`, `ix_broker_ext_order_conflict`, `ix_broker_ext_trade_order`
- FK: 없음 (migration 정의 기준)

### 금지 / 후속

1. **금지:** 이 파일을 `database/alembic/versions/`로 복원 후 `alembic upgrade` 실행
2. **금지:** `alembic stamp h1a2b3c4d5e6`를 임의 실행
3. **Superseded by:** formal revision **`l3m4n5o6p7q8`**
   (`database/alembic/versions/l3m4n5o6p7q8_broker_external_history_reconcile.py`)
   - `down_revision = k2l3m4n5o6p7`
   - idempotent create/index ensure (기존 운영 테이블/데이터 보존)
   - h1a를 parent로 사용하지 않음
4. h1a는 **audit/archive reference only** — active migration으로 복원하지 말 것
5. 격리 시점 active head는 `k2l3m4n5o6p7`였고, 현재 운영 head는 `l3m4n5o6p7q8`
