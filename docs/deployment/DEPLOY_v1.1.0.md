# DEPLOY_v1.1.0 — Production 배포 가이드

Windows 11 · 비Docker · NSSM 전제.  
**운영 DB Migration은 수동. Secret 값은 본 문서에 기록하지 않음.**

---

## 0. Freeze 확인

- [ ] `release/v1.1.0` 또는 tag `v1.1.0`
- [ ] `APP_VERSION=1.1.0` / `GET /version` = 1.1.0
- [ ] 신규 기능 커밋 없음 (버그픽스만)
- [ ] Alembic head = `g3b4c5d6e7f8`

---

## 1. 배포 전 Backup

1. DB: [BACKUP.md](../../BACKUP.md) 절차로 dump
2. Env: `secrets\stock-platform.env` 복사 (권한 제한 경로)
3. Logs: 최근 로그 아카이브
4. (선택) AI prompt/설정 export

---

## 2. Code

```bat
git fetch
git checkout v1.1.0
REM 또는 release/v1.1.0
.\.venv\Scripts\pip.exe install -r requirements.txt
cd frontend && npm ci && npm run build && cd ..
```

---

## 3. Migration (수동)

```bat
.\.venv\Scripts\python.exe -m alembic heads
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m alembic current
```

실패 시 **즉시 중단** → [ROLLBACK_v1.1.0.md](ROLLBACK_v1.1.0.md)

---

## 4. Restart

```bat
ops\stop_server.bat
ops\start_server.bat
REM 또는 NSSM restart
```

확인: PostgreSQL Service · Ollama · API 포트

---

## 5. Health / Smoke

```text
GET /health/live
GET /health/ready
GET /version          → version=1.1.0
```

수동 Smoke:

1. 로그인
2. `/user/portfolio` · `/user/watchlist` · `/user/news` · `/user/disclosures`
3. `/user/ai` · `/user/notifications` · `/user/settings` · `/user/profile`
4. 로그아웃

---

## 6. Post-check

- [ ] Scheduler job 등록
- [ ] 알림 Inbox 적재 (Telegram 실발송은 조건부)
- [ ] Live 주문 OFF 유지
- [ ] 로그에 Secret 없음
