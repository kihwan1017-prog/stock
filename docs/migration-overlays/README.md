# Migration Overlay 보관

`alembic.ini`의 표준 경로는 `database/alembic/` 입니다.

이 디렉터리의 파일은 **STEP 패키지 overlay**로 제공되었으나,
Alembic revision chain에 연결되지 않은 **참고용 초안**입니다.

## 적용 금지

- 이 디렉터리 파일을 `alembic upgrade` 대상으로 사용하지 마세요.
- canonical migration은 `database/alembic/versions/`에만 추가합니다.

## 파일별 상태 (STEP35 분석 기준)

| 파일 | 상태 | 비고 |
|------|------|------|
| `step32_7_order_outbox_idempotency.py` | canonical에 편입됨 | `database/alembic/versions/*_add_order_outbox_idempotency_execution_tables.py` 참고 |
| `step32_8_execution.py` | canonical에 편입됨 | 위와 동일 revision |
| `20260717_02_step33_market_data.py` | **사용 금지** | `market.instrument` / `price_daily`와 중복 |
| `20260717_01_step32_position.py` | 보류 | `paper_position`, `broker_position_snapshot`과 역할 중복 — STEP38 검토 |
| `20260717_03_indicator.py` | 보류 | STEP36에서 별도 테이블 vs 컬럼 추가 검토 |

## Legacy DB 객체

ORM 미등록 테이블은 `docs/LEGACY_DB_OBJECTS.md`를 참고하세요.
