# STEP 04 — 인증·사용자·관리자 Repository 정리

> 작성일: 2026-07-22  
> 목표: Auth 서비스가 Repository private(`_session`)에 접근하지 않도록 계약을 맞추고 Fake와 실구현을 동기화한다.

---

## 1. 분석 결과

### 1.1 `_repository._session` 사용처 (수정 전)

| 위치 | 용도 |
|------|------|
| `AuthService._register_failed_login` | flush |
| `AuthService.change_password` | password_change_required 반영 flush |
| `AuthService.complete_onboarding` | flush |
| `AuthService.unlock_user` | flush |
| `UserAdminService.create_member` | password_change_required flush |
| `UserAdminService.unlock_member` | flush |
| `UserAdminService.list_member_accounts` | `UserProfileService(session)` 주입 |

### 1.2 Fake 계약 불일치 (STEP2/3 실패 원인)

| Fake | 문제 |
|------|------|
| `test_auth_signup.FakeRepo` | `mark_last_login` 없음, `revoke_refresh(reason=)` 미지원 |
| `test_user_admin._FakeRepo` | `_session` / `set_password_change_required` 없음 |
| `test_auth_jwt.FakeRepo` | `_session` 우회 flush에 의존 |

---

## 2. Repository 공개 계약 (추가)

`AuthRepository`에 다음을 추가했다.

| 메서드 | 역할 |
|--------|------|
| `flush()` | ORM flush |
| `get_session()` | 동일 트랜잭션용 Session (private 접근 대체) |
| `record_failed_login(...)` | 실패 카운트·잠금 |
| `clear_lockout(user)` | 잠금 해제 |
| `mark_onboarding_completed(user)` | 온보딩 완료 |
| `set_password_change_required(user, required=)` | 비밀번호 변경 강제 플래그 |

기존 유지: `get_by_id`, `get_by_username`, `mark_last_login`, `revoke_refresh(*, reason=)`, `update_password`, `save_refresh_token` 등.

---

## 3. 수정한 파일

| 파일 | 내용 |
|------|------|
| `src/stock_platform/auth/repository.py` | 공개 계약 메서드 추가 |
| `src/stock_platform/auth/service.py` | `_session` 제거, repository 메서드 사용 |
| `src/stock_platform/auth/user_admin_service.py` | `_session` 제거, `get_session()` 사용 |
| `tests/test_auth_signup.py` | FakeRepo 계약 정렬 |
| `tests/test_user_admin.py` | _FakeRepo 계약 정렬 |
| `tests/test_auth_jwt.py` | FakeRepo 정리 (`_session` 제거) |
| `tests/test_admin_user_unlock.py` | `clear_lockout` mock |
| `tests/test_auth_repository_contract.py` | **신규** 계약 단위 테스트 |

---

## 4. 테스트 결과

```powershell
pytest tests/test_auth_signup.py tests/test_user_admin.py tests/test_auth_jwt.py `
  tests/test_admin_user_unlock.py tests/test_auth_repository_contract.py `
  tests/test_auth_user_status.py tests/test_refresh_cookie.py -q
# → 전부 통과

pytest -q
```

| | STEP3 후 | STEP4 후 |
|--|----------|----------|
| failed | 13 | **7** |
| 해결 | — | auth signup 2 + user_admin 4 |
| 잔여 | — | 예외 5 + scheduler 1 + kill-switch 1 |

### 해결된 실패 (STEP2 목록)

- `test_auth_signup` 2건
- `test_user_admin` 4건

### 잔여 실패 (후속 STEP)

- 예외 코드 5건 → STEP5
- AutomaticScheduler 1건 → STEP9
- Kill Switch Fake 1건 → STEP8

---

## 5. 검증

- `src/stock_platform/auth/` 내 `_repository._session` **호출 코드 없음** (docstring 언급만)
- Fake와 실 Repository가 동일 메서드명을 사용

---

## 6. 남아 있는 문제

- `get_session()`은 Session을 노출한다. Profile 등 동일 트랜잭션 조합을 위한 최소 공개 API이며, private `_session` 직접 접근보다는 안전하다.
- RBAC Fake 통합·DB 통합 인증 E2E는 범위 밖(기존 통과분 유지).

---

## 7. 다음 단계

**STEP5** — 예외 계층과 API 오류 매핑 (`EXTERNAL_API_ERROR`, `KIWOOM_API_ERROR` 등).

---

## 8. 권장 커밋 메시지

```text
fix(step04): align auth repository contracts and remove private session access
```
