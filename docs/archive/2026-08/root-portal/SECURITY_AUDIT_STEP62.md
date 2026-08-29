# SECURITY_AUDIT_STEP62.md

**일자:** 2026-07-20  
**범위:** Authentication · Authorization · Order · Admin · CORS · Rate Limit · Secrets · Logs  
**제약:** 자동매매 로직 미변경 · Schema 변경 없음 · 실주문/실 Telegram 미실행

---

# Executive Summary

Critical 무인증 mutate/조회 API 다수를 `require_admin`으로 봉쇄했습니다.  
JWT는 DB RBAC 재검증, Refresh 재사용 시 세션 전체 폐기, Rate Limit·보안 Header·로그 마스킹을 추가했습니다.

**운영망(VPN/사설) + Admin 인증 전제**에서 RC 배포 가능.  
공개망 직접 노출은 여전히 비권장입니다.

---

# Authentication

| 항목 | 상태 |
|------|------|
| alg=none | 미허용 (algorithms 고정 HS256) |
| JWT Secret | 운영 필수 |
| Access/Refresh 만료 | 설정값 적용 |
| Refresh 회전 | revoke 후 재발급 |
| Refresh 재사용 | **전체 세션 폐기** (STEP62) |
| 비활성 사용자 | 차단 |
| Token query string | 미사용 |
| Login Rate Limit | **20/min IP** |

---

# Authorization

Critical 라우터에 `require_admin` 일괄 적용:

- realtime-sessions / realtime-execution / strategy-runtime  
- paper-executions / paper-simulation  
- kiwoom pending-orders / kiwoom config·token  
- risk-policies / position-limits / daily-loss  
- strategy-deployment-pipeline  
- admin-summary / system dashboard  
- kill-switch GET / jobs GET·history  

`require_admin`은 JWT **claim roles가 아니라 DB 역할**을 재검증합니다.

---

# Account Ownership

- Paper: 기존 `assert_paper_account_access`  
- Trading Order 조회/취소/정정: `assert_trading_account_access` 추가  
- 비admin list는 `account_id` 필수

---

# Order Security

- 직접 create 주문 API 비활성 (기존)  
- Live: `KIWOOM_LIVE_ORDER_ENABLED` + mock 교차 가드 (기존)  
- Pending modify/cancel: Admin 필수  
- Paper fill: Admin 필수  

---

# Admin API

무인증 Admin/운영 API를 Admin 보호로 전환.  
Kiwoom `token/test`는 **운영에서 403**.

---

# CORS

- Allowlist env 유지  
- methods/headers를 필요 목록으로 축소 (wildcard 제거)  
- credentials + `*` origin 금지 (운영 검증 유지)

---

# Swagger/OpenAPI

운영에서 `/docs` `/redoc` `/openapi.json` 비활성 (STEP59 유지).

`/health` 운영: DB 상태 최소 공개.  
`/health/live` · `/health/ready` 분리 (STEP61).

---

# Rate Limit

메모리 슬라이딩 윈도우 (`common/rate_limit.py`):

| Scope | Limit |
|-------|-------|
| login | 20 / 60s |
| refresh | 60 / 60s |
| change-password | 10 / 300s |
| notification/test | 10 / 60s |
| telegram webhook | 120 / 60s |

다중 인스턴스 공유는 미구현 (Remaining).

---

# Input Validation / SQL Injection

- 주문 필드 max_length/gt 보강  
- 동적 f-string SQL 미발견  
- Docs CMS path traversal 방어 유지  

---

# Secret Management

- DEV_OPEN 없음  
- `.env.example` placeholder  
- `TELEGRAM_WEBHOOK_SECRET` 추가  
- JWT_ALGORITHM HS256 only  

---

# Log Masking

- structlog `structlog_redact_processor`  
- Audit `redact_mapping`  
- 계좌/이메일/토큰 마스킹 유틸  

---

# Frontend Security

| 항목 | 상태 |
|------|------|
| localStorage 토큰 | **잔여** (Remember-me) — Medium |
| dangerouslySetInnerHTML | 없음 |
| NEXT_PUBLIC secrets | 없음 |
| 메뉴 숨김만 권한 | Backend 검증 필수 (강화됨) |

---

# Telegram Security

- Allowed Chat ID fail-closed (기존)  
- Webhook Secret-Token 검증 (설정 시)  
- 명령 테스트 Admin only  

---

# AI Security

- Ollama는 주문 직접 실행 경로 없음 (기존 Risk 계층)  
- Semaphore/동시성 제한은 잔여 (KNOWN_ISSUES)

---

# Dependency Vulnerabilities

| 도구 | 결과 |
|------|------|
| npm audit | **moderate 2** — `postcss`/`next` (GHSA-qx2v-qp2m-jg93). `npm audit fix --force`는 Next 메이저 다운그레이드 위험 → **미적용**, Next 패치 대기 |
| pip audit | 패키지 미설치 — 운영 전 `pip install pip-audit` 후 점검 |

강제 메이저 업그레이드는 수행하지 않음.

---

# Applied Fixes

1. Critical mutate/조회 API `require_admin`  
2. `require_admin` DB RBAC 재검증  
3. Refresh reuse → revoke all  
4. Order IDOR 소유권 검사  
5. Rate limit + Security headers  
6. CORS methods/headers 축소  
7. Telegram webhook secret  
8. 로그/Audit 마스킹  
9. 운영 `/health` 최소 공개 · kiwoom token/test 비활성  
10. 보안 테스트 `tests/test_security_step62.py`

---

# Remaining Risks

| 우선순위 | 내용 |
|----------|------|
| High | 일부 AI/pipeline/indicator execute API 권한 불균일 잔존 가능 |
| High | FE localStorage 토큰 (XSS 시 탈취) |
| Medium | Rate limit 단일 인스턴스 전용 |
| Medium | `/health` 로컬에서는 상세 유지 |
| Medium | account_id=1 runtime 하드코딩 잔존 |
| Low | npm/pip audit 지속 모니터링 |

---

# Production Recommendations

1. `TELEGRAM_WEBHOOK_SECRET` 설정 후 setWebhook  
2. `CORS_ALLOW_ORIGINS` 실제 Origin만  
3. VPN/역프록시 뒤 배치  
4. Live 주문은 체크리스트+승인 후  
5. `pip-audit` / `npm audit` 정기 실행  
6. Admin API Key·JWT Secret 로테이션 절차  

---

# Priority Legend

- **Critical** — 무인증 주문/런타임 제어 (완화됨)  
- **High** — IDOR·정보 노출·토큰 저장  
- **Medium** — 운영 편의/확장성  
- **Low / Informational** — 관측·문서
