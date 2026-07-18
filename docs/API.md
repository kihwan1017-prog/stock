# API 개요 — stock-platform v1.0

OpenAPI: `http://127.0.0.1:8000/docs`

## 운영

| Method | Path | 인증 |
|--------|------|------|
| GET | `/health` | 없음 |
| GET | `/api/v1/system/dashboard` | 없음 |
| GET | `/api/v1/audit/events` | Admin |
| POST | `/api/v1/scheduler-admin/run-now/{job}` | Admin |

## 주문

| Method | Path | 인증 |
|--------|------|------|
| POST | `/api/v1/order-execution/submit` | 권장 Admin |
| POST | `/api/v1/orders/{id}/dispatch` | Admin |

## 리스크 / 실전

| Method | Path | 인증 |
|--------|------|------|
| GET | `/api/v1/risk/kill-switch` | 없음 |
| POST | `/api/v1/risk/kill-switch/activate` | Admin |
| POST | `/api/v1/broker/live-transition/approve` | Admin |

## AI / 후보

| Method | Path |
|--------|------|
| POST | `/api/v1/candidate-runs` |
| POST | `/api/v1/ai-analysis/{exchange}` |
| GET | `/api/v1/ai-analysis/runs/{id}` |
| POST | `/api/v1/ai-analysis/runs/{id}/reproduce` |

관리 API 헤더: `X-Admin-API-Key: <ADMIN_API_KEY>`
