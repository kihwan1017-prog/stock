# API.md — stock-platform v1.0.0

상세 엔드포인트·매뉴얼: [docs/backend/API.md](docs/backend/API.md) · [docs/manual/API사용매뉴얼.md](docs/manual/API사용매뉴얼.md)

---

## 1. OpenAPI / Swagger

| 환경 | `/docs` · `/redoc` · `/openapi.json` |
|------|--------------------------------------|
| `APP_ENV=local` (개발) | 활성 — http://127.0.0.1:8000/docs |
| `production` / `staging` | **비활성** (보안) |

기계용 스펙(개발): `GET /openapi.json`  
앱 버전: FastAPI `version` = `APP_VERSION` (기본 `1.0.0`) · `GET /version`

---

## 2. Authentication

| 방식 | 사용법 |
|------|--------|
| JWT | `Authorization: Bearer <access_token>` |
| Admin Key | `X-Admin-API-Key: <ADMIN_API_KEY>` |
| Login | `POST /api/v1/auth/login` → access + refresh |
| Refresh | `POST /api/v1/auth/refresh` |
| Me | `GET /api/v1/auth/me` |

운영 Signup: **403** (Admin이 사용자 생성)

---

## 3. 공통 응답 / 에러

성공: 엔드포인트별 JSON  
에러 (통일):

```json
{
  "code": "HTTP_400",
  "message": "human readable",
  "detail": {},
  "request_id": "uuid-or-trace"
}
```

대표 상태 코드: `200` · `201` · `400` · `401` · `403` · `404` · `409` · `422` · `429` · `500`

---

## 4. 핵심 엔드포인트 (요약)

### System

| Method | Path | Auth |
|--------|------|------|
| GET | `/` | 없음 |
| GET | `/health` | 없음 (prod 최소) |
| GET | `/health/live` | 없음 |
| GET | `/health/ready` | 없음 |
| GET | `/version` | 없음 |

### Auth / Admin Ops

| Method | Path | Auth |
|--------|------|------|
| POST | `/api/v1/auth/login` | 없음 |
| GET | `/api/v1/monitoring/overview` | Admin |
| POST | `/api/v1/risk/kill-switch/activate` | Admin |

### Trading

| Method | Path | Auth / 비고 |
|--------|------|-------------|
| POST | `/api/v1/order-execution/submit` | JWT/Admin + Risk/Kill |
| POST | `/api/v1/orders/{id}/cancel` | 소유권/권한 |
| POST | `/api/v1/paper-orders` | Risk + Kill |

전체 목록은 개발 환경 Swagger 또는 OpenAPI JSON을 기준으로 합니다.

---

## 5. 예시

### Login

```http
POST /api/v1/auth/login
Content-Type: application/json

{"username":"admin","password":"..."}
```

```json
{
  "access_token": "...",
  "refresh_token": "...",
  "token_type": "bearer"
}
```

### Version

```http
GET /version
```

```json
{
  "version": "1.0.0",
  "build_version": "1.0.0",
  "git_commit": "abc1234",
  "environment": "local",
  "app_name": "stock-platform",
  "uptime_seconds": 12.3,
  "started_at": "2026-07-20T00:00:00+00:00"
}
```

---

## 6. 주의 (Known Issues)

일부 pipeline/AI/sync/runtime API는 **인증이 없을 수 있습니다.**  
공개망 노출 금지. 상세: [KNOWN_ISSUES.md](KNOWN_ISSUES.md)
