# SECURITY_REVIEW_STEP74

## 범위

STEP65–73 사용자 Self API + Frontend 사용자 영역.

## 결과 요약

| 등급 | 건수 |
|------|------|
| Critical | 0 |
| High | 0 (범위 내) |
| Medium | 3 |
| Low | 若干 |

---

## Broken Access Control / IDOR

- `user_*` 라우터: `user_id`는 JWT만. Path의 resource id는 서비스에서 소유권 검증.
- Admin `/api/v1/users`, `/settings`, `/ollama`는 별도 권한.
- 테스트: STEP65 403, STEP73 session 404, STEP74 401 스모크.

## Authentication / Session

- bcrypt rounds=12
- Refresh reuse → 전체 revoke
- 비밀번호 변경 Rate Limit + 타 세션 revoke
- Profile에 JWT/Token 미표시

## Injection / XSS

- `dangerouslySetInnerHTML` 없음
- Profile HTML `<>` 차단
- AI Prompt Injection 방어는 STEP69/70 서비스 로직(문서·테스트 존재)

## Secret Leakage

- NEXT_PUBLIC에 KEY/SECRET/TOKEN 없음
- 응답에서 password_hash, broker secret, bot token 제외
- `userApi` admin settings/ollama 래퍼 **제거**(F74-01)

## Rate Limit

- login / refresh / change-password / revoke sessions / user change-password

## Medium 잔여

1. Telegram DLQ/retry worker 없음
2. Trading 계열 페이지가 admin realtime API를 호출 → 일반 유저 403 (보안은 유지, UX 혼재)
3. npm `postcss` moderate (next 종속) — Major 강제 미적용

## Logging

- `security_mask.redact_mapping` + structlog processor
- Audit에 비밀번호 원문 미기록
