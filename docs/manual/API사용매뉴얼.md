# API 사용 매뉴얼

기준: FastAPI OpenAPI (`Stock Platform API` v1.0.0)  
대화형 문서: `http://127.0.0.1:8000/docs` · 스키마: `/openapi.json`

> Request/Response JSON 스키마의 **단일 소스 오브 트루스**는 OpenAPI입니다.  
> 본 문서는 권한·예제·전체 엔드포인트 목록을 제공합니다. 본문에 없는 필드를 추측하지 마세요.

## 목차

1. [공통](#공통)
2. [권한](#권한)
3. [주요 예제](#주요-예제)
4. [API 그룹 요약](#api-그룹-요약)
5. [전체 엔드포인트 목록](#전체-엔드포인트-목록)

---

## 공통

| 항목 | 값 |
|------|-----|
| Base | `http://127.0.0.1:8000` |
| Prefix | 대부분 `/api/v1/...` (`/health`, `/version`, `/` 예외) |
| Content-Type | `application/json` |
| CORS (Admin) | `http://localhost:3000`, `http://127.0.0.1:3000` |

요약 표(일부): [../backend/API.md](../backend/API.md)

---

## 권한

| 구분 | 헤더 | 동작 |
|------|------|------|
| 일반 | 없음 | 대부분 공개 (네트워크 노출 주의) |
| Admin | `X-Admin-API-Key: <ADMIN_API_KEY>` | `require_admin` 의존성 |
| 키 미설정 | — | 개발 모드로 통과 (`DEV_OPEN`) |

### Admin 보호 엔드포인트 (코드 기준)

| Method | Path |
|--------|------|
| GET | `/api/v1/audit/events` |
| POST | `/api/v1/scheduler-admin/run-now/{job_name}` |
| POST | `/api/v1/orders/{order_id}/dispatch` |
| POST | `/api/v1/risk/kill-switch/activate` |
| POST | `/api/v1/risk/kill-switch/deactivate` |
| POST | `/api/v1/broker/live-transition/request` |
| POST | `/api/v1/broker/live-transition/{transition_id}/approve` |
| POST | `/api/v1/broker/live-transition/{transition_id}/disable` |
| GET | `/api/v1/broker/live-transition/history` |
| POST | `/api/v1/strategy-policy/{approval_run_id}/force` |
| POST | `/api/v1/strategy-policy/{approval_run_id}/reject` |

그 외 엔드포인트는 OpenAPI에 인증 스키마가 없어도 **운영 네트워크에서 보호**해야 합니다.

---

## 주요 예제

### Health

```http
GET /health
```

응답 예(구조는 환경에 따라 다름): `status`, `components.database`, `ollama`, `live_trading` 등.

### System dashboard

```http
GET /api/v1/system/dashboard
```

### Kill Switch 조회 / 활성화

```http
GET /api/v1/risk/kill-switch

POST /api/v1/risk/kill-switch/activate
X-Admin-API-Key: <ADMIN_API_KEY>
Content-Type: application/json

{}
```

Body 필드는 `/docs`에서 확인하세요.

### Scheduler 즉시 실행

```http
POST /api/v1/scheduler-admin/run-now/candidate_screening
X-Admin-API-Key: <ADMIN_API_KEY>
```

### Paper 주문 생성

```http
POST /api/v1/paper-orders
Content-Type: application/json
```

필수 필드는 OpenAPI `Paper Orders` → Create Paper Order 스키마를 따릅니다.

### AI 분석 실행

```http
POST /api/v1/ai-analysis/{exchange_code}
Content-Type: application/json
```

Ollama 기동 필요.

### curl 공통 패턴

```powershell
curl.exe -s http://127.0.0.1:8000/health
curl.exe -s -H "X-Admin-API-Key: $env:ADMIN_API_KEY" http://127.0.0.1:8000/api/v1/audit/events
```

---

## API 그룹 요약

OpenAPI tag / prefix 기준 (구현됨):

| 영역 | Prefix 예 |
|------|-----------|
| Health / Version | `/health`, `/version` |
| System / Audit | `/api/v1/system/dashboard`, `/api/v1/audit` |
| Market / Prices | `/api/v1/market`, `/api/v1/prices`, `/api/v1/indicators` |
| Kiwoom / Upbit / Sync | `/api/v1/kiwoom`, `/api/v1/upbit`, `/api/v1/sync` |
| Candidates / AI | `/api/v1/candidates`, `/api/v1/ai-*`, `/api/v1/ai/candidates` |
| News / DART | `/api/v1/news`, `/api/v1/dart` |
| Backtest / Walk-forward / Portfolio | `/api/v1/backtest*`, `/api/v1/walk-forward*`, `/api/v1/portfolio-*` |
| Strategy | `/api/v1/strategy-*` |
| Risk | `/api/v1/risk*`, `/api/v1/realtime-risk` |
| Orders / Outbox / Executions | `/api/v1/orders`, `/api/v1/order-*`, `/api/v1/executions` |
| Paper | `/api/v1/paper-*` |
| Broker / Live | `/api/v1/broker/*` |
| Realtime | `/api/v1/realtime-*` |
| Jobs / Scheduler / Pipelines | `/api/v1/jobs`, `/api/v1/scheduler-admin`, `/api/v1/pipelines` |
| Notifications / Calendar / Reports | `/api/v1/notification`, `/api/v1/trading-calendar`, `/api/v1/daily-reports` |

---

## 전체 엔드포인트 목록

아래 표는 `app.openapi()`에서 생성한 **전체 경로**입니다.  
`Has body=True`이면 Request Body가 있습니다. 상세 스키마·응답 코드는 `/docs`를 여세요.

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
