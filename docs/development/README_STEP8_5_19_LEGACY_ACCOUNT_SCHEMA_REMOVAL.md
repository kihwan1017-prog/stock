# STEP 8-5-19 — Legacy Account Schema 제거 및 Skipped Test 복구

## 조사 결과

내부 식별용 `account_number`가 남아 있던 핵심 경로:

| 영역 | 기존 | 분류 |
|------|------|------|
| `operation.position_limit` UK `(broker, account_number, exchange, symbol)` | 내부 식별 | 제거→UBA/Paper |
| `operation.risk_event.account_number` NOT NULL | 내부 식별 | 제거→UBA/Paper + masked |
| `RiskAccountStateService.load(account_number=...)` | Deprecated | 제거 |
| Risk Dashboard / Position Limit API path | 내부 입력 | UBA/Paper |
| Daily Loss Paper Unique | 미구현 | Method A 테이블 추가 |
| Kiwoom/Upbit Adapter vault account_number | 외부 API | 유지 |
| masked 표시 | 표시 | 유지 |

## Position Limit

### 기존
- UK: `(broker_code, account_number, exchange_code, symbol)`

### 변경
- 컬럼: `user_broker_account_id`, `paper_account_id`, `account_scope_type`, `masked_account_ref`
- `account_number` 컬럼 **삭제**
- Partial Unique:
  - `(uba, exchange, symbol)` WHERE uba IS NOT NULL
  - `(paper, exchange, symbol)` WHERE paper IS NOT NULL
- Check: `ck_position_limit_exactly_one_scope`

## Risk Event

### 기존
- `account_number` NOT NULL (UK 없음)

### 변경
- `user_id`, `user_broker_account_id`, `paper_account_id`, `correlation_id`, `masked_account_ref`, `account_scope_type`
- `account_number` 컬럼 **삭제**
- Check: `ck_risk_event_account_scope`
- Dedup/Idempotency에 account_number 미사용 (correlation_id)

## Paper Daily Loss (Method A)

테이블 `operation.account_daily_loss`:

- LIVE Unique: `(uba, trading_date, currency, market)`
- Paper Unique: `(paper, trading_date, currency, market)`
- Check: 정확히 하나의 scope

Runtime이 활성 UBA + Paper 전수 점검 후 upsert.

## Deprecated Loader 제거

- `RiskAccountStateService.load(...)` → 호출 시 `LEGACY_ACCOUNT_NUMBER_ONLY` raise
- 대체: `load_by_uba` / `load_by_paper_account`
- AST 테스트로 운영 코드 `load(account_number=)` 호출 0 검증

## Adapter 허용 경계

- Kiwoom/Upbit credential vault의 `account_number`
- Broker REST body (원문 로그 금지)
- 마스킹 formatter

## Cache / Idempotency / Scheduler

- 주문 idempotency는 이미 client_order_id 기반 (변경 없음)
- Kill/Daily Loss scope: `UBA:{id}` / `PAPER:{id}`
- Scheduler member job: 8-5-18 검증 유지

## Backfill 결과

| 항목 | 건수 |
|------|------|
| position_limit 대상 | 0 |
| risk_event 대상 | 0 |
| UBA Backfill | 0 |
| Paper Backfill | 0 |
| Orphan | 0 |
| 충돌 | 0 |

(운영 DB 기준 두 테이블 모두 비어 있었음)

## Migration

- ID: `g0a1b2c3d4e5`
- Revises: `f9a0b1c2d3e4`
- Down/Up 검증 완료

## Skip 테스트 복구

1. `test_kiwoom_rest_adapter.py` — keyword config + FakeRestClient + UBA 필수 검증
2. `test_risk_service.py::test_create_policy` — 현재 `RiskService.create_policy` FakeRepo
3. `test_risk_service.py::test_create_and_save_position_plan` — 동일

**Skipped = 0**

## Health / Audit

- Health: `legacy_account_schema` 컴포넌트
- Audit 코드: LEGACY_* / DEPRECATED_ACCOUNT_LOADER (이벤트 타입 상수와 API Gone 응답)

## 운영 적용

```bash
python -m alembic upgrade head
```

## Rollback

```bash
python -m alembic downgrade f9a0b1c2d3e4
```

## 남은 Technical Debt

- `broker_pending_order` UK의 account_number (브로커 sync 키 — 후속)
- Snapshot UK `(broker, account_number)` 장기 재검토
- FE Position Limit 관리 UI는 아직 없음 (API만 UBA/Paper)

## v1.0 RC 진입 가능 여부

**가능** — Backend 0 skip / 0 failed, Alembic single head, Lint/tsc/build OK.
