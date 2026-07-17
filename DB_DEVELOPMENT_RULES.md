# DB 개발 규칙 — stock-platform

> 대상 프로젝트: `D:\Projects\stock-platform`  
> DBMS: PostgreSQL 17  
> 개발도구: Cursor AI + PostgreSQL MCP + Terminal  
> 운영 방식: Windows 서비스형 PostgreSQL 사용  
> Docker는 사용하지 않는다.

---

# 1. 목적

이 문서는 Cursor AI가 `stock-platform` 프로젝트에서 데이터베이스 관련 개발을 수행할 때 따라야 하는 공통 규칙이다.

핵심 원칙은 다음과 같다.

1. 기존 테이블을 확인하지 않고 새 테이블을 만들지 않는다.
2. DB 직접 수정과 Alembic Migration을 분리하지 않는다.
3. 운영 DB 구조와 SQLAlchemy 모델 구조를 항상 일치시킨다.
4. 테스트용 코드가 운영 테이블을 임의로 변경하지 못하게 한다.
5. 모의투자와 실전투자 데이터가 섞이지 않게 한다.
6. Docker 관련 설정이나 명령을 추가하지 않는다.

---

# 2. 현재 프로젝트 DB 구조

현재 프로젝트는 다음 PostgreSQL Schema를 사용한다.

```text
ai
backtest
broker
common
disclosure
market
news
operation
strategy
trading
public
```

표준 Alembic 경로:

```text
database/alembic/versions/   ← alembic.ini script_location
```

참고용 overlay (적용 금지):

```text
docs/migration-overlays/
alembic/versions/              ← deprecated, chain 미포함
```

Legacy DB 객체:

```text
docs/LEGACY_DB_OBJECTS.md
```

이전에 문서에만 있던 schema 목록(common~public)은 위 목록으로 통합한다.

---

# 3. Cursor DB 작업 시작 순서

Cursor는 DB 관련 기능을 개발하기 전에 반드시 아래 순서를 따른다.

```text
1. 관련 Service 확인
2. 관련 Repository 확인
3. 관련 Entity/Model 확인
4. 기존 Alembic Revision 확인
5. PostgreSQL MCP로 실제 테이블 확인
6. 컬럼·PK·FK·Index·Constraint 확인
7. 기존 기능 재사용 가능 여부 판단
8. 변경 계획 작성
9. Migration 작성
10. Repository/Service/API 수정
11. 테스트 작성
12. Migration 적용 및 검증
```

이 순서를 생략하고 바로 `CREATE TABLE`을 작성하지 않는다.

---

# 4. PostgreSQL MCP 사용 규칙

## 4.1 MCP 접속 계정

가능하면 개발 전용 계정을 사용한다.

예시:

```text
Host: localhost
Port: 5432
Database: stock_platform
User: stock_app
```

Cursor 설정 파일이나 MCP 설정 파일에는 비밀번호를 직접 저장하지 않는다.

비밀번호는 다음 중 하나로 관리한다.

```text
환경변수
Windows Credential Manager
별도 로컬 비밀 설정 파일
```

비밀 설정 파일은 반드시 `.gitignore`에 추가한다.

---

## 4.2 MCP 기본 권한

초기 연결은 아래 권한을 권장한다.

```text
SELECT
INSERT
UPDATE
DELETE
```

개발용 DB에서는 Alembic 적용을 위해 DDL 권한이 필요할 수 있다.

하지만 Cursor가 임의로 아래 작업을 수행하지 못하게 한다.

```text
DROP DATABASE
DROP SCHEMA
TRUNCATE 운영 핵심 테이블
ALTER ROLE
CREATE ROLE
GRANT SUPERUSER
```

---

## 4.3 MCP 조회 우선 원칙

Cursor는 새로운 테이블을 제안하기 전에 다음 SQL을 먼저 실행한다.

### Schema 확인

```sql
SELECT schema_name
FROM information_schema.schemata
WHERE schema_name IN (
    'common',
    'market',
    'trading',
    'news',
    'disclosure',
    'ai',
    'operation'
)
ORDER BY schema_name;
```

### 테이블 확인

```sql
SELECT
    table_schema,
    table_name
FROM information_schema.tables
WHERE table_schema NOT IN ('pg_catalog', 'information_schema')
  AND table_type = 'BASE TABLE'
ORDER BY table_schema, table_name;
```

### 컬럼 확인

```sql
SELECT
    table_schema,
    table_name,
    ordinal_position,
    column_name,
    data_type,
    is_nullable,
    column_default
FROM information_schema.columns
WHERE table_schema = :schema_name
  AND table_name = :table_name
ORDER BY ordinal_position;
```

### PK/FK 확인

```sql
SELECT
    tc.constraint_type,
    tc.constraint_name,
    kcu.column_name,
    ccu.table_schema AS referenced_schema,
    ccu.table_name AS referenced_table,
    ccu.column_name AS referenced_column
FROM information_schema.table_constraints tc
LEFT JOIN information_schema.key_column_usage kcu
       ON tc.constraint_name = kcu.constraint_name
      AND tc.table_schema = kcu.table_schema
LEFT JOIN information_schema.constraint_column_usage ccu
       ON tc.constraint_name = ccu.constraint_name
      AND tc.table_schema = ccu.table_schema
WHERE tc.table_schema = :schema_name
  AND tc.table_name = :table_name
ORDER BY tc.constraint_type, tc.constraint_name;
```

### Index 확인

```sql
SELECT
    schemaname,
    tablename,
    indexname,
    indexdef
FROM pg_indexes
WHERE schemaname = :schema_name
  AND tablename = :table_name
ORDER BY indexname;
```

---

# 5. 신규 테이블 생성 판단 기준

다음 조건을 모두 만족할 때만 신규 테이블을 만든다.

```text
1. 같은 목적의 기존 테이블이 없다.
2. 기존 테이블 컬럼 추가로 해결할 수 없다.
3. JSON 컬럼 하나로 임시 저장하는 방식보다 관계형 구조가 적절하다.
4. Repository와 Service의 책임이 명확하다.
5. 조회 패턴과 보존 기간이 정의되어 있다.
6. PK와 중복 방지 기준이 정의되어 있다.
7. 인덱스 기준이 정의되어 있다.
8. Alembic upgrade/downgrade가 작성된다.
9. 테스트가 작성된다.
```

신규 테이블이 불필요한 대표 사례:

```text
기존 테이블에 상태 컬럼 하나만 추가하면 되는 경우
기존 History 테이블로 충분한 경우
동일 데이터를 이름만 바꿔 다시 저장하는 경우
Repository 중복 때문에 새 테이블을 만드는 경우
임시 디버깅 데이터를 저장하려는 경우
```

---

# 6. STEP35~STEP40 신규 테이블 판단

## STEP35

원칙적으로 신규 테이블을 만들지 않는다.

주요 작업:

```text
Alembic 경로 통합
중복 Migration 확인
Schema 구조 확인
기존 Entity와 실제 DB 비교
```

예외:

- 애플리케이션 기동 이력이나 Migration 이력을 별도 관리해야 한다는 명확한 요구가 생긴 경우

하지만 기존 `operation.job_run_history` 또는 유사 테이블을 우선 검토한다.

---

## STEP36

시장 데이터 관련 기존 테이블을 우선 사용한다.

이미 확인된 Migration 예:

```text
create_market_instrument_table
create_market_price_daily_table
```

다음 테이블이 실제로 존재하는지 먼저 확인한다.

```text
market.instrument
market.price_daily
market.candle_daily
market.candle_minute
market.quote
market.trade
market.orderbook
```

신규 생성 가능성이 있는 영역:

```text
분봉
실시간 Quote
실시간 Trade
Orderbook Snapshot
수집 Checkpoint
데이터 품질 오류
```

하지만 동일 목적 테이블이 있으면 절대 재생성하지 않는다.

---

## STEP37

이미 확인된 Migration 예:

```text
create_ai_candidate_analysis_tables
create_candidate_screening_tables
create_news_article_and_summary_tables
create_dart_disclosure_table
```

따라서 아래 테이블을 새로 만들기 전에 반드시 기존 구조를 확인한다.

```text
ai candidate analysis
candidate screening run/result
news article/summary
dart disclosure
strategy selection run
```

신규 테이블보다는 기존 테이블에 다음 필드를 추가하는 방식을 우선 검토한다.

```text
prompt_version
model_name
context_hash
confidence
risk_flags
invalidation_conditions
analysis_started_at
analysis_completed_at
```

---

## STEP38

이미 확인된 Migration 예:

```text
create_trading_order_tables
create_paper_order_table
create_broker_pending_order_table
create_broker_account_snapshot_tables
create_position_limit_table
create_risk_event_table
create_persistent_kill_switch_tables
create_live_trading_transition_table
create_paper_account_position_and_trade
create_risk_policy_and_position_plan
create_broker_recovery_tables
```

따라서 주문·체결·포지션·리스크용 새 테이블을 임의로 만들지 않는다.

신규 테이블보다는 다음을 먼저 확인한다.

```text
기존 주문 상태 컬럼
Execution 저장 구조
부분체결 처리 구조
Position Snapshot 구조
Risk Event 구조
Kill Switch 상태
Live Transition 승인 이력
```

---

## STEP39

이미 확인된 Migration 예:

```text
create_job_run_history_table
create_pipeline_run_tables
create_daily_operations_report_table
```

신규 생성 가능성이 있는 영역:

```text
notification_delivery
notification_failure
audit_log
system_component_health_history
```

하지만 알림 발송 이력과 운영 이력이 기존 Job/Pipeline/Report 테이블로 처리 가능한지 먼저 확인한다.

---

## STEP40

신규 테이블을 만들지 않는다.

STEP40은 다음 작업에 집중한다.

```text
Migration 검증
Schema 비교
Index 검증
데이터 보존 정책
Backup/Restore 검증
Release 점검
```

---

# 7. Alembic Migration 규칙

## 7.1 Migration 파일 위치

STEP35에서 최종 확정 전까지 새 Migration을 두 경로에 중복 생성하지 않는다.

후보 경로:

```text
database/alembic/versions/
```

금지:

```text
database/alembic/versions/와 alembic/versions/에 같은 변경을 이중 생성
```

---

## 7.2 Revision 이름

파일명은 기능이 드러나야 한다.

예:

```text
<revision>_add_market_minute_candle_table.py
<revision>_add_ai_analysis_context_hash.py
<revision>_add_notification_delivery_table.py
```

금지:

```text
update_table.py
fix_db.py
new_change.py
step36.py
```

---

## 7.3 upgrade와 downgrade

모든 Migration은 `upgrade()`와 `downgrade()`를 작성한다.

```python
def upgrade() -> None:
    ...

def downgrade() -> None:
    ...
```

다운그레이드가 데이터 손실을 발생시키는 경우 파일 상단 주석과 개발 보고서에 명시한다.

---

## 7.4 Schema 명시

PostgreSQL 다중 Schema를 사용하므로 테이블 생성 시 반드시 Schema를 명시한다.

```python
op.create_table(
    "example_table",
    ...,
    schema="market",
)
```

Index와 Constraint도 Schema를 정확히 지정한다.

---

## 7.5 중복 방지

Migration 작성 전 다음을 실행한다.

```powershell
alembic current
alembic heads
alembic history
```

`alembic heads` 결과는 원칙적으로 하나여야 한다.

두 개 이상이면 새 기능 개발보다 head 병합과 revision chain 정리를 먼저 수행한다.

---

## 7.6 Migration 적용 검증

개발 DB:

```powershell
alembic upgrade head
```

검증:

```powershell
alembic current
alembic heads
```

가능한 경우 별도의 빈 테스트 DB에서 다음을 검증한다.

```text
빈 DB 생성
전체 upgrade head
핵심 테이블 확인
최신 revision downgrade
다시 upgrade head
```

Docker는 사용하지 않는다.

테스트 DB는 로컬 PostgreSQL에 별도 Database로 만든다.

예:

```text
stock_platform_test
```

---

# 8. 테이블 설계 규칙

## 8.1 테이블명

```text
영문 소문자
snake_case
복수형과 단수형은 기존 프로젝트 규칙에 맞춤
```

신규 테이블 이름을 정하기 전에 같은 Schema의 기존 이름 규칙을 확인한다.

---

## 8.2 PK

기본 선택:

```text
BIGINT Identity
UUID
업무상 자연키
```

무조건 UUID를 사용하거나 무조건 숫자형을 사용하지 않는다.

대량 시계열 테이블은 저장량과 인덱스 크기를 고려한다.

---

## 8.3 시간 컬럼

권장:

```text
created_at
updated_at
occurred_at
collected_at
started_at
completed_at
```

PostgreSQL 타입:

```text
TIMESTAMP WITH TIME ZONE
```

저장 기준:

```text
UTC 저장
API/화면에서 Asia/Seoul 변환
```

날짜만 필요한 시장 거래일:

```text
DATE
```

---

## 8.4 금액과 수량

금액, 가격, 수량, 비율에는 `FLOAT` 사용을 피한다.

권장:

```text
NUMERIC(20, 8)
NUMERIC(24, 12)
BIGINT
```

가격과 수량 정밀도는 시장별 특성에 맞춘다.

---

## 8.5 상태값

상태값을 자유 문자열로 저장하지 않는다.

예:

```text
PENDING
SUBMITTED
PARTIALLY_FILLED
FILLED
CANCELED
REJECTED
FAILED
```

다음 중 프로젝트 기존 규칙을 따른다.

```text
CHECK Constraint
PostgreSQL Enum
애플리케이션 Enum + VARCHAR
```

---

## 8.6 JSONB

JSONB는 아래 경우에만 사용한다.

```text
외부 API 원문 보존
모델별 가변 AI 분석 상세
규격이 자주 변경되는 메타데이터
```

검색·조인·집계에 자주 사용하는 값은 일반 컬럼으로 분리한다.

---

## 8.7 삭제 정책

거래·체결·리스크·감사 데이터는 물리 삭제를 기본으로 하지 않는다.

가능하면 다음 방식 중 하나를 사용한다.

```text
status 변경
is_active
deleted_at
valid_from / valid_to
```

시장 원시 데이터와 임시 캐시는 보존 정책을 별도로 정의한다.

---

# 9. Index 규칙

Index는 실제 조회 조건을 기준으로 만든다.

대표 기준:

```text
symbol + trade_date
market_code + symbol
status + created_at
run_id
strategy_id
broker_order_id
client_order_id
occurred_at
```

다음은 지양한다.

```text
모든 컬럼에 Index 생성
중복 Index 생성
낮은 선택도의 boolean 단일 Index
사용되지 않는 복합 Index
```

복합 Index의 컬럼 순서는 실제 WHERE, JOIN, ORDER BY를 기준으로 정한다.

---

# 10. Unique Constraint 규칙

외부 데이터 중복 방지 키를 명확히 한다.

예:

```text
시장 + 종목 + 거래일
시장 + 종목 + 캔들주기 + 시각
Broker + 계좌 + Broker 주문번호
공시 접수번호
뉴스 원문 URL Hash
AI Run + 종목
Job Name + 기준일 + 실행회차
```

애플리케이션 코드만으로 중복을 막지 않고 DB Constraint도 사용한다.

---

# 11. FK 규칙

FK는 데이터 무결성이 중요할 때 사용한다.

하지만 초대량 시계열 데이터에 무분별하게 FK를 추가하지 않는다.

삭제 규칙을 명시한다.

```text
RESTRICT
CASCADE
SET NULL
```

거래 데이터에서 무분별한 `ON DELETE CASCADE`는 금지한다.

---

# 12. SQLAlchemy 규칙

## 12.1 공통 Base와 Mixins 사용

현재 프로젝트 경로:

```text
src/stock_platform/database/base.py
src/stock_platform/database/mixins.py
src/stock_platform/database/session.py
```

신규 Entity는 기존 Base와 Mixins를 우선 사용한다.

별도의 Base를 새로 만들지 않는다.

---

## 12.2 Entity와 API Model 분리

다음을 혼용하지 않는다.

```text
SQLAlchemy Entity
Pydantic Request
Pydantic Response
Domain Model
```

각 역할을 분리한다.

---

## 12.3 Repository 책임

Repository는 다음 작업만 담당한다.

```text
조회
저장
수정
삭제 또는 상태 변경
DB Transaction 참여
```

Repository 내부에서 아래 작업을 하지 않는다.

```text
외부 API 호출
Ollama 호출
주문 전략 판단
알림 발송
복잡한 비즈니스 규칙
```

---

## 12.4 Transaction

여러 테이블 변경이 하나의 업무 단위면 같은 Transaction에서 처리한다.

예:

```text
Order 저장
Outbox 저장
Risk Event 저장
```

실패 시 모두 rollback되어야 한다.

---

# 13. 기존 중복 구조 처리 규칙

현재 프로젝트에는 다음과 같은 중복 후보가 존재한다.

```text
market / markets
indicator / indicators
risk / risk_engine
broker / brokers
strategy / strategies / strategy_deployment
```

Cursor는 중복 구조를 발견해도 즉시 삭제하지 않는다.

처리 순서:

```text
1. import 사용처 검색
2. API 사용처 검색
3. 테스트 사용처 검색
4. DB Entity 연결 확인
5. 표준 패키지 결정
6. compatibility import 제공
7. 단계적으로 이전
8. 테스트 통과 후 구형 코드 제거
```

---

# 14. 테스트 DB 규칙

로컬 PostgreSQL에 테스트 DB를 별도로 사용한다.

권장 DB:

```text
stock_platform_test
```

운영 개발 DB:

```text
stock_platform
```

테스트 실행 시 실전 계좌, 실전 주문, 실제 Broker 주문 API를 사용하지 않는다.

필수 환경변수 예:

```dotenv
APP_ENV=test
KIWOOM_USE_MOCK=true
KIWOOM_LIVE_ORDER_ENABLED=false
```

테스트는 각 실행 후 데이터를 rollback하거나 고유한 test run id로 격리한다.

---

# 15. Cursor가 DB를 변경할 때 보고할 내용

Cursor는 DB 변경 작업 완료 후 반드시 다음 형식으로 보고한다.

```text
[DB 변경 보고]

1. 변경 목적
2. 기존 테이블 조사 결과
3. 신규/변경 테이블
4. 추가/변경 컬럼
5. PK/FK/Unique/Index
6. Alembic Revision
7. upgrade 결과
8. downgrade 결과
9. Repository 변경
10. Service/API 변경
11. 테스트 결과
12. 데이터 손실 가능성
13. 수동 작업 필요 여부
```

---

# 16. 금지사항

Cursor는 다음 작업을 사용자 승인 없이 수행하지 않는다.

```text
운영 DB DROP
Schema DROP
대량 데이터 TRUNCATE
기존 거래/체결 이력 삭제
Migration 파일 임의 재작성
적용 완료된 Revision ID 변경
실전 계좌 데이터 초기화
실전 주문 활성화
비밀번호 소스코드 저장
DB 접속정보 Git Commit
Docker 설정 추가
docker-compose.yml 생성
Docker 기반 PostgreSQL 전환
```

---

# 17. Windows 실행 명령 기준

이 프로젝트는 Docker를 사용하지 않는다.

PostgreSQL은 Windows 서비스로 실행한다.

## PostgreSQL 접속

```powershell
& "D:\Programs\PostgreSQL\17\bin\psql.exe" `
  -U stock_app `
  -d stock_platform
```

## 테스트 DB 접속

```powershell
& "D:\Programs\PostgreSQL\17\bin\psql.exe" `
  -U stock_app `
  -d stock_platform_test
```

## Alembic 상태 확인

프로젝트 루트:

```powershell
Set-Location D:\Projects\stock-platform
```

가상환경 활성화:

```powershell
.\.venv\Scripts\Activate.ps1
```

Alembic 확인:

```powershell
alembic current
alembic heads
alembic history
```

Migration 적용:

```powershell
alembic upgrade head
```

테스트:

```powershell
pytest -m "not external and not live"
```

---

# 18. STEP35 Cursor 시작 지시문

아래 내용을 Cursor에 그대로 전달한다.

```text
DB_DEVELOPMENT_RULES.md와
STEP35_TO_STEP40_DEVELOPMENT_ROADMAP.md를 먼저 읽으세요.

현재 프로젝트는 Docker를 사용하지 않습니다.
Dockerfile, docker-compose.yml, Docker 기반 PostgreSQL 설정을
추가하거나 제안하지 마세요.

STEP35에서는 신규 테이블을 먼저 만들지 마세요.

먼저 다음을 수행하세요.

1. alembic.ini 확인
2. database/alembic/env.py 확인
3. alembic/versions와 database/alembic/versions 비교
4. alembic heads/current/history 실행
5. PostgreSQL MCP로 실제 Schema와 테이블 조회
6. SQLAlchemy Entity와 실제 테이블 비교
7. 중복 Migration과 중복 테이블 후보 정리
8. DB 변경 계획 보고

사용자 승인 전 Migration을 적용하거나
기존 테이블을 삭제하지 마세요.
```

---

# 19. 최종 원칙

```text
기존 DB 확인이 먼저다.
신규 테이블 생성은 마지막 선택이다.
Schema 변경은 반드시 Alembic으로 관리한다.
실제 DB와 Entity를 항상 일치시킨다.
모의투자와 실전투자를 분리한다.
Docker는 사용하지 않는다.
```
