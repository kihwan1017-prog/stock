# STEP 8-3 — 전략 user_id 소유권

작성일: 2026-07-23

## 1. 기존 전략 구조

| 구성요소 | 역할 | 소유권 |
|----------|------|--------|
| `StrategyFactoryRegistry` | 코드→전략 인스턴스 (인메모리) | 없음 |
| `trading.strategy_deployment` | 런타임 배포 인스턴스 | `strategy_code`만 |
| `trading.strategy_performance_run` | 성과/백테스트 실행 | `strategy_code`만 |
| 승인 파이프라인 (`strategy_approval_run`) | `requested_by` / `decided_by` 문자열 메타 | RBAC Role 아님 |
| 별도 전략 정의 테이블 | **없었음** | — |

파라미터·버전은 배포/성과 행의 JSONB에 포함. `user_id` / `visibility` / `is_public` 필드는 기존에 없음.

## 2. 기존 공용 데이터 처리 문제

- FE Alert: “전략 목록·순위는 플랫폼 공용 데이터”
- USER가 전략 ID만으로 타 사용자 자산을 구분할 수 있는 구조 부재
- Runtime이 전역 단일 슬롯이라 동일 공개 전략을 여러 계좌가 써도 상태 혼입 가능

## 3. 선택한 소유권 모델

```text
owner_type
├─ SYSTEM  (user_id IS NULL)
└─ USER    (user_id IS NOT NULL)
```

루트 테이블: **`trading.strategy_definition`**

## 4. 공개 범위 모델

단일 기준: **`visibility` ∈ {PRIVATE, PUBLIC}**

정책:

- USER 생성 기본값: `PRIVATE` + `owner_type=USER` + `user_id=current_user`
- USER는 `PUBLIC` / `SYSTEM` 을 Body로 강제해도 서버가 거부·덮어쓰기
- PUBLIC 전환은 ADMIN `publish` (+ 승인) 경로만
- 공개되어도 원본 소유자 유지, 타 USER는 원본 수정 불가 → **복제** 후 개인 사용

## 5. DB 변경

신규:

- `trading.strategy_definition`
- `trading.account_strategy_link` (Paper XOR UBA)

확장:

- `trading.strategy_deployment`: `strategy_id`, `owner_type`, `user_id`, `visibility`
- `trading.strategy_performance_run`: `strategy_id`, `requested_by_user_id`

ACTIVE 배포 unique → SYSTEM / USER partial index 분리.

## 6. Migration ID

```text
q4e5f6a7b8c9 → r5e6f7a8b9c0
```

파일: `database/alembic/versions/r5e6f7a8b9c0_strategy_ownership.py`

## 7. 기존 전략 Backfill

정책: 기존 `strategy_code`(deployment ∪ performance_run) → **SYSTEM + PUBLIC**. 임의 USER 배정 금지.

로컬 검증 DB 결과:

| 항목 | 수 |
|------|----|
| 전체 기존 전략(정의로 생성) | 0 |
| SYSTEM | 0 |
| USER | 0 |
| 공개 | 0 |
| 비공개 | 0 |
| 소유자 미결정 | 0 (임의 배정 없음) |
| 계좌 연결 유지 | 0 (신규 테이블) |
| Backfill 제외 | 0 |

운영 DB에 deployment/performance 데이터가 있으면 동일 SQL로 SYSTEM PUBLIC 정의가 생성되고 FK가 연결된다.

## 8. 승인 메타값 보존 결과

- Migration에 `decided_by`/`requested_by`/`approved_by` 의 `"operator"` → `"admin"` 일괄 UPDATE **없음**
- 로컬 `operator_meta_preserved` 카운트: **0** (approval 행 없음). 값이 있어도 변경하지 않음
- RBAC Role은 ADMIN/USER만 사용. `"operator"`는 감사·파이프라인 메타로 유지

## 9. USER 권한

가능: 공개 조회, 본인 CRUD( soft delete ), 복제, 본인/공개 백테스트 진입 검사, 본인 계좌 연결

불가: 타인 개인 전략 조회·수정·삭제·실행·연결, SYSTEM/공개 원본 수정, 승인·배포·공개 전환

## 10. ADMIN 권한

`require_admin` + `/api/v1/admin/strategies/*`

전체 조회, SYSTEM 생성/수정, 승인/거절, 공개/비공개, 활성/비활성

## 11. 계좌 전략 연결 소유권

검사 위치: `StrategyDefinitionService.link_to_account`

1. 계좌 소유권 (`assert_paper_account_access` / `assert_broker_account_access`)
2. 전략 접근 (`assert_strategy_readable` = 본인 OR PUBLIC)
3. 활성·미승인 PUBLIC(USER) 차단
4. 시장 호환성

API: `POST/DELETE /api/v1/user/accounts/{account_id}/strategies/{strategy_id}`

## 12. 시장 호환성 검사

`market_compatible()`:

- STOCK → KIWOOM / PAPER / PAPER_STOCK / KRX
- CRYPTO → UPBIT / PAPER_CRYPTO

## 13. Runtime 격리

- `build_runtime_scope_key(user, account|uba, strategy_id, code, market)`
- `DynamicStrategyRuntimeManager`가 scope별 `_runtimes` dict 유지
- `get_active`는 SYSTEM ACTIVE 우선, USER는 `get_active_for_user`
- 비활성·삭제 정의 실행 차단

레거시 전역 슬롯(`_runtime`)은 하위 호환용으로 유지.

## 14. 백테스트 소유권

- `strategy_performance_run.strategy_id` / `requested_by_user_id` 컬럼 추가
- USER `GET .../performance/runs/{id}`: 타인 개인 결과 403 (공개 전략은 readable 시 허용)
- `POST /user/strategies/{id}/backtest`: 접근 허용 여부 사전 검사

## 15. USER API

| Method | Path |
|--------|------|
| GET/POST | `/api/v1/user/strategies` |
| GET/PUT/DELETE | `/api/v1/user/strategies/{strategy_id}` |
| POST | `/api/v1/user/strategies/{strategy_id}/clone` |
| POST | `/api/v1/user/strategies/{strategy_id}/backtest` |
| GET/POST/DELETE | `/api/v1/user/accounts/{account_id}/strategies[/{strategy_id}]` |

기존 `/user/strategies/ranking` 등 정적 경로는 ownership 라우터보다 **먼저** 등록.

## 16. ADMIN API

| Method | Path |
|--------|------|
| GET/POST | `/api/v1/admin/strategies` |
| PUT | `/api/v1/admin/strategies/{id}` |
| POST | `.../approve` `.../reject` `.../publish` `.../unpublish` `.../activate` `.../deactivate` |

## 17. Frontend 변경

- USER `/user/strategies`: “공용 데이터” Alert 제거 → **내 전략 / 공개 전략** 패널 (CRUD·복제·계좌 연결). 공개는 수정·삭제 버튼 없음
- ADMIN `/admin/strategies`: 정의 목록 + 승인/공개/비공개/비활성 + SYSTEM 생성

## 18. 감사 로그

`AuditLogService.record` — 생성/수정/삭제/복제/연결, ADMIN 승인·공개·활성 변경. 전략 소스·Secret 미저장.

## 19. 변경 파일 (주요)

- `database/alembic/versions/r5e6f7a8b9c0_strategy_ownership.py`
- `src/stock_platform/strategy_deployment/definition_entities.py`
- `src/stock_platform/strategy_deployment/ownership.py`
- `src/stock_platform/strategy_deployment/runtime_*.py`
- `src/stock_platform/api/v1/user_strategy_ownership.py`
- `src/stock_platform/api/v1/user_account_strategies.py`
- `src/stock_platform/api/v1/admin_strategies.py`
- `src/stock_platform/api/router.py`
- FE: `user/strategies/page.tsx`, `admin/strategies/page.tsx`, `userApi.ts`, `adminApi.ts`
- tests: `test_step8_3_*.py`

## 20. 테스트 결과

### Backend

- `tests/test_step8_3_strategy_ownership.py` — 통과
- `tests/test_step8_3_migration_integration.py` — 통과
- `tests/test_dynamic_strategy_runtime_manager.py` — 통과
- Migration down → up → head: **성공**

### Frontend

- vitest **73/73** 통과
- production build **성공**
- `tsc --noEmit`: 이번 변경 오류 없음. 기존 `menu.test.ts` path typing **2건** 잔존 (STEP 무관)

## 21. 운영 DB 적용 방법

```powershell
cd d:\Projects\stock-platform
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m alembic current
```

롤백:

```powershell
.\.venv\Scripts\python.exe -m alembic downgrade q4e5f6a7b8c9
```

## 22. 남은 문제

1. 로컬 DB에 기존 deployment가 없어 SYSTEM 공개 전략이 0건 — 운영은 backfill SQL로 채워짐. 필요 시 ADMIN이 SYSTEM 전략 생성
2. 레거시 전역 runtime 슬롯은 호환용으로 남음 — 모든 스케줄러가 scope_key를 넘기도록 점진 전환 필요 (STEP 8-4 Recovery와 연계 가능)
3. 백테스트 실행 본체가 `requested_by_user_id`를 항상 채우도록 전 경로 보강은 일부 위임(진입 가드 + 컬럼) 상태
4. STEP 8-4 Recovery Runtime — **미착수** (요청에 따라 중지)

## 삭제 정책

- 물리 삭제 대신 `deleted_at` soft delete
- 활성 계좌 연결 있으면 삭제 차단
- 공개 전략은 USER 삭제 차단
- 버전·백테스트 기록은 보존
