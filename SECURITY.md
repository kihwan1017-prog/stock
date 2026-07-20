# SECURITY.md — stock-platform v1.0.0

관련: [SECURITY_AUDIT_STEP62.md](SECURITY_AUDIT_STEP62.md) · [KNOWN_ISSUES.md](KNOWN_ISSUES.md) · [FINAL_AUDIT_REPORT.md](FINAL_AUDIT_REPORT.md)

---

## 1. 위협 모델 (제품 전제)

| 전제 | 설명 |
|------|------|
| 네트워크 | 사설망 / VPN / 역프록시 뒤. **공개망 직접 노출 금지** |
| 사용자 | 단일 운영자 또는 소수 Admin |
| 주문 | Paper 기본 · Live는 별도 승인 + env 게이트 |
| 시크릿 | `E:\StockTrading\secrets\stock-platform.env` (Git 금지) |

---

## 2. 인증 / 인가

| 메커니즘 | 용도 |
|----------|------|
| JWT Bearer | Admin/User Web, 보호된 API |
| `X-Admin-API-Key` | 스크립트·자동화 Admin |
| DB RBAC | `require_admin` — JWT role claim만 믿지 않음 |
| Refresh reuse | 감지 시 해당 사용자 세션 일괄 revoke |

운영(`production`/`staging`):

- `JWT_SECRET` 필수
- Signup **403**
- Swagger/OpenAPI **비활성**
- CORS: `CORS_ALLOW_ORIGINS` 필수, localhost 단독 거부

---

## 3. 주문 보안

- Canonical 경로: `OrderExecutionService.submit`
- Kill Switch / Daily Loss / Risk Policy 적용 (경로별 편차 → Known Issues)
- Live: `KIWOOM_LIVE_ORDER_ENABLED` + DB live-transition
- Account ownership: `assert_trading_account_access` (주문 IDOR 완화)

---

## 4. 시크릿·로깅

- JWT / Broker / Telegram / DB 비밀번호는 env만
- 로그·Audit에 마스킹 (`security_mask`)
- `NEXT_PUBLIC_*`에 시크릿 금지

필수 점검:

```text
JWT_SECRET
ADMIN_API_KEY
DB_PASSWORD
KIWOOM_APP_KEY / KIWOOM_SECRET_KEY
TELEGRAM_BOT_TOKEN
TELEGRAM_WEBHOOK_SECRET   # 사용 시 필수 권장
```

---

## 5. Telegram

- Chat allowlist: `TELEGRAM_ALLOWED_CHAT_IDS` (미설정 시 명령 거부)
- Webhook: `TELEGRAM_WEBHOOK_SECRET` 설정 시 헤더 검증
- **Known Issue:** secret 미설정 시 검증 스킵 → 운영에서는 반드시 설정

---

## 6. Rate Limit / Headers

- In-memory rate limit (단일 인스턴스 전제)
- Security headers middleware
- XFF 신뢰는 역프록시 구성에 의존 → 공개망 금지 이유 중 하나

---

## 7. 잔여 Critical (배포 제약)

STEP63 감사 기준 — 공개망/고객 Live 차단:

1. 일부 mutate API 무인증 (pipeline, AI, sync, strategy-runtime 등)
2. Outbox Paper 고정
3. Webhook secret fail-open
4. `account_id=1` 하드코딩 경로

상세 우선순위: [TOP_100_IMPROVEMENTS.md](TOP_100_IMPROVEMENTS.md)

---

## 8. 보안 인시던트

의심 시: [INCIDENT_RESPONSE.md](INCIDENT_RESPONSE.md)  
즉시: Kill Switch 활성화 · API 중지 · 시크릿 로테이션 · 감사 로그 보존
