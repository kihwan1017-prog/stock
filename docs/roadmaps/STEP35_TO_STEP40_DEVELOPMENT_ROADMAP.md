# STEP35 ~ STEP40 개발 로드맵

> 기준 프로젝트: `stock-platform(2).zip`  
> 목적: Cursor AI가 STEP35부터 STEP40까지 순서대로 실제 개발을 수행할 수 있도록 개발 범위와 우선순위를 확정한다.

---

## 0. 현재 프로젝트 판단

현재 프로젝트에는 이미 다음 영역이 구현되어 있다.

- 키움 REST 인증·시세·주문·미체결·체결 WebSocket
- 업비트 일봉 및 실시간 WebSocket
- 시장 데이터 저장
- 기술지표
- 후보종목 선별
- 뉴스·DART 공시
- Ollama 기반 AI 분석
- 백테스트·워크포워드·포트폴리오 백테스트
- 주문 상태·Outbox·취소/정정·Execution
- 실시간 전략·실시간 주문 실행
- 리스크 엔진·킬스위치·일손실 제한
- 전략 성과·랭킹·자동 배포
- 운영 Job·Pipeline·Report·Dashboard
- 다수의 단위 테스트

따라서 STEP35~STEP40은 새 기능을 처음부터 만드는 단계가 아니라, 이미 구현된 기능을 실제 운영 가능한 하나의 시스템으로 통합하고 검증하는 단계로 진행한다.

---

# STEP35 — 프로젝트 통합 안정화

## 목표

현재 흩어져 있는 모듈과 중복 구현을 정리하고, 서버가 일관된 구조로 기동·종료되며 전체 테스트가 안정적으로 실행되는 상태를 만든다.

## 개발 작업

### TASK 35-01 — 애플리케이션 Lifespan 통합

대상 파일:

- `src/stock_platform/api/main.py`
- `src/stock_platform/realtime/runtime.py`
- `src/stock_platform/realtime/session_runtime.py`
- `src/stock_platform/broker/recovery_runtime.py`
- `src/stock_platform/broker/kiwoom/ws_manager.py`
- `src/stock_platform/strategy_deployment/runtime_manager.py`

개발 내용:

- 시작 순서를 `설정 검증 → DB 확인 → Broker 복구 → 전략 로딩 → Scheduler 시작 → WebSocket/Realtime 시작`으로 명확히 한다.
- 종료 순서는 시작 순서의 역순으로 통일한다.
- 일부 서비스 시작 실패 시 전체 서버가 죽어야 하는 경우와 경고만 남기고 계속 기동할 경우를 구분한다.
- 중복 `start()`, `shutdown()`, `stop()` 호출에 안전하도록 idempotent 처리한다.
- 시작·종료 상태를 운영 로그에 기록한다.

완료 기준:

- 서버를 연속 두 번 시작·종료해도 Task 중복, Event loop 오류, 미정리 세션이 발생하지 않는다.
- Lifespan 전용 테스트가 추가된다.

---

### TASK 35-02 — Router 등록과 API 경로 정리

대상 파일:

- `src/stock_platform/api/router.py`
- `src/stock_platform/api/main.py`
- `src/stock_platform/api/v1/indicator_router.py`
- `src/stock_platform/api/v1/indicators.py`
- `src/stock_platform/api/v1/market_data_router.py`

개발 내용:

- `main.py`에서 별도 등록되는 `indicator_router`를 `api_router` 체계로 통합한다.
- `indicator`와 `indicators`, `market`과 `markets`, `broker`와 `brokers`처럼 중복된 패키지 및 API 경로를 조사한다.
- 기존 호환성이 필요한 경로는 deprecated alias로 유지하고 신규 표준 경로를 확정한다.
- Router 등록 순서를 도메인별로 정렬한다.
- 중복 prefix·중복 operation_id 검사를 추가한다.

완료 기준:

- FastAPI OpenAPI schema 생성 시 중복 operation ID 경고가 없다.
- 모든 v1 Router가 한 곳에서 등록된다.

---

### TASK 35-03 — 설정과 환경변수 단일화

대상 파일:

- `src/stock_platform/common/settings.py`
- `src/stock_platform/broker/kiwoom/config.py`
- `config/kiwoom.env.example`
- `.env.example`
- 환경변수를 직접 읽는 모든 파일

개발 내용:

- `os.getenv()` 직접 호출을 Settings 객체로 통합한다.
- Kiwoom, Upbit, DART, Ollama, PostgreSQL, 실시간 전략, 리스크, 알림 설정을 한 구조로 정리한다.
- 필수값과 선택값을 구분한다.
- 모의투자와 실전투자 설정을 명확히 분리한다.
- `KIWOOM_LIVE_ORDER_ENABLED=false`가 기본값이 되도록 한다.
- 잘못된 환경변수는 서버 시작 시 명확한 오류로 보고한다.

완료 기준:

- 운영 코드에서 임의의 `os.getenv()` 사용이 최소화된다.
- `.env.example` 하나만으로 전체 설정 항목을 확인할 수 있다.

---

### TASK 35-04 — 중복 도메인 구조 조사 및 정리

조사 대상:

- `market` / `markets`
- `indicator` / `indicators`
- `broker` / `brokers`
- `risk` / `risk_engine`
- `strategy` / `strategies` / `strategy_deployment`

개발 내용:

- 각 패키지의 역할, 사용처, API, Repository, Service, Entity를 비교한다.
- 삭제부터 하지 않고 표준 패키지를 결정한다.
- 이전 import 경로가 필요한 경우 compatibility module을 둔다.
- 신규 개발은 표준 패키지만 사용하도록 규칙을 만든다.
- 결과를 `docs/development/DOMAIN_PACKAGE_MAP.md`에 기록한다.

완료 기준:

- 각 도메인별 표준 패키지가 한 개로 결정된다.
- 신규 코드가 어느 패키지에 추가되어야 하는지 명확하다.

---

### TASK 35-05 — 공통 예외와 API 응답 통일

대상 파일:

- `src/stock_platform/common/`
- `src/stock_platform/api/`
- Broker, Collector, AI, Risk 예외 클래스

개발 내용:

- DomainError, ValidationError, ExternalApiError, ConflictError, NotFoundError를 정의한다.
- FastAPI exception handler를 등록한다.
- 외부 API 오류에서 비밀키·토큰·계좌번호가 응답에 노출되지 않도록 한다.
- API 오류 응답 형식을 `code`, `message`, `detail`, `request_id`로 통일한다.
- 성공 응답을 무리하게 전부 래핑하지는 않는다.

완료 기준:

- 대표 API 오류 테스트가 통과한다.
- Kiwoom/DART/Upbit/Ollama 오류가 HTTP 상태 코드에 일관되게 매핑된다.

---

### TASK 35-06 — Alembic Revision 정리

대상:

- `alembic/versions/`
- `database/alembic/versions/`
- `alembic.ini`
- `database/alembic/env.py`

개발 내용:

- Alembic 디렉터리가 두 군데 존재하는 이유를 확인한다.
- 실제 운영 기준 Alembic 경로를 하나로 확정한다.
- 모든 revision의 `revision`, `down_revision` 연결을 검증한다.
- STEP32·33·34 revision이 하나의 head로 연결되도록 한다.
- 중복 테이블 생성 및 누락 downgrade를 점검한다.
- `alembic heads`, `history`, `upgrade head`, `downgrade` 검증 스크립트를 추가한다.

완료 기준:

- Alembic head가 하나다.
- 빈 PostgreSQL DB에 처음부터 migration 적용이 성공한다.

---

### TASK 35-07 — 전체 테스트 실행 기반 정리

대상:

- `pytest.ini` 또는 `pyproject.toml`
- `tests/conftest.py`
- 전체 `tests/`

개발 내용:

- unit, integration, external, live 테스트 marker를 정의한다.
- 기본 `pytest` 실행 시 실제 주문이나 외부 API 호출이 절대 발생하지 않도록 한다.
- PostgreSQL이 필요한 테스트와 메모리 테스트를 분리한다.
- 공통 fixture를 정리한다.
- 현재 실패 테스트를 분류하고 수정한다.

완료 기준:

- `pytest -m "not external and not live"`가 안정적으로 통과한다.
- 테스트 결과 요약 문서가 생성된다.

---

## STEP35 최종 결과

- 서버 기동·종료 안정화
- Router 단일화
- 환경변수 단일화
- 패키지 중복 구조 정리
- 공통 오류 처리
- Alembic 단일 head
- 전체 기본 테스트 통과

권장 커밋:

```text
refactor(step35): stabilize application integration
```

---

# STEP36 — 시장 데이터 수집 및 저장 엔진 완성

## 목표

키움과 업비트의 과거·실시간 데이터를 PostgreSQL에 안정적으로 저장하고, 중단 후 이어받기가 가능한 수집 엔진을 완성한다.

## 개발 작업

### TASK 36-01 — PostgreSQL Market Repository 완성

대상 파일:

- `src/stock_platform/market/repository.py`
- `src/stock_platform/markets/repository.py`
- `src/stock_platform/market/services/sync.py`
- STEP33 메모리 Repository 관련 코드

개발 내용:

- Symbol, Daily Candle, Minute Candle, Quote, Trade, Orderbook의 PostgreSQL Repository를 확정한다.
- Upsert 기준 키와 중복 방지 제약조건을 정의한다.
- batch insert/upsert를 적용한다.
- UTC 저장, Asia/Seoul 표시 원칙을 통일한다.

---

### TASK 36-02 — 업비트 KRW 전체 일봉 동기화

대상 파일:

- `src/stock_platform/collectors/upbit/`
- `src/stock_platform/markets/`
- Scheduler/Job 관련 모듈

개발 내용:

- KRW 마켓 목록 자동 동기화
- 최근 3년 일봉 최초 적재
- 마지막 저장일 다음 날부터 이어받기
- 429 응답 및 rate limit 대응
- 실패 종목 재시도
- 수집 결과를 `operation.job_run_history`에 기록

---

### TASK 36-03 — 키움 종목·일봉 동기화 완성

대상 파일:

- `src/stock_platform/collectors/kiwoom/`
- `src/stock_platform/broker/kiwoom/client.py`
- Kiwoom mapper/parser

개발 내용:

- 공식 REST TR 기준으로 종목 기본정보와 일봉 mapper를 확정한다.
- 연속조회 `cont-yn`, `next-key`를 실제 응답 기반으로 처리한다.
- 모의투자와 실전 서버 설정을 분리한다.
- 토큰 갱신, 401 재시도, 요청 제한을 통합한다.
- 수집 중단 후 이어받기를 지원한다.

---

### TASK 36-04 — 분봉 저장

개발 내용:

- 1분, 3분, 5분, 15분봉 모델과 Repository를 확정한다.
- 키움·업비트 raw trade 또는 분봉 API를 표준 Candle 모델로 변환한다.
- 동일 timestamp 데이터 Upsert
- 장 시간 밖 데이터 처리
- 대량 적재 성능 테스트

---

### TASK 36-05 — 실시간 Quote/Trade/Orderbook 영속화

대상 파일:

- `src/stock_platform/realtime/upbit_client.py`
- `src/stock_platform/broker/kiwoom/ws_client.py`
- `src/stock_platform/realtime/manager.py`
- market Repository

개발 내용:

- WebSocket 이벤트를 공통 MarketEvent 모델로 표준화한다.
- 수신과 DB 저장을 Queue로 분리한다.
- DB 장애 시 bounded retry와 drop 정책을 정의한다.
- 연결 상태, 마지막 수신시간, 수신 건수, 오류를 Health API에 노출한다.

---

### TASK 36-06 — 지표 자동 계산 파이프라인

대상 파일:

- `src/stock_platform/indicator/`
- `src/stock_platform/indicators/`
- `src/stock_platform/screener/`

개발 내용:

- 일봉 적재 후 MA5/20/60, EMA, RSI14, 거래량평균, 52주 고저를 계산한다.
- 필요한 과거 데이터가 부족한 경우 상태를 명확히 기록한다.
- 동일 날짜 재실행은 Upsert한다.
- 대상 종목 전체 batch 계산 Job을 추가한다.

---

### TASK 36-07 — 데이터 품질 검증

개발 내용:

- OHLC 논리 오류 검사
- 음수 가격·거래량 방지
- 누락 거래일 탐지
- 중복 Candle 탐지
- 시장별 최신 수집 시각 Dashboard 제공

---

## STEP36 최종 결과

- 키움·업비트 과거 데이터 자동 저장
- 실시간 데이터 수신 및 저장
- 중단 후 이어받기
- 지표 자동 계산
- 데이터 품질 점검

권장 커밋:

```text
feat(step36): complete market data pipeline
```

---

# STEP37 — 후보 선별 및 AI 의사결정 엔진 완성

## 목표

규칙 기반 후보 10개를 생성하고 뉴스·공시·기술지표를 결합해 AI가 최종 후보 5개와 근거를 생성하도록 한다.

## 개발 작업

### TASK 37-01 — 후보 선정 규칙 확정

대상 파일:

- `src/stock_platform/screener/`
- candidate rule/scoring 관련 코드

개발 내용:

- 유동성
- 거래대금
- 추세
- RSI
- 거래량 증가
- 52주 위치
- 과도한 변동성 제외
- 거래정지·관리종목 제외

각 규칙의 점수와 탈락 사유를 저장한다.

---

### TASK 37-02 — 뉴스 수집·중복 제거·종목 연결

대상 파일:

- `src/stock_platform/news/`
- `src/stock_platform/collectors/`

개발 내용:

- 뉴스 원문 저장
- URL·제목 기반 중복 제거
- 종목코드 연결
- 게시일과 수집일 분리
- 최근 뉴스 우선 조회
- 수집 실패 이력 저장

---

### TASK 37-03 — DART 공시 수집·종목 연결

대상 파일:

- `src/stock_platform/disclosure/`
- `src/stock_platform/disclosure/dart_client.py`

개발 내용:

- corp_code 목록 동기화
- 공시 목록 이어받기
- 주요 공시 유형 분류
- 정정공시 연결
- 종목코드 연결
- 중요도 점수 생성

---

### TASK 37-04 — AI Context Builder 고도화

대상 파일:

- `src/stock_platform/ai/context_builder.py`
- `src/stock_platform/ai/orchestration_service.py`

개발 내용:

- 가격·지표·후보점수·뉴스·공시·현재 포지션·리스크 상태를 하나의 context로 구성한다.
- 토큰 길이를 제한한다.
- 뉴스와 공시는 중요도·최신순으로 축약한다.
- 입력 데이터 출처와 기준시각을 저장한다.

---

### TASK 37-05 — 구조화된 AI 응답

대상 파일:

- `src/stock_platform/ai/ollama_client.py`
- `src/stock_platform/ai/analysis_service.py`
- AI 모델/Entity

응답 필드:

- symbol
- score
- rank
- decision
- confidence
- positive_reasons
- negative_reasons
- risk_flags
- invalidation_conditions
- suggested_holding_period
- model_name
- prompt_version

개발 내용:

- JSON Schema 기반 응답 검증
- 파싱 실패 재시도
- hallucination 방지 검증
- 후보 외 종목 반환 차단
- 분석 결과 DB 저장

---

### TASK 37-06 — 최종 10 → 5 선별

개발 내용:

- 규칙 기반 상위 10개 입력
- AI 평가 후 최대 5개 출력
- 최소 점수·최소 confidence 미달 시 5개보다 적게 선택 가능
- AI 오류 시 규칙 기반 fallback
- 선정·탈락 근거 저장

---

### TASK 37-07 — AI 결과 조회 및 재현

개발 내용:

- 분석 run 조회 API
- 후보별 근거 조회 API
- prompt/version/context hash 저장
- 동일 입력 재실행 비교
- AI 응답 시간과 오류율 Metrics

---

## STEP37 최종 결과

- 후보 10개 자동 생성
- 뉴스·공시 컨텍스트 생성
- AI 최종 5개 선정
- 선정·탈락 근거와 위험요소 저장

권장 커밋:

```text
feat(step37): complete ai candidate decision engine
```

---

# STEP38 — 실시간 자동매매 및 리스크 통합

## 목표

AI 후보와 전략 신호를 주문으로 연결하되, Risk Engine의 승인을 통과한 주문만 모의투자 환경에서 실행되도록 한다.

## 개발 작업

### TASK 38-01 — 주문 실행 단일 진입점

대상 파일:

- `src/stock_platform/order/`
- `src/stock_platform/broker/`
- `src/stock_platform/realtime/`

개발 내용:

모든 주문은 아래 순서를 통과한다.

```text
Signal
→ Position Sizing
→ Risk Validation
→ Safety Guard
→ Idempotency
→ Outbox
→ Broker Adapter
→ Order State
→ Execution
→ Position
```

직접 Broker 호출 경로를 금지한다.

---

### TASK 38-02 — 계좌 상태 동기화

대상 파일:

- `src/stock_platform/broker/kiwoom/account_sync_service.py`
- `src/stock_platform/trading/account_service.py`
- position 관련 코드

개발 내용:

- 예수금
- 주문가능금액
- 보유수량
- 평균단가
- 평가손익
- 실현손익
- 미체결

을 Broker와 내부 DB 사이에서 동기화한다.

---

### TASK 38-03 — 주문 상태·체결 정합성

개발 내용:

- 주문 상태 전이 검증
- 부분체결
- 완전체결
- 취소
- 정정
- 거부
- 타임아웃
- WebSocket 누락 시 REST 조회 복구
- 중복 체결 idempotency

---

### TASK 38-04 — 포지션 사이징

대상 파일:

- `src/stock_platform/position/calculator.py`
- `src/stock_platform/risk_engine/`

개발 내용:

- 정액
- 계좌 비율
- 손절거리 기반 위험금액
- 최대 종목 비중
- 최대 총투자 비중
- 최소 주문금액
- 호가 단위와 주문 수량 보정

---

### TASK 38-05 — 리스크 정책 완성

정책:

- 종목별 손절
- 익절
- 트레일링 스탑
- 일일 최대손실
- 최대 보유종목 수
- 종목별 최대 비중
- 전략별 손실 제한
- 연속 손실 제한
- 거래시간 제한
- Kill Switch
- 데이터 지연 차단
- Broker 연결 불안정 차단

---

### TASK 38-06 — 모의투자 End-to-End 실행

개발 내용:

- 모의투자 계좌만 사용
- 실전 주문 기본 차단
- 주문 전 확인 로그
- 주문→체결→포지션→손익 전체 검증
- 재시작 후 복구 테스트

---

### TASK 38-07 — 실전 전환 승인 절차

대상 파일:

- `src/stock_platform/broker/live_transition_service.py`
- strategy approval/deployment 관련 코드

개발 내용:

실전 전환 조건:

- 모든 필수 테스트 통과
- 모의투자 최소 운영기간 충족
- 최대 손실 기준 충족
- 계좌번호 설정
- 사용자 명시적 승인
- `KIWOOM_LIVE_ORDER_ENABLED=true`
- 승인 이력 저장

---

## STEP38 최종 결과

- 주문 실행 경로 단일화
- 계좌·미체결·체결·포지션 정합성 확보
- 리스크 통합
- 모의투자 자동매매 가능
- 실전 주문은 계속 기본 차단

권장 커밋:

```text
feat(step38): integrate trading execution and risk controls
```

---

# STEP39 — 운영센터, 모니터링, 알림

## 목표

운영자가 시스템 상태, 데이터 상태, AI 판단, 전략, 주문, 리스크를 한 곳에서 확인하고 장애를 즉시 인지할 수 있도록 한다.

## 개발 작업

### TASK 39-01 — 통합 System Health

대상 파일:

- `src/stock_platform/operation/health_service.py`
- Dashboard API

확인 대상:

- PostgreSQL
- Ollama
- Kiwoom REST
- Kiwoom WebSocket
- Upbit REST/WebSocket
- DART
- News
- Scheduler
- Queue
- 최근 시장 데이터 시각
- Kill Switch
- 실전 주문 활성화 여부

---

### TASK 39-02 — 운영 Dashboard API

대상 파일:

- `src/stock_platform/dashboard/`
- `src/stock_platform/performance/dashboard_service.py`
- `src/stock_platform/api/v1/system_dashboard.py`

화면/응답:

- 시스템 상태
- Job 실행 상태
- 데이터 최신성
- 오늘 후보
- AI 최종 선정
- 보유 포지션
- 미체결 주문
- 당일 손익
- 리스크 상태
- 전략 배포 상태

---

### TASK 39-03 — 구조화 로그와 Audit Log

개발 내용:

- request_id
- run_id
- strategy_id
- account hash
- order_id
- client_order_id
- symbol
- event type

를 구조화 로그에 포함한다.

비밀키·토큰·전체 계좌번호는 절대 기록하지 않는다.

---

### TASK 39-04 — Telegram/Discord 알림

대상 파일:

- `src/stock_platform/notification/`

알림 이벤트:

- 서버 시작·종료
- Broker 연결 실패
- 데이터 수집 실패
- AI 분석 완료/실패
- 주문 접수·체결·거부
- 손절·익절
- 일손실 제한 발동
- Kill Switch
- 전략 자동 중지

중복 알림 억제와 재시도를 구현한다.

---

### TASK 39-05 — 일일 운영 리포트

대상 파일:

- `src/stock_platform/operation/report_service.py`
- `src/stock_platform/api/v1/daily_reports.py`

리포트 내용:

- 수집 결과
- 후보 10개
- AI 선정 5개
- 주문·체결
- 보유 포지션
- 실현·평가손익
- 리스크 이벤트
- Job 실패
- 다음 거래일 주의사항

---

### TASK 39-06 — 관리용 API 보호

개발 내용:

- Scheduler 실행
- Kill Switch 해제
- 실전 전환
- 전략 승인
- 수동 주문
- 데이터 재수집

등의 관리 API에 인증과 권한을 적용한다.

---

### TASK 39-07 — 운영 Runbook

생성 문서:

- `docs/OPERATIONS_RUNBOOK.md`
- `docs/INCIDENT_RESPONSE.md`
- `docs/LIVE_TRADING_CHECKLIST.md`

---

## STEP39 최종 결과

- 통합 상태 확인
- 운영 Dashboard
- 장애 알림
- 일일 리포트
- 관리 API 보호
- 장애 대응 문서

권장 커밋:

```text
feat(step39): add operations monitoring and alerts
```

---

# STEP40 — 통합 검증 및 v1.0 릴리스

## 목표

전체 시스템을 회귀 테스트하고 설치·운영·복구 문서를 완성하여 v1.0 릴리스 가능한 상태로 만든다.

## 개발 작업

### TASK 40-01 — 전체 회귀 테스트

테스트 범위:

- Market data
- Indicators
- Screener
- News
- DART
- AI
- Backtest
- Strategy
- Risk
- Order
- Broker
- Realtime
- Scheduler
- Dashboard
- Notifications

---

### TASK 40-02 — End-to-End 시나리오 테스트

시나리오:

```text
시장 데이터 수집
→ 지표 계산
→ 후보 10개 생성
→ 뉴스·공시 수집
→ AI 후보 5개 선정
→ 전략 신호
→ 리스크 승인
→ 모의 주문
→ 체결
→ 포지션 반영
→ 손익 계산
→ 리포트·알림
```

---

### TASK 40-03 — 장애 복구 테스트

검증 항목:

- 서버 강제 종료 후 재시작
- PostgreSQL 일시 장애
- Ollama 중단
- Kiwoom 토큰 만료
- WebSocket 연결 종료
- 중복 체결 메시지
- Scheduler Job 중복 실행
- Outbox 처리 중 종료
- Kill Switch 상태 복원

---

### TASK 40-04 — 성능 검증

검증 항목:

- 3년치 Upbit 전체 KRW 일봉 적재 시간
- 일봉·분봉 Batch Upsert
- 실시간 이벤트 처리량
- 지표 전체 계산 시간
- 후보 분석 시간
- Ollama 응답 시간
- Dashboard 조회 시간

---

### TASK 40-05 — 보안 점검

점검 항목:

- `.env` Git 제외
- API Key·Token 로그 노출 방지
- 계좌번호 마스킹
- 실전 주문 기본 비활성
- 관리 API 인증
- SQL Injection 방지
- 외부 응답 검증
- 의존성 취약점 점검

---

### TASK 40-06 — 문서 완성

필수 문서:

- `README.md`
- `docs/INSTALL.md`
- `docs/CONFIGURATION.md`
- `docs/ARCHITECTURE.md`
- `docs/API.md`
- `docs/ERD.md`
- `docs/OPERATIONS_RUNBOOK.md`
- `docs/LIVE_TRADING_CHECKLIST.md`
- `docs/TROUBLESHOOTING.md`
- `CHANGELOG.md`

---

### TASK 40-07 — v1.0 릴리스

개발 내용:

- 버전 `1.0.0`
- Migration 검증
- Release note
- Git tag
- 백업 절차
- 설치 ZIP에서 `.venv`, cache, log, secret 제외
- 최종 체크리스트 작성

권장 커밋:

```text
release(step40): prepare stock platform v1.0.0
```

권장 태그:

```text
v1.0.0
```

---

# STEP별 요약

| STEP | 핵심 목표 | 최종 산출물 |
|---|---|---|
| STEP35 | 통합 안정화 | 서버·Router·설정·Alembic·테스트 정리 |
| STEP36 | 데이터 엔진 | 키움·업비트 과거/실시간 데이터와 지표 |
| STEP37 | AI 의사결정 | 규칙 후보 10개 → AI 최종 후보 최대 5개 |
| STEP38 | 자동매매·리스크 | 모의투자 주문·체결·포지션·리스크 통합 |
| STEP39 | 운영센터 | Dashboard·Health·로그·알림·리포트 |
| STEP40 | v1.0 릴리스 | E2E·장애복구·성능·보안·문서·배포 |

---

# Cursor 공통 실행 규칙

각 STEP 시작 시 Cursor는 반드시 다음 순서로 작업한다.

1. 해당 STEP의 대상 파일을 실제로 읽는다.
2. 이미 구현된 기능을 목록화한다.
3. 중복 구현 없이 변경 계획을 작성한다.
4. 한 Task씩 구현한다.
5. Task별 테스트를 실행한다.
6. STEP 전체 테스트를 실행한다.
7. 변경 파일과 테스트 결과를 보고한다.
8. 사용자 확인 전 실전 주문을 활성화하지 않는다.
9. 하나의 STEP이 완료되기 전 다음 STEP으로 넘어가지 않는다.
10. 테스트가 실패한 상태를 완료라고 보고하지 않는다.

