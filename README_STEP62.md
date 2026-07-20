# README_STEP62 — Security Hardening

## 목적

인증·권한·주문·Admin·Secret·로그·API 노출을 최종 점검하고 강화합니다.  
자동매매 전략/주문 판단 로직은 변경하지 않습니다.

---

## 보안 구조

```
Client → CORS Allowlist → Security Headers
      → JWT/Admin Key → RBAC (DB)
      → Account Ownership
      → Rate Limit (민감 API)
      → Business / Risk Guards
```

---

## 변경 파일 (요약)

- `auth/deps.py` — Admin JWT DB 역할 재검증  
- `auth/service.py` — Refresh 재사용 시 전체 revoke  
- `auth/jwt_service.py` — HS256 only  
- `auth/account_ownership.py` — trading account 소유권  
- `common/rate_limit.py` · `security_mask.py` · `logger.py`  
- `api/security_middleware.py` · `main.py` CORS/Header  
- 다수 `api/v1/*` — `require_admin` / 소유권 / webhook secret  
- `tests/test_security_step62.py`  
- `SECURITY_AUDIT_STEP62.md`

---

## 인증 및 권한

- Access/Refresh JWT, 비활성 사용자 차단  
- Admin: `X-Admin-API-Key` 또는 admin/`ops:execute` JWT (DB 기준)  
- 로그인 실패·성공 Audit  

## 계정 소유권

- Paper: `assert_paper_account_access`  
- Order: `assert_trading_account_access`  

## 주문 보호

- Live 플래그·mock 교차 (기존)  
- Pending/Paper fill/실시간 제어 → Admin  

## Rate Limit

로그인·refresh·비밀번호·알림 테스트·Telegram webhook

## CORS / Swagger

- CORS methods/headers 명시 목록  
- 운영 Swagger 비활성  
- 운영 `/health` 최소 정보  

## Secret / 로그

- Webhook secret env  
- structlog·Audit 마스킹  

## 보안 테스트

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_security_step62.py -q
.\.venv\Scripts\python.exe -m pytest -q
```

## 운영 시 주의

1. 공개망 직접 노출 금지  
2. `TELEGRAM_WEBHOOK_SECRET` 설정  
3. FE Remember-me(localStorage) XSS 주의  
4. Live 주문은 별도 승인  
5. 상세 감사: `SECURITY_AUDIT_STEP62.md`

## 검증 (2026-07-20)

| 검사 | 결과 |
|------|------|
| pytest | **349 passed**, 3 skipped |
| FE lint/typecheck/test/build | PASS |
| pip audit | 도구 미설치 (문서화) |
