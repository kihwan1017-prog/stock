# README_STEP73 — My Profile, Security & Connected Accounts

## 목적

일반 사용자가 본인 프로필·비밀번호·로그인 세션·연결 계정을  
관리자 User API와 **분리된 Self API**로 안전하게 관리한다.

---

## 기존 문제

- Profile이 `/auth/me` + 계좌 목록 조합 위주
- 프로필 PATCH·세션 list/revoke Self API 부재
- 연결 상태 통합 화면 부재
- 관리자 `/users` 와 사용자 API 경계 혼동 위험

---

## 사용자 Self API

Prefix: `/api/v1/user/profile`  
권한: `trading:read` (JWT `user_id`만 사용, Path/Body user_id 금지)

| Method | Path |
|--------|------|
| GET | `/` |
| PATCH | `/` |
| POST | `/change-password` |
| GET | `/sessions` |
| DELETE | `/sessions/{session_id}` |
| DELETE | `/sessions?exclude_current=` |
| GET | `/accounts-summary` |
| GET | `/connections` |
| DELETE | `/connections/telegram` |

관리자: `/api/v1/users` (`users:read/write`) — 그대로 유지.

기존 `POST /api/v1/auth/change-password` 도 유지 (호환).

---

## 프로필 구조

`auth.user` 확장: nickname, profile_image_url, bio, locale, email_verified, last_login_at  
(기존 password_changed_at 재사용)

이메일 변경은 이번 STEP에서 **읽기 전용**.

---

## 비밀번호 변경 후 세션 정책

- Hash: **bcrypt** (rounds=12)
- 서버에서 confirmation 검증
- Rate limit: 10회 / 5분
- `X-Refresh-Token` 이 유효하면 **현재 세션 유지**, 나머지 revoke
- 헤더 없으면 전체 revoke → 재로그인 권장
- Refresh reuse 감지 시 기존처럼 전체 폐기

---

## 로그인 세션

`auth.refresh_token` 확장: session_public_id, device/browser/OS, ip, UA, last_used_at, revoke_reason  
Raw Refresh Token은 저장하지 않음 (hash만).

응답은 public id + 마스킹 IP만 노출.

---

## 계정 소유권 / 연결

- `accounts-summary`: 현재 user_id 집계 (FE 필터 금지)
- `connections`: KIWOOM / UPBIT (STEP65 계좌) + TELEGRAM 상태
- 키움/업비트 연결·해제는 `/user/accounts` 재사용
- Telegram 일회용 연결 코드 흐름은 **후속** (상태·해제만)

---

## 민감정보 마스킹

`mask_email`, `mask_ip`, `mask_chat_id`, 계좌 마스킹 유틸 재사용.  
password_hash / token / broker secret / bot token 응답 금지.

---

## Database

Migration: `g3b4c5d6e7f8` (revises `f2a3b4c5d6e7`)  
- user 프로필 컬럼  
- refresh_token 세션 메타 + public id backfill  
- `auth.user_connection` (Telegram 등)

운영 DB 자동 적용 안 함.

---

## Frontend

`/user/profile` — 기본정보 / 비밀번호 / 세션 / 소유권 / 연결  
JWT·Token 미표시. 관리자 Users API 미호출.

---

## 테스트

```bash
.\.venv\Scripts\python.exe -m pytest tests/test_step73_user_profile.py -q
```

---

## 후속 작업

- 2FA (TOTP)
- 이메일 변경 인증
- 회원 탈퇴 / 데이터 내보내기
- Telegram 연결 코드 플로우
- Refresh Token HttpOnly Cookie 전환
- User E2E
