# API 개요 — stock-platform v1.0.0

루트 요약: [../../API.md](../../API.md)

OpenAPI (local only): `http://127.0.0.1:8000/docs`  
OpenAPI JSON: `http://127.0.0.1:8000/openapi.json`  
운영(`production`/`staging`)에서는 docs/openapi **비활성**.  
사람용 매뉴얼: [../manual/API사용매뉴얼.md](../manual/API사용매뉴얼.md)

앱 버전: `APP_VERSION` / `GET /version` → **1.0.0**

## 인증

| 방식 | 헤더 / 경로 | 용도 |
|------|-------------|------|
| JWT | `Authorization: Bearer <access>` | Admin Web, 회원·설정·문서 CMS |
| Admin Key | `X-Admin-API-Key: <ADMIN_API_KEY>` | 감사·Kill Switch·live transition·dispatch 등 |
| 로그인 | `POST /api/v1/auth/login` | access + refresh 발급 |

## Auth / RBAC

| Method | Path | 인증 |
|--------|------|------|
| POST | `/api/v1/auth/login` | 없음 |
| POST | `/api/v1/auth/refresh` | refresh |
| GET | `/api/v1/auth/me` | JWT |
| GET/POST/PUT/DELETE | `/api/v1/users` | JWT + users:* |
| GET/PUT | `/api/v1/roles` | JWT + roles:* |

## Settings / Ops

| Method | Path | 인증 |
|--------|------|------|
| GET/PUT | `/api/v1/settings` | JWT + settings:* |
| GET | `/api/v1/ops/db/status` | JWT + system:read |
| GET | `/api/v1/audit/events` | Admin |
| GET | `/api/v1/docs` | JWT (menu:docs 등) |
| GET | `/api/v1/docs/{slug}` | JWT |

## Trading

| Method | Path | 인증 / 비고 |
|--------|------|-------------|
| POST | `/api/v1/order-execution/submit` | Risk + Kill Switch **필수** |
| POST | `/api/v1/orders/{id}/cancel` | Live는 env+transition 가드 |
| POST | `/api/v1/paper-orders` | Risk + Kill Switch |
| POST | `/api/v1/strategy-deployments` | PAPER만 |
| POST | `/api/v1/strategy-deployments/{id}/update` | 파라미터 재배포 |

## 리스크 / 실전

| Method | Path | 인증 |
|--------|------|------|
| GET | `/api/v1/risk/kill-switch` | Admin (STEP62) |
| POST | `/api/v1/risk/kill-switch/activate` | Admin |
| POST | `/api/v1/broker/live-transition/*/approve` | Admin |

## AI / 후보

| Method | Path |
|--------|------|
| POST | `/api/v1/candidate-runs` |
| POST | `/api/v1/ai-analysis/{exchange}` |
| GET | `/api/v1/ollama/status` |
