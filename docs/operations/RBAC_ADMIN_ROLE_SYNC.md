# STEP 8-9C-1 — Admin RBAC 정합

## 증상

Admin UI는 들어가지만 `/api/v1/admin/**` 가 `FORBIDDEN / 관리자 권한이 필요합니다` 를 반환.

## 원인

- 화면 게이트: `user.roles`(JSONB) 폴백 포함
- Admin API `require_admin`: `auth.user_role`만 검사
- Bootstrap admin 생성 시 `RbacRepository` 미주입 → JSONB만 `admin`, `user_role` 누락

## 수정

1. Bootstrap에 RBAC sync
2. 로그인/`require_admin`/`get_current_user`에서 JSONB↔`user_role` 치유
3. Alembic `p5f6a7b8c9d0` backfill

## 관리자 승격 (기존 기능)

Admin → 회원관리에서 대상 회원 수정 → Role에 `admin` 선택 후 저장.

또는 권한 API:

```http
PUT /api/v1/roles/users/{user_id}
{"roles": ["admin"]}
```

(이미 Admin JWT가 통과하는 상태에서만 호출)

직접 SQL UPDATE는 사용하지 않는다.
