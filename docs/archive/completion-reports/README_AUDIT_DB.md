# README_AUDIT_DB.md — Database 전체 감사 보고서

| 항목 | 내용 |
|------|------|
| **감사일** | 2026-07-21 |
| **근거** | 라이브 PostgreSQL MCP 조회 + `database/alembic/versions` + ORM(`src/stock_platform`) |
| **원칙** | **코드·DB 수정 없음.** 관찰·권고만 기록 |
| **Alembic head (DB)** | `operation.alembic_version` = `g3b4c5d6e7f8` |
| **Alembic script_location** | `alembic.ini` → `database/alembic` (단일 head, base `21ef733dc7ca`, revision **58**) |

---

## 0. 인벤토리 요약

### 0.1 스키마·테이블 규모

| Schema | Tables | Approx total size |
|--------|--------|-------------------|
| ai | 6 | 184 kB |
| auth | 8 | 464 kB |
| backtest | 3 | 48 kB |
| disclosure | 4 | 3.0 MB |
| market | 7 | **73 MB** |
| news | 5 | 424 kB |
| notification | 3 | 88 kB |
| operation | 18 | 1.2 MB |
| strategy | 4 | 128 kB |
| trading | 25 | 792 kB |
| **합계** | **83** | — |

빈 스키마(테이블 0): `broker`, `common`, `public`

### 0.2 객체 카운트 (앱 스키마)

| 객체 | 수량 | 비고 |
|------|------|------|
| Tables | 83 | `operation.alembic_version` 포함 |
| Indexes (`pg_indexes`) | 201 | PK unique index 포함 |
| PRIMARY KEY | 83 | 테이블당 1개 (복합 PK 일부 포함 가능) |
| FOREIGN KEY | **50** | `*_id` 논리 참조 대비 부족 |
| UNIQUE | 49 | |
| CHECK | 20 | |
| Sequences | **71** | 전부 `bigint`, NO CYCLE |
| Triggers | **0** | |
| Views | **0** | |
| Materialized Views | **0** | |
| Functions (앱 스키마) | **0** | |
| Procedures | **0** | |
| PostgreSQL ENUM types | **0** | 상태값은 `varchar` + CHECK/앱 enum |
| Table comments | **16** / 83 | |
| Column comments | **23** | |

### 0.3 ORM 매핑

- ORM `__tablename__` 모델: **81**
- DB 전용·ORM 없음: `operation.system_health`, `operation.alembic_version`
- ORM ↔ 비즈니스 테이블은 대체로 1:1 (system_health 제외)

### 0.4 주요 데이터 테이블 (approx rows)

| 테이블 | rows | size |
|--------|------|------|
| `market.price_daily` | ~174,992 | 28 MB |
| `market.indicator_daily` | ~83,273 | 44 MB |
| `disclosure.dart_disclosure` | ~1,935 | 3 MB |
| `operation.audit_event` | ~605 | 464 kB |
| `operation.broker_recovery_run` | ~344 | 128 kB |
| `market.instrument` | ~270 | 328 kB |
| `news.news_article` | ~100 | 232 kB |
| 다수 trading/strategy/ai | 0 | 골격만 |

---

## 전체 테이블 목록

### ai (6)
`candidate_analysis_result`, `candidate_analysis_run`, `recommendation_request`, `recommendation_result`, `strategy_selection_run`, `user_recommendation_state`

### auth (8)
`permission`, `refresh_token`, `role`, `role_permission`, `user`, `user_connection`, `user_preference`, `user_role`

### backtest (3)
`backtest_equity`, `backtest_run`, `backtest_trade`

### disclosure (4)
`dart_corp`, `dart_disclosure`, `disclosure_ai_summary`, `user_disclosure_state`

### market (7)
`candle_minute`, `indicator_daily`, `instrument`, `orderbook_snapshot`, `price_daily`, `quote_snapshot`, `trade_tick`

### news (5)
`collection_failure`, `news_article`, `news_article_symbol`, `news_summary`, `user_news_state`

### notification (3)
`notification`, `notification_subscription`, `user_notification`

### operation (18)
`alembic_version`, `app_setting`, `app_setting_history`, `audit_event`, `broker_recovery_run`, `broker_recovery_step`, `daily_operations_report`, `idempotency_key`, `job_run_history`, `kill_switch`, `kill_switch_history`, `live_trading_transition`, `pipeline_run`, `pipeline_step_run`, `position_limit`, `risk_event`, `system_health`, `trading_calendar_day`

### strategy (4)
`candidate_result`, `candidate_run`, `position_plan`, `risk_policy`

### trading (25)
`broker_account_snapshot`, `broker_pending_order`, `broker_position_snapshot`, `execution`, `order_outbox`, `paper_account`, `paper_order`, `paper_position`, `paper_trade`, `portfolio_snapshot`, `strategy_approval_run`, `strategy_deployment`, `strategy_deployment_history`, `strategy_deployment_performance`, `strategy_deployment_pipeline`, `strategy_leaderboard_entry`, `strategy_leaderboard_snapshot`, `strategy_performance_metric`, `strategy_performance_run`, `strategy_runtime_switch`, `trading_order`, `trading_order_status_history`, `user_broker_account`, `walk_forward_window_metric`, `watchlist`

---

## Index / FK / PK / Sequence / 기타 객체

### Indexes
- 총 **201**개 (`pg_indexes`)
- 핵심 unique: instrument(exchange,symbol), paper_position(account,symbol), watchlist(user,market,symbol), outbox/execution broker id 등
- **실중복 후보**: `auth.user` username (`uq_user_username` + `ix_auth_user_username`), `market.orderbook_snapshot` (`uq_*` + `ix_*` 동일 키)

### Foreign Keys (50) — ON DELETE 요약
- 다수 **CASCADE** (auth 소유권·자식, market→instrument, news/disclosure state 등)
- **SET NULL**: `paper_account.user_id`, `paper_trade.order_id`, `position_plan.policy_id`, `trading_order.strategy_deployment_id`, AI parent run 등
- **ON DELETE 미지정(NO ACTION)**: `trading.execution.order_id`, `trading.order_outbox.order_id` — 주문 삭제 시 체결/아웃박스 차단 의도 가능

### Primary Keys
- 비즈니스 테이블마다 surrogate PK (`*_id` bigint Identity/sequence) 중심
- 조인/상태 테이블은 복합 unique + 별도 surrogate PK 혼용 (`role_permission`, `user_role` 등)

### Sequences (71)
- 스키마별 Identity/serial 소유 시퀀스
- 이름 잘림 예: `strategy_deployment_performan_strategy_deployment_performan_seq` (PostgreSQL 63자 제한)

### Triggers / Views / MV / Functions / Procedures / Enums
- **모두 0** (앱 스키마 기준)
- 상태·유형은 **varchar + 애플리케이션 StrEnum/CHECK**로 관리

---

## Migration 인벤토리

| 구분 | 내용 |
|------|------|
| 활성 경로 | `database/alembic/versions/*.py` — Alembic graph **58 revisions**, head `g3b4c5d6e7f8` |
| DB version | `operation.alembic_version.version_num = g3b4c5d6e7f8` (일치) |
| 비활성/오버레이 | `alembic/versions/` 및 `docs/migration-overlays/` — placeholder `REPLACE_WITH_*` 포함, **script_location 밖** |
| 유사 파일명 | news·job_run_history 등 create 파일이 체인으로 연속(후속이 alter/재생성) — head 단일로 충돌 없음 |

---

# 확인사항 (1–15)

각 항목: **위치 / 문제 / 영향도 / 수정방법**

영향도: Critical · High · Medium · Low

---

## 1. 사용되지 않는 테이블

### 1.1 `operation.system_health`

| 항목 | 내용 |
|------|------|
| **위치** | DB: `operation.system_health` (1 row) — ORM 매핑 **없음** |
| **문제** | 레거시 헬스 스냅샷으로 보이며 코드베이스에서 미사용. |
| **영향도** | Medium |
| **수정방법** | LEGACY 문서 유지 후 drop 마이그레이션, 또는 ORM/모니터링에 재연결. |

### 1.2 빈 스키마 `broker`, `common`

| 항목 | 내용 |
|------|------|
| **위치** | PostgreSQL schemas `broker`, `common` (테이블 0) |
| **문제** | 초기 스키마 생성 잔존. 실제 브로커 데이터는 `trading`/`operation`에 존재. |
| **영향도** | Low |
| **수정방법** | 문서화 후 `DROP SCHEMA` 또는 향후 사용 계획 명시. |

### 1.3 상시 0행·미활성 도메인 테이블

| 항목 | 내용 |
|------|------|
| **위치** | 예: `backtest.*`, `strategy.position_plan`, `trading.strategy_*` 다수, `market.candle_minute`/`quote_snapshot`/`trade_tick`, AI/notification 일부 |
| **문제** | “미사용”이 아니라 **미적재/미기동**. 스키마는 ORM·API와 연결됨. |
| **영향도** | Low (용량) / Medium (운영 혼동) |
| **수정방법** | 제품 사용 여부에 따라 아카이브 또는 시드/잡 활성화. 삭제 전 참조 그래프 확인. |

### 1.4 `operation.alembic_version`

| 항목 | 내용 |
|------|------|
| **위치** | `operation.alembic_version` |
| **문제** | 미사용이 아님 — Alembic 메타. public이 아닌 operation 스키마에 위치. |
| **영향도** | Low (관례 이슈) |
| **수정방법** | 현행 유지. 문서에 version 테이블 위치 명시. |

---

## 2. FK 누락

논리 `*_id`이나 FK 없는 **핵심 후보** (PK·외부시스템 ID 제외 후):

### 2.1 전략 배포 그래프

| 항목 | 내용 |
|------|------|
| **위치** | `trading.strategy_deployment.strategy_performance_run_id`, `replaced_by_deployment_id` · `strategy_approval_run.{deployment_id,strategy_performance_run_id,strategy_selection_run_id}` · `strategy_deployment_pipeline.*` · `strategy_runtime_switch.{previous,target}_deployment_id` · `strategy_leaderboard_entry.*` · `strategy_performance_metric.strategy_performance_run_id` · `walk_forward_window_metric.strategy_performance_run_id` · `ai.strategy_selection_run.selected_performance_run_id` |
| **문제** | 전략 승인·배포·리더보드·WF 체인에 **DB 무결성 없음**. 고아 ID·잘못된 참조 가능. |
| **영향도** | **High** |
| **수정방법** | 대상 PK로 FK 추가(삭제 정책: RESTRICT/SET NULL). 기존 orphan 데이터 정리 후 적용. |

### 2.2 주문·계좌 참조

| 항목 | 내용 |
|------|------|
| **위치** | `trading.trading_order.{account_id,original_order_id,replaced_order_id,portfolio_id,position_id}` · `ai.recommendation_request.account_id` · `auth.user_preference.{default_account_id,default_watchlist_id}` · `trading.paper_order.position_plan_id` · `operation.audit_event.order_id` |
| **문제** | 앱 레벨 ownership에 의존. preference/default가 깨진 ID를 가리킬 수 있음. `trading_order.account_id`가 paper/live 중 어디인지 FK로 고정되지 않음. |
| **영향도** | **High** |
| **수정방법** | paper면 `paper_account` FK, preference는 `paper_account`/`watchlist` FK(SET NULL). 주문 자기참조 FK 추가. |

### 2.3 `trading.paper_order`에 `account_id` 자체 부재

| 항목 | 내용 |
|------|------|
| **위치** | `trading.paper_order` 컬럼 목록 — **account_id 없음**, FK도 PK만 존재 |
| **문제** | 모의 주문이 계좌에 DB로 귀속되지 않음. `paper_trade`만 account FK. 멀티유저 격리·조회·정합성이 취약. |
| **영향도** | **Critical** (멀티 계좌/유저 전제 시) |
| **수정방법** | `account_id NOT NULL` + FK(`paper_account`) + 인덱스 마이그레이션. 기존 행 백필 전략 필요. |

### 2.4 FK는 있으나 supporting index 약한 컬럼

| 항목 | 내용 |
|------|------|
| **위치** | `ai.candidate_analysis_run.parent_analysis_run_id`, `source_candidate_run_id` · `operation.broker_recovery_step.broker_recovery_run_id` · `strategy.position_plan.policy_id` · `trading.paper_trade.order_id` · `trading.strategy_deployment_performance.strategy_deployment_id` |
| **문제** | FK 존재하나 선행 인덱스 미흡 가능 → DELETE/JOIN 시 seq scan. |
| **영향도** | Medium |
| **수정방법** | FK 컬럼 단일/복합 인덱스 추가. |

---

## 3. Index 누락

| 항목 | 내용 |
|------|------|
| **위치** | §2.4 FK 미인덱스 · `trading.trading_order`의 미FK `account_id` 조회 패턴 · 대용량 `market.price_daily`/`indicator_daily`의 미사용 조회 키(운영 쿼리 기준 재확인) |
| **문제** | 자식 삭제·계좌별 주문 목록·복구 스텝 조회 시 성능 저하 가능. |
| **영향도** | Medium–High (`price_daily`/`indicator_daily` 규모) |
| **수정방법** | `pg_stat_user_indexes` / 슬로우 쿼리 기준으로 covering index. FK 컬럼은 기본 인덱스 정책화. |

---

## 4. Index 중복

### 4.1 동일 키 Unique + Non-unique

| 항목 | 내용 |
|------|------|
| **위치** | `auth.user`: `uq_user_username` + `ix_auth_user_username` (둘 다 UNIQUE on username) · `market.orderbook_snapshot`: `uq_orderbook_snapshot_instrument_captured` + `ix_orderbook_snapshot_instrument_captured` |
| **문제** | 저장·쓰기 오버헤드 이중. |
| **영향도** | Medium |
| **수정방법** | unique만 남기고 non-unique(또는 중복 unique) drop. |

### 4.2 Partial unique와 일반 index 공존 (정상 가능)

| 항목 | 내용 |
|------|------|
| **위치** | `trading.paper_account`: `ix_paper_account_user_id` + `uq_paper_account_user_default` (WHERE is_default) |
| **문제** | 완전 중복은 아님. user_id 조회용 ix는 유지 가치 있음. |
| **영향도** | Low |
| **수정방법** | 유지. 문서에 역할 구분. |

---

## 5. Cascade 문제

| 항목 | 내용 |
|------|------|
| **위치** | market: instrument **ON DELETE CASCADE** → price/indicator/candle/tick/orderbook/quote · auth user CASCADE → refresh/roles/watchlist/notifications 등 · paper_account CASCADE → positions/trades/snapshots |
| **문제** | instrument 실수로 삭제 시 **시세·지표 대량 삭제**. user 삭제 시 광범위 cascade(의도일 수 있으나 복구 어려움). |
| **영향도** | **High** |
| **수정방법** | 마스터(instrument/user)는 RESTRICT + soft delete. 자식만 CASCADE. 운영 delete 권한 최소화. |

### 5.1 주문-체결 NO ACTION

| 항목 | 내용 |
|------|------|
| **위치** | `execution`/`order_outbox` → `trading_order` (ON DELETE 없음) |
| **문제** | 주문 hard delete 불가 → 감사 관점 양호. orphan cleanup 경로 필요. |
| **영향도** | Low–Medium |
| **수정방법** | 현행 유지 권장. 삭제 대신 상태 전이. |

---

## 6. Nullable 문제

| 항목 | 내용 |
|------|------|
| **위치** | `trading.paper_account.user_id` NULL 허용(SET NULL) · `paper_order`에 account 미연결 · preference default_* NULL · 다수 strategy_*_id NULL |
| **문제** | 소유권 NULL paper 계좌·고아 주문·깨진 기본값 가능. |
| **영향도** | High |
| **수정방법** | 신규 계좌 `user_id NOT NULL`. paper_order에 account_id NOT NULL. default_*는 FK+존재 검증. |

---

## 7. PK 설계 문제

| 항목 | 내용 |
|------|------|
| **위치** | 전역적으로 `bigint` surrogate PK · 일부 시퀀스 이름 63자 truncate |
| **문제** | Surrogate PK 자체는 양호. 시퀀스 이름 가독성 저하. `quote_snapshot` 등 자연키가 PK가 아닐 수 있음(별도 확인 불필요 수준). |
| **영향도** | Low |
| **수정방법** | 신규 테이블은 짧은 PK 컬럼명. 기존 truncate 시퀀스는 rename 가능하나 위험 낮음. |

---

## 8. Naming 문제

| 항목 | 내용 |
|------|------|
| **위치** | 스키마 `broker`/`common` 공허 vs 테이블은 `trading` · `auth."user"` 예약어 인용 · FK/인덱스 prefix 혼재(`fk_`/`ix_`/`uq_`) · 시퀀스 truncate |
| **문제** | 온보딩·autogenerate·교차 스키마 조인 시 혼란. |
| **영향도** | Medium |
| **수정방법** | 네이밍 가이드 고정. 빈 스키마 정리. `user` 테이블명 변경은 비용 큼 → 문서화. |

---

## 9. Data Type 문제

| 항목 | 내용 |
|------|------|
| **위치** | 상태/코드 다수 `varchar(n)` (ENUM 0) · 금액 `numeric(20/28,8)` · ID `bigint` |
| **문제** | varchar 상태는 DB 레벨 허용값 약함(CHECK 20개뿐). 앱 enum과 drift 가능. |
| **영향도** | Medium |
| **수정방법** | 핵심 status에 CHECK 또는 PG ENUM 도입. money scale 문서화(8 vs 통화). |

---

## 10. Timestamp 문제

| 항목 | 내용 |
|------|------|
| **위치** | timestamptz 컬럼 **172**, timestamp without time zone **0** |
| **문제** | TZ 정책은 **양호**(전부 timestamptz). 다만 `created_at`/`updated_at` 누락 테이블 다수(§12). |
| **영향도** | Low (타입) / Medium (컬럼 누락) |
| **수정방법** | 현행 timestamptz 유지. audit 컬럼 표준 적용. |

---

## 11. Soft Delete 문제

| 항목 | 내용 |
|------|------|
| **위치** | Soft delete 명시: `auth.user.deleted_at`, `notification.user_notification.is_deleted`(+archived_at) · 그 외 대부분 hard delete / CASCADE |
| **문제** | 정책 불통일. user soft delete 후에도 CASCADE 자식은 별도 정책 필요. instrument 등 마스터는 soft delete 없음. |
| **영향도** | Medium |
| **수정방법** | 마스터/계정 soft delete 표준. 자식은 보존 또는 익명화. 알림 is_deleted와 user deleted_at 정책 문서화. |

---

## 12. Audit 컬럼 누락

`created_at` / `updated_at` 부재 예:

| 테이블 | created | updated |
|--------|---------|---------|
| `auth.role_permission`, `auth.user_role` | ✗ (assigned_at만) | ✗ |
| `backtest.backtest_equity`, `backtest_trade` | ✗ | ✗ |
| `news.collection_failure` | ✗ (failed_at만) | ✗ |
| `operation.broker_recovery_*`, `pipeline_*`, `live_trading_transition`, `system_health` | ✗/부분 | ✗ |
| `trading.broker_*_snapshot`, `broker_pending_order`, `paper_trade`, `strategy_performance_run`, `strategy_leaderboard_snapshot` | ✗/부분 | ✗ |

| 항목 | 내용 |
|------|------|
| **위치** | 위 표 및 §0.3 audit flag 조회 결과 |
| **문제** | 변경 추적·운영 디버깅 어려움. history 테이블과 본 테이블 비대칭. |
| **영향도** | Medium |
| **수정방법** | 변경 가능 엔티티에 `created_at`/`updated_at` NOT NULL DEFAULT now() 표준. 불변 로그는 created만. |

---

## 13. Comment 누락

| 항목 | 내용 |
|------|------|
| **위치** | Table comment **16/83**, Column comment **23** (전역적으로 희소). 일부 trading/operation/auth.user만 주석 |
| **문제** | DBA·신규 개발자 온보딩·MCP/문서 자동화에 불리. |
| **영향도** | Low–Medium |
| **수정방법** | 스키마별 COMMENT ON TABLE/COLUMN 마이그레이션 배치. |

---

## 14. Migration 충돌

| 항목 | 내용 |
|------|------|
| **위치** | 활성: `database/alembic` 단일 head `g3b4c5d6e7f8` = DB · 비활성: `alembic/versions/*` placeholder · `docs/migration-overlays/*` |
| **문제** | **활성 체인 충돌 없음.** 다만 루트 `alembic/versions`·overlay를 잘못 적용하면 충돌/이중 적용 위험. |
| **영향도** | Medium (프로세스) |
| **수정방법** | overlay/legacy 경로 README에 “적용 금지” 명시. CI에서 `alembic heads` == 1 검증. |

### 14.1 유사 create 파일

| 항목 | 내용 |
|------|------|
| **위치** | `9193f9b0bc0e` → `234f43fd1557` (news) · `8fe17ae5b326` → `86706db6ba99` (job_run_history) |
| **문제** | 파일명이  alike하나 **체인으로 연결**되어 정상. |
| **영향도** | Low |
| **수정방법** | 파일명/docstring에 “follow-up alter” 명시. |

---

## 15. Alembic 문제

| 항목 | 내용 |
|------|------|
| **위치** | `alembic.ini` `script_location=database/alembic` · version 테이블 `operation.alembic_version` · env.py 모델 import 범위(과거 감사: autogenerate drift 가능) · 이중 디렉터리 |
| **문제** | 1) 레거시 `alembic/versions` 혼동 2) version table 스키마가 non-default 3) autogenerate 시 미import 모델 → false diff 4) 그린필드 시 스키마 CREATE 누락 revision 존재 가능(과거 문서) |
| **영향도** | **High** (운영 실적용 시) |
| **수정방법** | 단일 versions 경로만 유지. `alembic check`/`heads` CI. env.py에 전 ORM import. 신규 환경 bootstrap 문서와 스키마 CREATE 검증. |

---

## 우선순위 백로그

1. **P0 / Critical** — `paper_order.account_id`(+FK) 도입 · 전략 배포/리더보드/승인 FK 보강  
2. **P1 / High** — instrument/user CASCADE → RESTRICT+soft delete 재검토 · preference/default_* FK · 중복 username/orderbook 인덱스 제거  
3. **P2 / Medium** — FK supporting index · audit 컬럼 표준 · system_health/빈 스키마 정리 · Alembic 경로 단일화  
4. **P3 / Low** — COMMENT 배치 · PG ENUM/CHECK 강화 · View/MV는 필요 시 성능 레이어로만 도입  

---

## 결론

DB는 **스키마 분리·timestamptz 일관성·Alembic head 일치** 측면에서 성숙하다.  
잔여 핵심 부채는 (1) **논리 FK 대비 실제 FK 50개로 부족**(특히 strategy·trading_order·preference), (2) **`paper_order`의 계좌 비귀속**, (3) **마스터 CASCADE 파괴력**, (4) **system_health/빈 스키마·인덱스 중복·코멘트 희소**, (5) **레거시 alembic overlay 경로 혼동**이다.

본 문서는 감사 전용이며 **어떠한 DB/코드 수정도 수행하지 않았다.**
