# GO_LIVE_CHECKLIST.md — stock-platform v1.0.0

**대상 배포:** 사설망 · 단일 운영자 · Paper 중심 · `KIWOOM_LIVE_ORDER_ENABLED=false`  
**고객 공개망 / Live SaaS:** STEP63 기준 **Go-Live 금지** (이 체크리스트를 통과해도 Live 고객 배포는 별도 감사 필요)

관련: [RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md) · [RUNBOOK.md](RUNBOOK.md) · [KNOWN_ISSUES.md](KNOWN_ISSUES.md)

---

## A. 환경변수

- [ ] `APP_ENV=production` (또는 staging)  
- [ ] `APP_VERSION=1.0.0`  
- [ ] `JWT_SECRET` 길이·entropy 충분  
- [ ] `ADMIN_API_KEY` 설정  
- [ ] `CORS_ALLOW_ORIGINS` = 실제 Admin Origin (localhost만 아님)  
- [ ] `LOG_LEVEL` 적절  
- [ ] DB_* 정확 · 비밀번호 강도  
- [ ] `KIWOOM_USE_MOCK=true` (Paper) · `KIWOOM_LIVE_ORDER_ENABLED=false`  
- [ ] Telegram 사용 시: token · allowlist · **`TELEGRAM_WEBHOOK_SECRET`**  
- [ ] Ollama 사용 시: `OLLAMA_BASE_URL` · 모델  

템플릿: `ops/env.production.example` · `.env.example`

---

## B. Database

- [ ] PostgreSQL 서비스 자동 시작  
- [ ] `alembic upgrade head` 완료 · `current` = head  
- [ ] 일간 backup 스크립트 검증 ([BACKUP.md](BACKUP.md))  
- [ ] Restore 리허설 1회 ([RECOVERY.md](RECOVERY.md))  

---

## C. Broker

- [ ] Mock/Paper 경로 주문 1건 성공  
- [ ] Live 플래그 OFF 확인  
- [ ] 키·계좌 번호 운영 문서와 일치  
- [ ] Outbox worker 기동 · PENDING 적체 없음  

---

## D. Telegram

- [ ] 알림 1건 수신  
- [ ] 허용 chat만 명령 가능  
- [ ] Webhook secret 설정 (fail-open 방지)  
- [ ] poller/webhook 하나만 사용  

---

## E. Ollama

- [ ] `GET` ollama status 또는 tags 응답  
- [ ] 타임아웃 시 주문 경로 영향 없음 확인  

---

## F. Health / Monitoring

- [ ] `/health/live` 200  
- [ ] `/health/ready` 200  
- [ ] `/version` → `version: 1.0.0`  
- [ ] Monitoring overview (Admin)  
- [ ] Alert 규칙 평가 (선택)  

---

## G. Backup / Restore

- [ ] `ops\backup_db.bat` 성공  
- [ ] 덤프 크기·경로 기록  
- [ ] Restore 스모크 (비운영 DB 권장)  

---

## H. Scheduler

- [ ] API **단일** 인스턴스  
- [ ] Jobs / Outbox / Exit Monitor 로그 OK  
- [ ] 중복 서버 기동 없음  

---

## I. Risk

- [ ] Kill Switch activate/deactivate 리허설  
- [ ] Daily Loss 한도 설정  
- [ ] Exit Monitor 동작( Paper )  
- [ ] Known Issues(Risk 우회 경로) 인지 서명  

---

## J. 네트워크 / 패키지

- [ ] 공개 포트 미노출 · VPN/방화벽  
- [ ] 무인증 mutate API를 ACL로 차단 (코드 미봉쇄분)  
- [ ] LICENSE / README / ops 스크립트 포함  
- [ ] Frontend build · Backend pytest 통과  

---

## 서명

| 역할 | 이름 | 일자 | 결과 |
|------|------|------|------|
| 운영 | | | PASS / FAIL |
| 개발 | | | PASS / FAIL |
| 승인 | | | **GO (Paper)** / **NO-GO** |

Live 전환은 본 체크리스트와 **별도** Live Trading Checklist + 재감사 후에만.
