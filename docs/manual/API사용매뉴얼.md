# API 사용 매뉴얼

관리 화면에 아직 없는 기능은 **API** 로 처리합니다.  
이 문서는 **처음 여는 순서**부터 안내합니다.

대화형 설명서(추천): http://127.0.0.1:8000/docs  
기계용 목록: http://127.0.0.1:8000/openapi.json

> **중요:** 각 API가 요구하는 입력칸(필드)의 정확한 이름은 `/docs` 에 있는 설명이 기준입니다.  
> 이 문서에 없는 값을 추측해서 넣지 마세요.

요약 표(일부): [../backend/API.md](../backend/API.md)

---

## 목차 (사용 순서)

1. [API가 뭔가요?](#1-api가-뭔가요)
2. [설명서 화면 열기](#2-설명서-화면-열기)
3. [권한(관리 키)](#3-권한관리-키)
4. [자주 쓰는 작업 따라 하기](#4-자주-쓰는-작업-따라-하기)
5. [기능 그룹 한눈에 보기](#5-기능-그룹-한눈에-보기)
6. [전체 주소 목록](#6-전체-주소-목록)

---

## 용어 설명

| 쉬운 말 | 전문 용어 | 뜻 |
|---------|-----------|-----|
| 서버 주소 | URL / Endpoint | 예: `/health`, `/api/v1/orders` |
| 요청 방식 | Method (GET/POST…) | GET=조회, POST=실행·저장 |
| 보내기 내용 | Request Body | POST 때 함께 보내는 JSON 데이터 |
| 받기 결과 | Response | 서버가 돌려주는 답 |
| API 설명서 | OpenAPI / Swagger | `/docs` 에서 버튼으로 시험 |
| 관리 키 | `X-Admin-API-Key` | 위험한 작업용 비밀번호 헤더 |
| JSON | — | `{ "키": "값" }` 형태의 데이터 글자 |

---

## 1. API가 뭔가요?

API는 **서버에게 일을 시키는 리모컨 버튼**입니다.  
관리 화면이 준비 중일 때도, `/docs` 에서 같은 일을 할 수 있습니다.

기본 주소:

```text
http://127.0.0.1:8000
```

대부분의 기능은 `/api/v1/...` 로 시작합니다.  
예외: `/health`, `/version`, `/`

---

## 2. 설명서 화면 열기

1. 서버를 켭니다 ([운영매뉴얼.md](운영매뉴얼.md))  
2. 브라우저에서 http://127.0.0.1:8000/docs 를 엽니다  
3. 원하는 항목을 펼치고 **Try it out** → **Execute** 로 시험합니다

**[스크린샷]** `/docs` 첫 화면  
**[스크린샷]** 한 API를 펼쳐 Try it out 한 모습

---

## 3. 권한 (JWT · 관리 키)

| 구분 | 어떻게? |
|------|---------|
| Admin Web | `/login` → JWT (`Authorization: Bearer …`) |
| 회원·역할·설정·문서 CMS | JWT + RBAC permission |
| 관리 작업(감사·Kill Switch 등) | `X-Admin-API-Key` **또는** admin JWT |
| 키가 비어 있음 | Admin Key 검사는 로컬에서 통과 가능. **운영에서는 키·JWT_SECRET 필수** |

### Auth / Settings 예시

| 방식 | 주소 | 설명 |
|------|------|------|
| POST | `/api/v1/auth/login` | 로그인 |
| GET | `/api/v1/auth/me` | 현재 사용자·권한 |
| GET | `/api/v1/users` | 회원 목록 |
| GET | `/api/v1/roles` | 역할·권한 |
| GET/PUT | `/api/v1/settings` | 앱 설정 |
| GET | `/api/v1/docs` | 문서 CMS 목록 |
| GET | `/api/v1/docs/{slug}` | 매뉴얼 본문 |

### 관리 키가 필요한 주소 (코드 기준)

| 방식 | 주소 | 쉬운 설명 |
|------|------|-----------|
| GET | `/api/v1/audit/events` | 감사(누가 무엇을) 조회 |
| POST | `/api/v1/scheduler-admin/run-now/{job_name}` | 스케줄 작업 즉시 실행 |
| POST | `/api/v1/orders/{order_id}/dispatch` | 주문 전송 |
| POST | `/api/v1/risk/kill-switch/activate` | 비상 정지 ON |
| POST | `/api/v1/risk/kill-switch/deactivate` | 비상 정지 OFF |
| POST | `/api/v1/broker/live-transition/request` | 실전 전환 요청 |
| POST | `/api/v1/broker/live-transition/{id}/approve` | 실전 전환 승인 |
| POST | `/api/v1/broker/live-transition/{id}/disable` | 실전 전환 해제 |
| GET | `/api/v1/broker/live-transition/history` | 실전 전환 이력 |
| POST | `/api/v1/strategy-policy/{id}/force` | 전략 정책 강제 |
| POST | `/api/v1/strategy-policy/{id}/reject` | 전략 정책 거절 |

**[스크린샷]** `/docs` 에서 Authorize 또는 헤더에 키를 넣는 방법(해당 UI가 있을 때)

---

## 4. 자주 쓰는 작업 따라 하기

### 4-1. 서버가 살아 있는지 확인

```http
GET /health
```

브라우저에서도 열 수 있습니다: http://127.0.0.1:8000/health

**[스크린샷]** health 결과 (database, ollama 등)

### 4-2. 시스템 요약 보기

```http
GET /api/v1/system/dashboard
```

### 4-3. 비상 정지 상태 보기 / 켜기

```http
GET /api/v1/risk/kill-switch

POST /api/v1/risk/kill-switch/activate
X-Admin-API-Key: (키)
Content-Type: application/json
```

보낼 내용(Body)의 정확한 칸은 `/docs` 에서 확인하세요.

### 4-4. 스케줄 작업 한 번 실행

```http
POST /api/v1/scheduler-admin/run-now/candidate_screening
X-Admin-API-Key: (키)
```

### 4-5. 모의(Paper) 주문 만들기

```http
POST /api/v1/paper-orders
Content-Type: application/json
```

필수 항목은 `/docs` → Paper Orders → Create 에서 확인합니다.  
(실제 돈이 나가지 않는 연습용입니다.)

### 4-6. AI 분석 실행

```http
POST /api/v1/ai-analysis/{exchange_code}
Content-Type: application/json
```

먼저 **Ollama** 가 켜져 있어야 합니다.

### 4-7. 터미널에서 간단히 호출 (선택)

```powershell
curl.exe -s http://127.0.0.1:8000/health
curl.exe -s -H "X-Admin-API-Key: $env:ADMIN_API_KEY" http://127.0.0.1:8000/api/v1/audit/events
```

---

## 5. 기능 그룹 한눈에 보기

| 하고 싶은 일 | 주소가 시작하는 곳 |
|--------------|--------------------|
| 건강·버전 | `/health`, `/version` |
| 운영 요약·감사 | `/api/v1/system/dashboard`, `/api/v1/audit` |
| 시세·지표 | `/api/v1/market`, `/api/v1/prices`, `/api/v1/indicators` |
| 키움·업비트·동기화 | `/api/v1/kiwoom`, `/api/v1/upbit`, `/api/v1/sync` |
| 후보·AI | `/api/v1/candidates`, `/api/v1/ai-*` |
| 뉴스·공시 | `/api/v1/news`, `/api/v1/dart` |
| 백테스트·포트폴리오 | `/api/v1/backtest*`, `/api/v1/portfolio-*` |
| 전략 | `/api/v1/strategy-*` |
| 위험 관리 | `/api/v1/risk*`, `/api/v1/realtime-risk` |
| 주문·체결 | `/api/v1/orders`, `/api/v1/order-*`, `/api/v1/executions` |
| 모의 거래 | `/api/v1/paper-*` |
| 브로커·실전 전환 | `/api/v1/broker/*` |
| 실시간 | `/api/v1/realtime-*` |
| 작업·스케줄·파이프라인 | `/api/v1/jobs`, `/api/v1/scheduler-admin`, `/api/v1/pipelines` |
| 알림·달력·일일 보고 | `/api/v1/notification`, `/api/v1/trading-calendar`, `/api/v1/daily-reports` |

---

## 6. 전체 주소 목록

아래 표는 서버 OpenAPI에서 뽑아 온 **전체 목록**입니다.

- **Method** = 요청 방식 (GET/POST/…)  
- **Path** = 주소  
- **Has body** = 보낼 내용(JSON)이 있으면 True  
- **Summary** = 짧은 이름  

상세 입력·출력 칸은 반드시 `/docs` 에서 확인하세요.

| Method | Path | Tags | Has body | Summary |
|--------|------|------|----------|---------|
| GET | `/` |  | False | Root |
| GET | `/api/v1/ai-analysis/latest/{exchange_code}` | AI Analysis | False | Get Latest Ai Analysis |
| GET | `/api/v1/ai-analysis/metrics` | AI Analysis | False | Get Ai Analysis Metrics |
| GET | `/api/v1/ai-analysis/runs` | AI Analysis | False | List Ai Analysis Runs |
| GET | `/api/v1/ai-analysis/runs/{analysis_run_id}` | AI Analysis | False | Get Ai Analysis Run |
| GET | `/api/v1/ai-analysis/runs/{analysis_run_id}/candidates/{symbol}` | AI Analysis | False | Get Ai Candidate Rationale |
| POST | `/api/v1/ai-analysis/runs/{analysis_run_id}/reproduce` | AI Analysis | False | Reproduce Ai Analysis |
| POST | `/api/v1/ai-analysis/{exchange_code}` | AI Analysis | True | Execute Ai Analysis |
| POST | `/api/v1/ai-orchestration/{exchange_code}` | AI Orchestration | True | Execute Orchestration |
| POST | `/api/v1/ai/candidates/rank/{exchange_code}` | AI Candidates | False | Rank Candidates |
| GET | `/api/v1/audit/events` | Audit | False | List Audit Events |
| POST | `/api/v1/backtest-grid` | Backtest Grid | True | Run Backtest Grid |
| POST | `/api/v1/backtest-performance/save` | Backtest Performance | True | Save Backtest Performance |
| GET | `/api/v1/backtest-runs` | Backtest Runs | False | List Backtest Runs |
| POST | `/api/v1/backtest-runs` | Backtest Runs | True | Run And Save Backtest |
| GET | `/api/v1/backtest-runs/compare/ranking` | Backtest Runs | False | Compare Backtest Runs |
| GET | `/api/v1/backtest-runs/{backtest_run_id}` | Backtest Runs | False | Get Backtest Run |
| POST | `/api/v1/backtests/moving-average` | Backtests | True | Run Moving Average Backtest |
| GET | `/api/v1/broker/account` | Broker | False | Get Broker Account |
| POST | `/api/v1/broker/kiwoom/account-state/sync` | Kiwoom Account State | False | Synchronize Kiwoom Account State |
| POST | `/api/v1/broker/kiwoom/account/sync` | Kiwoom Account | False | Synchronize Kiwoom Account |
| GET | `/api/v1/broker/kiwoom/account/{account_number}` | Kiwoom Account | False | Get Kiwoom Account Snapshot |
| GET | `/api/v1/broker/kiwoom/order-websocket/history` | Kiwoom Order WebSocket | False | Get Kiwoom Order Websocket History |
| POST | `/api/v1/broker/kiwoom/order-websocket/start` | Kiwoom Order WebSocket | False | Start Kiwoom Order Websocket |
| GET | `/api/v1/broker/kiwoom/order-websocket/status` | Kiwoom Order WebSocket | False | Get Kiwoom Order Websocket Status |
| POST | `/api/v1/broker/kiwoom/order-websocket/stop` | Kiwoom Order WebSocket | False | Stop Kiwoom Order Websocket |
| GET | `/api/v1/broker/kiwoom/pending-orders/{account_number}` | Kiwoom Pending Orders | False | List Orders |
| POST | `/api/v1/broker/kiwoom/pending-orders/{account_number}/sync` | Kiwoom Pending Orders | False | Sync Orders |
| POST | `/api/v1/broker/kiwoom/pending-orders/{order_id}/cancel` | Kiwoom Pending Orders | True | Cancel |
| POST | `/api/v1/broker/kiwoom/pending-orders/{order_id}/modify` | Kiwoom Pending Orders | True | Modify |
| POST | `/api/v1/broker/live-approval` | Broker | False | Issue Live Trading Approval |
| GET | `/api/v1/broker/live-transition/active` | Live Trading Transition | False | Get Active Live Transition |
| GET | `/api/v1/broker/live-transition/history` | Live Trading Transition | False | List Live Transition History |
| POST | `/api/v1/broker/live-transition/request` | Live Trading Transition | True | Request Live Transition |
| POST | `/api/v1/broker/live-transition/validate` | Live Trading Transition | True | Validate Live Transition |
| POST | `/api/v1/broker/live-transition/{transition_id}/approve` | Live Trading Transition | True | Approve Live Transition |
| POST | `/api/v1/broker/live-transition/{transition_id}/disable` | Live Trading Transition | True | Disable Live Transition |
| POST | `/api/v1/broker/orders` | Broker | True | Place Broker Order |
| GET | `/api/v1/broker/orders/{broker_order_id}` | Broker | False | Get Broker Order |
| POST | `/api/v1/broker/orders/{broker_order_id}/cancel` | Broker | False | Cancel Broker Order |
| POST | `/api/v1/broker/recovery/run` | Broker Recovery | False | Run Broker Recovery |
| GET | `/api/v1/broker/recovery/status` | Broker Recovery | False | Get Broker Recovery Status |
| POST | `/api/v1/candidate-runs` | Candidate Runs | True | Execute Candidate Run |
| GET | `/api/v1/candidate-runs/latest/{exchange_code}` | Candidate Runs | False | Get Latest Candidate Run |
| GET | `/api/v1/candidates/evaluate/{exchange_code}/{symbol}` | Candidates | False | Evaluate Candidate |
| GET | `/api/v1/candidates/top/{exchange_code}` | Candidates | False | Get Top Candidates |
| GET | `/api/v1/daily-reports` | Daily Reports | False | List Daily Reports |
| POST | `/api/v1/daily-reports` | Daily Reports | True | Generate Daily Report |
| GET | `/api/v1/daily-reports/{report_date}/{exchange_code}` | Daily Reports | False | Get Daily Report |
| POST | `/api/v1/dart/corps/sync` | DART | False | Sync Dart Corps |
| POST | `/api/v1/dart/sync` | DART | True | Sync Dart Disclosures |
| GET | `/api/v1/dashboard/risk` | Risk Dashboard | False | Get Risk Dashboard |
| GET | `/api/v1/dashboard/strategy-operations` | Strategy Operations Dashboard | False | Get Strategy Operations Dashboard |
| GET | `/api/v1/dashboard/strategy-performance` | Strategy Performance Dashboard | False | Get Strategy Performance Dashboard |
| GET | `/api/v1/dashboard/summary` | step32 | False | Dashboard Summary |
| GET | `/api/v1/executions` | Executions | False | List Executions |
| POST | `/api/v1/guarded-pipelines/daily-strategy` | Guarded Pipelines | True | Execute Guarded Daily Pipeline |
| GET | `/api/v1/indicator/health` | indicator-deprecated | False | Health |
| GET | `/api/v1/indicator/screen` | indicator-deprecated | False | Screen |
| POST | `/api/v1/indicators/daily/batch/compute` | Indicators | True | Compute Indicators Batch |
| GET | `/api/v1/indicators/daily/{exchange_code}/{symbol}` | Indicators | False | Get Daily Indicators |
| POST | `/api/v1/indicators/daily/{exchange_code}/{symbol}/compute` | Indicators | True | Compute And Save Indicators |
| GET | `/api/v1/indicators/daily/{exchange_code}/{symbol}/saved` | Indicators | False | List Saved Indicators |
| GET | `/api/v1/jobs` | Jobs | False | List Registered Jobs |
| GET | `/api/v1/jobs/history` | Jobs | False | List Job History |
| POST | `/api/v1/jobs/{job_name}/execute` | Jobs | True | Execute Job |
| GET | `/api/v1/kiwoom/configuration` | Kiwoom | False | Get Kiwoom Configuration |
| POST | `/api/v1/kiwoom/token/test` | Kiwoom | False | Test Kiwoom Token |
| POST | `/api/v1/market-quality/check` | Market Quality | True | Run Quality Check |
| GET | `/api/v1/market-quality/dashboard` | Market Quality | False | Market Collection Dashboard |
| GET | `/api/v1/market/candles/day/{market}/{symbol}` | market-data | False | Get Daily Candles |
| GET | `/api/v1/market/candles/minute/{market}/{symbol}` | market-data | False | Get Minute Candles |
| GET | `/api/v1/market/orderbook/{market}/{symbol}` | market-data | False | Get Orderbook |
| GET | `/api/v1/market/quotes/{market}/{symbol}` | market-data | False | Get Quote |
| GET | `/api/v1/market/symbols` | market-data | False | List Symbols |
| POST | `/api/v1/market/sync/kiwoom/day/{symbol}` | market-data | False | Sync Kiwoom Daily Alias |
| POST | `/api/v1/market/sync/upbit/day/{symbol}` | market-data | False | Sync Upbit Daily Alias |
| GET | `/api/v1/market/trades/{market}/{symbol}` | market-data | False | Get Trades |
| GET | `/api/v1/news/failures` | News | False | List News Failures |
| POST | `/api/v1/news/summarize` | News | True | Summarize News |
| POST | `/api/v1/news/sync` | News | True | Sync News |
| GET | `/api/v1/news/{exchange_code}/{symbol}` | News | False | Get News Context |
| GET | `/api/v1/notification/status` | Notification | False | Get Notification Status |
| POST | `/api/v1/notification/test` | Notification | True | Send Test Notification |
| POST | `/api/v1/order-execution/submit` | Order Execution | True | Submit Order |
| GET | `/api/v1/order-outbox` | Order Outbox | False | List Outbox |
| POST | `/api/v1/order-outbox/retry` | Order Outbox | True | Retry Outbox |
| GET | `/api/v1/orders` | Orders | False | List Orders |
| POST | `/api/v1/orders` | Orders | True | Create Order |
| GET | `/api/v1/orders/{order_id}` | Orders | False | Get Order |
| GET | `/api/v1/orders/{order_id}/allowed-transitions` | Order States | False | Get Allowed Order Transitions |
| POST | `/api/v1/orders/{order_id}/cancel` | Order Cancel Replace | True | Cancel Order |
| POST | `/api/v1/orders/{order_id}/dispatch` | Order Dispatch | True | Dispatch Order |
| GET | `/api/v1/orders/{order_id}/executions` | Executions | False | List Order Executions |
| GET | `/api/v1/orders/{order_id}/history` | Orders | False | Get Order History |
| POST | `/api/v1/orders/{order_id}/replace` | Order Cancel Replace | True | Replace Order |
| POST | `/api/v1/orders/{order_id}/transition` | Order States | True | Transition Order State |
| POST | `/api/v1/paper-accounts` | Paper Accounts | True | Create Paper Account |
| POST | `/api/v1/paper-accounts/{account_id}/fills` | Paper Accounts | True | Apply Paper Fill |
| GET | `/api/v1/paper-accounts/{account_id}/positions` | Paper Accounts | False | List Paper Positions |
| POST | `/api/v1/paper-accounts/{account_id}/valuation` | Paper Accounts | True | Value Paper Account |
| POST | `/api/v1/paper-executions/fills` | Paper Executions | True | Apply Order Fill |
| GET | `/api/v1/paper-orders` | Paper Orders | False | List Paper Orders |
| POST | `/api/v1/paper-orders` | Paper Orders | True | Create Paper Order |
| POST | `/api/v1/paper-orders/{order_id}/cancel` | Paper Orders | False | Cancel Paper Order |
| POST | `/api/v1/paper-orders/{order_id}/fills` | Paper Orders | True | Fill Paper Order |
| POST | `/api/v1/paper-orders/{order_id}/reject` | Paper Orders | True | Reject Paper Order |
| POST | `/api/v1/paper-simulation/open-orders/daily-close` | Paper Simulation | True | Simulate Open Orders By Daily Close |
| POST | `/api/v1/paper-simulation/orders/{order_id}/daily-close` | Paper Simulation | True | Simulate Order By Daily Close |
| POST | `/api/v1/pipelines/daily-strategy` | Pipelines | True | Execute Daily Strategy Pipeline |
| GET | `/api/v1/pipelines/latest` | Pipelines | False | Get Latest Pipeline |
| POST | `/api/v1/portfolio-backtests` | Portfolio Backtests | True | Run Portfolio Backtest |
| POST | `/api/v1/portfolio-rebalancing-backtests` | Portfolio Rebalancing Backtests | True | Run Rebalancing Backtest |
| GET | `/api/v1/portfolio/summary` | step32 | False | Portfolio Summary |
| POST | `/api/v1/position-candidates/plans` | Position Candidates | True | Create Candidate Position Plans |
| GET | `/api/v1/positions` | step32 | False | List Positions |
| POST | `/api/v1/positions/executions` | step32 | True | Apply Execution |
| GET | `/api/v1/prices/daily/{exchange_code}/{symbol}` | Market Prices | False | Get Daily Prices |
| GET | `/api/v1/prices/latest/{exchange_code}/{symbol}` | Market Prices | False | Get Latest Price |
| POST | `/api/v1/realtime-ai/review` | Realtime AI | True | Review Realtime Symbol |
| GET | `/api/v1/realtime-execution/history` | Realtime Execution | False | Get Realtime Execution History |
| POST | `/api/v1/realtime-execution/start` | Realtime Execution | False | Start Realtime Execution |
| GET | `/api/v1/realtime-execution/status` | Realtime Execution | False | Get Realtime Execution Status |
| POST | `/api/v1/realtime-execution/stop` | Realtime Execution | False | Stop Realtime Execution |
| GET | `/api/v1/realtime-quotes` | Realtime Quotes | False | List Latest Quotes |
| GET | `/api/v1/realtime-quotes/status` | Realtime Quotes | False | Get Realtime Status |
| GET | `/api/v1/realtime-quotes/stream/sse` | Realtime Quotes | False | Stream Realtime Quotes |
| POST | `/api/v1/realtime-quotes/upbit/start` | Realtime Quotes | True | Start Upbit Realtime |
| POST | `/api/v1/realtime-quotes/{client_id}/stop` | Realtime Quotes | False | Stop Realtime Client |
| GET | `/api/v1/realtime-quotes/{exchange_code}/{symbol}` | Realtime Quotes | False | Get Latest Quote |
| GET | `/api/v1/realtime-risk/account-state/{account_number}/{exchange_code}/{symbol}` | Realtime Risk Account | False | Get Risk Account State |
| POST | `/api/v1/realtime-risk/check` | Realtime Risk Engine | True | Check Realtime Risk |
| GET | `/api/v1/realtime-risk/status` | Realtime Risk Engine | False | Get Realtime Risk Status |
| POST | `/api/v1/realtime-safety/realized-profit-loss` | Realtime Safety | True | Add Realized Profit Loss |
| POST | `/api/v1/realtime-safety/reset-daily` | Realtime Safety | False | Reset Daily Safety Counters |
| GET | `/api/v1/realtime-safety/status` | Realtime Safety | False | Get Realtime Safety Status |
| POST | `/api/v1/realtime-sessions/run-now/{phase}` | Realtime Sessions | False | Run Session Phase Now |
| POST | `/api/v1/realtime-sessions/start-scheduler` | Realtime Sessions | False | Start Realtime Session Scheduler |
| GET | `/api/v1/realtime-sessions/status` | Realtime Sessions | False | Get Realtime Session Status |
| POST | `/api/v1/realtime-sessions/stop-scheduler` | Realtime Sessions | False | Stop Realtime Session Scheduler |
| PUT | `/api/v1/realtime-strategy/positions` | Realtime Strategy | True | Set Realtime Position |
| GET | `/api/v1/realtime-strategy/positions/{exchange_code}/{symbol}` | Realtime Strategy | False | Get Realtime Position |
| GET | `/api/v1/realtime-strategy/signals/sse` | Realtime Strategy | False | Stream Realtime Signals |
| POST | `/api/v1/realtime-strategy/start` | Realtime Strategy | False | Start Realtime Strategy |
| GET | `/api/v1/realtime-strategy/status` | Realtime Strategy | False | Get Realtime Strategy Status |
| POST | `/api/v1/realtime-strategy/stop` | Realtime Strategy | False | Stop Realtime Strategy |
| GET | `/api/v1/risk-policies` | Risk Policies | False | List Risk Policies |
| POST | `/api/v1/risk-policies` | Risk Policies | True | Create Risk Policy |
| POST | `/api/v1/risk-policies/position-plans` | Risk Policies | True | Create Position Plan |
| POST | `/api/v1/risk/check` | step32 | True | Risk Check |
| POST | `/api/v1/risk/daily-loss/check` | Daily Loss Monitor | False | Check Daily Loss Now |
| GET | `/api/v1/risk/daily-loss/events` | Daily Loss Monitor | False | List Daily Loss Events |
| POST | `/api/v1/risk/daily-loss/reset` | Daily Loss Monitor | True | Reset Daily Loss Monitor |
| GET | `/api/v1/risk/daily-loss/status` | Daily Loss Monitor | False | Get Daily Loss Monitor Status |
| POST | `/api/v1/risk/exit-decision` | Risk | True | Evaluate Exit |
| GET | `/api/v1/risk/kill-switch` | Risk Kill Switch | False | Get Kill Switch State |
| POST | `/api/v1/risk/kill-switch/activate` | Risk Kill Switch | True | Activate Kill Switch |
| POST | `/api/v1/risk/kill-switch/deactivate` | Risk Kill Switch | True | Deactivate Kill Switch |
| PUT | `/api/v1/risk/position-limits` | Position Limits | True | Save Position Limit |
| GET | `/api/v1/risk/position-limits/{account_number}/{exchange_code}/{symbol}` | Position Limits | False | Get Position Limit |
| POST | `/api/v1/risk/position-plan` | Risk | True | Create Position Plan |
| POST | `/api/v1/scheduler-admin/run-now/{job_name}` | Scheduler Admin | False | Run Scheduled Job Now |
| POST | `/api/v1/strategy-deployment-performance/check-active` | Strategy Deployment Performance | False | Check Active Deployment Performance |
| GET | `/api/v1/strategy-deployment-performance/history` | Strategy Deployment Performance | False | Get Deployment Performance History |
| GET | `/api/v1/strategy-deployment-performance/status` | Strategy Deployment Performance | False | Get Deployment Performance Monitor Status |
| GET | `/api/v1/strategy-deployment-pipeline/history` | Strategy Deployment Pipeline | False | Get Strategy Deployment Pipeline History |
| POST | `/api/v1/strategy-deployment-pipeline/run` | Strategy Deployment Pipeline | True | Run Strategy Deployment Pipeline |
| GET | `/api/v1/strategy-deployment-pipeline/status` | Strategy Deployment Pipeline | False | Get Strategy Deployment Pipeline Status |
| POST | `/api/v1/strategy-deployments` | Strategy Deployments | True | Deploy Strategy |
| GET | `/api/v1/strategy-deployments/active` | Strategy Deployments | False | Get Active Strategy Deployment |
| POST | `/api/v1/strategy-deployments/{deployment_id}/stop` | Strategy Deployments | True | Stop Strategy Deployment |
| GET | `/api/v1/strategy-leaderboard/history` | Strategy Leaderboard | False | List Leaderboard History |
| POST | `/api/v1/strategy-leaderboard/snapshots` | Strategy Leaderboard | True | Create Leaderboard Snapshot |
| GET | `/api/v1/strategy-leaderboard/snapshots/{snapshot_id}` | Strategy Leaderboard | False | Get Leaderboard Snapshot |
| GET | `/api/v1/strategy-leaderboard/strategies/{strategy_code}/history` | Strategy Leaderboard | False | Get Strategy Rank History |
| POST | `/api/v1/strategy-performance/runs` | Strategy Performance | True | Create Performance Run |
| GET | `/api/v1/strategy-performance/runs/{run_id}` | Strategy Performance | False | Get Performance Run |
| POST | `/api/v1/strategy-performance/runs/{run_id}/complete` | Strategy Performance | True | Complete Performance Run |
| POST | `/api/v1/strategy-policy/evaluate` | Strategy Approval Policy | True | Evaluate Strategy Policy |
| GET | `/api/v1/strategy-policy/history` | Strategy Approval Policy | False | Get Strategy Policy History |
| POST | `/api/v1/strategy-policy/{approval_run_id}/force` | Strategy Approval Policy | True | Force Strategy Deployment |
| POST | `/api/v1/strategy-policy/{approval_run_id}/reject` | Strategy Approval Policy | True | Reject Strategy Policy |
| GET | `/api/v1/strategy-ranking` | Strategy Ranking | False | Get Strategy Ranking |
| GET | `/api/v1/strategy-ranking/summary` | Strategy Ranking | False | Get Strategy Performance Summary |
| POST | `/api/v1/strategy-runtime-switch` | Strategy Runtime Switch | True | Switch Strategy Runtime |
| POST | `/api/v1/strategy-runtime/clear` | Strategy Runtime | False | Clear Strategy Runtime |
| POST | `/api/v1/strategy-runtime/reload` | Strategy Runtime | False | Reload Strategy Runtime |
| GET | `/api/v1/strategy-runtime/status` | Strategy Runtime | False | Get Strategy Runtime Status |
| GET | `/api/v1/strategy-selector/latest` | Strategy Selector | False | Get Latest Strategy Selection |
| POST | `/api/v1/strategy-selector/select` | Strategy Selector | True | Select Strategy |
| POST | `/api/v1/sync/kiwoom/daily` | Synchronization | True | Sync Kiwoom Daily |
| GET | `/api/v1/system/dashboard` | System Dashboard | False | Get System Dashboard |
| POST | `/api/v1/trading-calendar/import` | Trading Calendar | True | Import Calendar Days |
| GET | `/api/v1/trading-calendar/{exchange_code}/{calendar_date}` | Trading Calendar | False | Evaluate Calendar Day |
| GET | `/api/v1/trading-calendar/{exchange_code}/{calendar_date}/next` | Trading Calendar | False | Get Next Trading Day |
| GET | `/api/v1/trading-calendar/{exchange_code}/{calendar_date}/previous` | Trading Calendar | False | Get Previous Trading Day |
| POST | `/api/v1/upbit/daily/sync` | Upbit | True | Sync Upbit Daily |
| POST | `/api/v1/upbit/daily/sync/krw-batch` | Upbit | True | Sync Upbit Krw Daily Batch |
| POST | `/api/v1/upbit/instruments/sync` | Upbit | False | Sync Upbit Instruments |
| GET | `/api/v1/upbit/markets` | Upbit | False | List Upbit Markets |
| POST | `/api/v1/upbit/minute/sync` | Upbit | True | Sync Upbit Minute |
| POST | `/api/v1/walk-forward` | Walk Forward | True | Run Walk Forward Validation |
| GET | `/api/v1/walk-forward-performance/runs/{run_id}/windows` | Walk Forward Performance | False | Get Walk Forward Windows |
| POST | `/api/v1/walk-forward-performance/save` | Walk Forward Performance | True | Save Walk Forward Performance |
| GET | `/health` | Health | False | Health |
| GET | `/version` | Version | False | Version |
