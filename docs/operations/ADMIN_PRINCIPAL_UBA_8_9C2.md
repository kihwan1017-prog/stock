# STEP 8-9C-2 — Admin Principal / UBA actor

## require_admin 반환 계약

`require_admin()` 은 **문자열을 반환하지 않는다**.

표준 Principal: `AuthenticatedUser`

| 필드 | 설명 |
|------|------|
| `user_id` | JWT 관리자 ID. API Key 인증 시 `0` |
| `username` | 로그인 사용자명. API Key 시 `ADMIN_KEY` |
| `roles` | DB RBAC(+치유) 기준 역할 |
| `permissions` | 권한 코드 목록 |
| `is_admin` | `"admin" in roles` (정규화 포함) |

경로:

1. Admin JWT → DB `admin` 역할 사용자 Principal
2. `X-Admin-API-Key` → 합성 Principal (`user_id=0`)

## actor 생성 규칙

```python
from stock_platform.auth.deps import admin_actor_label

actor = admin_actor_label(principal)  # "admin:{user_id}"
```

- 잘못된 Principal 타입 → **401 Fail Closed** (500/`AttributeError` 금지)
- username 문자열을 user_id 로 파싱하지 않음

## owner vs actor

| 개념 | 의미 |
|------|------|
| `owner_user_id` | UBA **계좌 소유자** (요청 body) |
| `actor` (`admin:{id}`) | **현재 로그인한 관리자** (감사 로그) |

동일 숫자여도 의미가 다르다. 혼동 금지.

## UBA 생성 (`POST /api/v1/admin/broker-accounts`)

정상: **201**

- `live_order_enabled=false`, `live_armed=false` 강제
- Credential 미등록 상태
- UPBIT + `apply_recommended_risk` → Risk **5000 / max_open_orders=1 / daily_order_limit=1**
- UBA + Risk 는 동일 트랜잭션 (Risk 실패 시 전체 rollback)

오류 코드:

| 상황 | HTTP |
|------|------|
| 미인증 | 401 |
| 비관리자 | 403 |
| owner 없음 | 404 |
| 중복 UBA | 409 |
| 잘못된 account_ref 등 | 422 |

실주문 / ARM / LIVE ON 은 이 API에서 수행하지 않는다.
