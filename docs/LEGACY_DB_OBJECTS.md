# Legacy DB 객체

Alembic/SQLAlchemy로 관리하지 않거나, 코드에서 참조하지 않는 DB 객체 목록입니다.

## operation.system_health

| 항목 | 내용 |
|------|------|
| Schema | `operation` |
| Table | `system_health` |
| ORM Entity | 없음 |
| 코드 참조 | 없음 (STEP35 조사 기준) |
| 처리 | `database/alembic/env.py`의 `include_object`로 autogenerate drop 방지 |

컬럼:

- `health_id` (bigint, PK)
- `component_name` (varchar)
- `status_code` (varchar)
- `message` (text)
- `checked_at` (timestamptz)

STEP39 운영 Health 기능에서 재사용할지, Entity를 추가할지 별도 결정합니다.
