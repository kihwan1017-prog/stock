# README_STEP57 — Database Stabilization

## 1. 목적

`PROJECT_FINAL_AUDIT.md` Database 항목을 기준으로 **운영 가능한 DB**로 안정화한다.

- 신규 비즈니스 기능 없음
- 기존 API / Entity 스키마 유지 (FK·Index·Comment만 보강)
- Alembic head 단일화, 무결성·백업 검증 스크립트 추가

---

## 2. Migration

| 항목 | 값 |
|------|-----|
| Revision | `d4e5f6a7b8c9` |
| Down revision | `c2d3e4f5a6b7` (STEP52) |
| 파일 | `database/alembic/versions/d4e5f6a7b8c9_step57_db_stabilization.py` |

적용:

```bash
python -m alembic -c alembic.ini upgrade head
```

포함 내용:

1. **Schema** — `auth`, `market`, `trading`, `strategy`, `operation`, `news`, `disclosure`, `ai`, `backtest`, `broker`, `common` `CREATE SCHEMA IF NOT EXISTS` (그린필드 보완)
2. **고아 정리** 후 **FK 6개** 추가
3. **Index** 조회 경로 보강
4. **COMMENT ON SCHEMA/TABLE** 운영자용 설명

### Alembic 점검

| 항목 | 결과 |
|------|------|
| Head | `d4e5f6a7b8c9` (단일) |
| Branch | 없음 |
| `env.py` | auth / RBAC / audit / settings 모델 import 추가 (autogenerate drift 완화) |

---

## 3. Foreign Key

| Constraint | 관계 | ON DELETE |
|------------|------|-----------|
| `fk_order_status_history_order` | `trading_order_status_history` → `trading_order` | CASCADE |
| `fk_strategy_deployment_history_deployment` | history → deployment | CASCADE |
| `fk_strategy_deployment_performance_deployment` | performance → deployment | CASCADE |
| `fk_position_plan_policy` | `position_plan.policy_id` → `risk_policy` | SET NULL |
| `fk_broker_recovery_step_run` | recovery_step → recovery_run | CASCADE |
| `fk_trading_order_strategy_deployment` | order → deployment | SET NULL |

기존 유지: execution/outbox → order, paper_* → account, auth RBAC CASCADE 등.

### 의도적으로 미추가 (후속)

| 컬럼 | 사유 |
|------|------|
| `trading_order.account_id` | paper/broker 계좌 통합 테이블 없음 |
| `trading_order.portfolio_id` / `position_id` | 소프트 참조 · 통합 Position 원장 부재 |
| `paper_order.account_id` | 컬럼 자체가 없음 (Entity 변경 범위 밖) |

---

## 4. Index

| Index | 목적 |
|-------|------|
| `ix_paper_order_status_created` | 상태·시간 조회 |
| `ix_paper_order_symbol_created` | 심볼·시간 조회 |
| `ix_paper_trade_account_traded` | 계좌별 체결 이력 (`traded_at`) |
| `ix_trading_order_deployment` | 배포별 주문 (partial) |
| `ix_job_run_history_name_started` | 잡 이력 |
| `ix_job_run_history_status_started` | 상태별 잡 이력 |
| `ix_broker_recovery_run_status_started` | 복구 런 조회 |
| `ix_broker_account_snapshot_broker` | broker_code 최신 스냅샷 |
| `ix_risk_event_created` | 리스크 이벤트 시간순 |
| `ix_strategy_deployment_history_dep` | 배포 이력 |

`pg_stat_user_tables` 기준 seq_scan이 높았던 `job_run_history`, `paper_order`, `broker_account_snapshot`, `broker_recovery_run` 경로를 우선 보강.

---

## 5. Unique

이미 충분한 Unique (변경 없음):

- `trading_order.client_order_id`
- `order_outbox.idempotency_key`
- `execution (broker_code, broker_execution_id)`
- `paper_account.account_name` / `paper_position (account, exchange, symbol)`
- `broker_account_snapshot (broker_code, account_number)`
- `broker_pending_order (broker, account, broker_order_id)`
- `strategy_deployment` active scope, `risk_policy.policy_name`
- auth `username` / role·permission code

후속 후보 (데이터 정책 확정 후):

- `paper_account.user_id` 1:1 강제 여부
- `paper_order` 비즈니스 키 (account 컬럼 추가와 함께)

---

## 6. Transaction

코드 점검 요약 (동작 변경 없음):

| 흐름 | 범위 |
|------|------|
| Order + Outbox | `OrderExecutionService.submit` — order/status/outbox 동일 세션 후 **단일 commit** |
| Outbox Worker | 멱등 begin + broker 송신 + outbox 상태 갱신 (실패 시 retry 세션) |
| Execution | order FK 하에 체결 기록 |
| Paper fill | account / position / trade 동일 서비스 트랜잭션 |
| Risk / Position plan | policy 조회 + plan insert |
| Kill Switch / Risk event | operation 스키마 단일 세션 |

권장: 주문 경로는 계속 `commit=False` 중간 flush + 마지막 commit 패턴 유지.

---

## 7. Schema 생성 순서

권장 의존 순서 (STEP57 migration이 IF NOT EXISTS로 보장):

1. `auth` → 2. `market` → 3. `trading` → 4. `strategy` → 5. `operation` → 6. `news` / `disclosure` / `ai` / `backtest` / `broker` / `common`

---

## 8. Comment

스키마·핵심 테이블에 한국어 COMMENT 추가. 운영자가 `psql` / GUI만으로 용도 파악 가능.

---

## 9. Data Integrity

스크립트: `scripts/check_db_integrity.py`

- 고아 행 (order history, deployment, recovery, execution, outbox, paper_position)
- `client_order_id` 중복
- STEP57 FK constraint 존재 여부

적용 후 로컬 DB: **전부 0 / PASSED**.

---

## 10. Performance

- 고 seq_scan 테이블에 Index 추가 (위 §4)
- 대용량 테이블(`order_outbox`)은 기존 idx_scan 양호 → 유지
- Slow query 로그 수집은 운영 설정(`log_min_duration_statement`) 권장 — 앱 코드 변경 없음

---

## 11. Backup

스크립트: `scripts/verify_db_backup.py`

1. `pg_dump` / `pg_restore` PATH 확인
2. **schema-only** custom-format dump
3. `pg_restore -l` 목록 스모크 (실 DB에 복원하지 않음)

웹 dump/restore 실행 API는 감사 항목 그대로 **후속** (`GET /ops/.../backup/status`는 도구 존재만).

운영 런북: `docs/manual/DB관리매뉴얼.md` + 본 스크립트.

---

## 12. 변경 파일

- `database/alembic/versions/d4e5f6a7b8c9_step57_db_stabilization.py`
- `database/alembic/env.py`
- Entity FK 미러: `order/entities.py`, `strategy_deployment/entities.py`, `performance_monitor_entities.py`, `broker/recovery_entities.py`, `risk/persistence_models.py`
- `scripts/check_db_integrity.py`, `scripts/verify_db_backup.py`
- `README_STEP57.md`

---

## 13. 검증

```bash
python -m alembic -c alembic.ini upgrade head
python scripts/check_db_integrity.py
python scripts/verify_db_backup.py
pytest
# frontend: lint / typecheck / test / build
```
