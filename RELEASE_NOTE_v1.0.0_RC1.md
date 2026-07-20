# RELEASE_NOTE — v1.0.0-RC1

**버전:** 1.0.0-RC1  
**일자:** 2026-07-20  
**성격:** Production Readiness (기능 동결 · 운영 준비)

---

## 요약

Stock Platform을 **내부망·단일 운영자** 기준 Release Candidate로 정리했습니다.  
신규 비즈니스 기능은 추가하지 않았고, 보안·설정·문서·검증을 중심으로 RC1을 구성합니다.

---

## 신규 기능 (이전 STEP 누적 · RC1 범위에 포함)

- Auth / JWT / RBAC / Admin·User Web
- Paper 주문·포지션 · Order Outbox · Kill Switch · Daily Loss
- Position Exit Monitor · Telegram Ops · Notification Publisher
- Ollama AI · News/Disclosure · Strategy Deployment
- Operations Center · Settings Catalog · DB 안정화(STEP57)
- 성능 핫패스 최적화(STEP58)

---

## 변경 사항 (STEP59 RC1)

### 보안
- Broker 주문/승인, Realtime Strategy, Kiwoom Order WS, Broker Recovery, Order State Transition, Strategy Deployment, Realtime Safety → **`require_admin`**
- `APP_ENV=production|staging` 시 **Swagger/OpenAPI 비활성**
- 운영 환경 **공개 Signup 403**
- 운영 CORS: `CORS_ALLOW_ORIGINS` 필수 · localhost 단독 거부

### 운영 설정
- `LOG_LEVEL`, `CORS_ALLOW_ORIGINS` 설정 추가
- `.env.example` bootstrap 비밀번호 placeholder화
- 에러 응답 포맷 통일 (`code` / `message` / `detail` / `request_id`)
- 미처리 Exception · Validation · HTTPException 핸들러 보강

### 문서
- `RELEASE_CHECKLIST.md`
- `KNOWN_ISSUES.md`
- `README_STEP59.md`
- 본 Release Note

---

## 보안 개선 (누적)

- DEV_OPEN 제거 (미설정 ADMIN_API_KEY로 열린 Admin 금지)
- JWT 운영 필수 / 개발 auto-secret 분리
- OpenClaw 제거 (공격·미구현 표면 축소)

---

## 성능 개선 (STEP58)

- DB Connection Pool 명시
- Exit Monitor `to_thread` · 로그 축소
- Ollama `keep_alive` + tags TTL cache
- Lifecycle 알림 timeout

---

## 리팩토링

- STEP56 Technical Debt Cleanup (dead packages 제거, RiskService 복구)
- STEP57 DB FK/Index/Comment

---

## Breaking Change

| 변경 | 영향 |
|------|------|
| 무인증 Broker/Realtime mutate API → Admin 필수 | 스크립트는 `ADMIN_API_KEY` 또는 Admin JWT 필요 |
| 운영에서 `/docs` 비활성 | 내부망에서만 OpenAPI 필요 시 `APP_ENV=local` 또는 별도 스테이징 |
| 운영 Signup 금지 | 사용자는 Admin Users API로 생성 |
| 운영 CORS localhost 단독 불가 | 실제 Origin 설정 필요 |
| HTTPException 응답이 `{detail}` → `{code,message,detail,request_id}` | FE가 `detail` 문자열만 파싱하면 조정 필요할 수 있음 |

---

## 설치·업그레이드

1. secrets env 준비 (`JWT_SECRET`, `ADMIN_API_KEY`, DB, CORS)
2. `alembic upgrade head`
3. `python scripts/check_db_integrity.py`
4. API/Frontend 기동
5. `RELEASE_CHECKLIST.md` 전부 체크

---

## 지원 범위

- ✅ Paper / 내부 운영 데모
- ✅ Telegram 원격 모니터링 (설정 시)
- ⚠️ Live 주문 — 체크리스트·별도 승인 후
- ❌ 멀티테넌시 SaaS / OpenClaw
