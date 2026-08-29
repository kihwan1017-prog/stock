# RELEASE_CHECKLIST.md — v1.0.0-RC1

운영(또는 스테이징) 배포 전 체크리스트입니다.  
모든 항목을 확인한 뒤에만 Live 주문을 허용하세요.

---

## A. 환경·보안

- [ ] `APP_ENV=production` (또는 `staging`)
- [ ] `JWT_SECRET` 설정 (자동 생성 금지)
- [ ] `ADMIN_API_KEY` 설정
- [ ] `CORS_ALLOW_ORIGINS` = 실제 Admin Origin (localhost 단독 금지)
- [ ] `LOG_LEVEL=INFO` 또는 `WARNING`
- [ ] secrets 파일은 Git 밖 (`E:\StockTrading\secrets\...` 등)
- [ ] `/docs`, `/redoc`, `/openapi.json` **404** (운영에서 숨김)
- [ ] 공개 `/api/v1/auth/signup` **403**
- [ ] Broker/Realtime mutate API는 Admin 인증 필요

## B. Database

- [ ] `python -m alembic -c alembic.ini current` = head (`d4e5f6a7b8c9` 이상)
- [ ] `python scripts/check_db_integrity.py` PASS
- [ ] `python scripts/verify_db_backup.py` PASS (도구·dump 스모크)
- [ ] 배포 전 schema-only 또는 full dump 백업 완료

## C. Broker

- [ ] mock이면 `KIWOOM_USE_MOCK=true`, live면 `false`
- [ ] Live 주문 시 `KIWOOM_LIVE_ORDER_ENABLED=true` + 실계좌 확인
- [ ] Live + Mock 동시 true **금지** (기동 검증)
- [ ] `GET /api/v1/broker/recovery/status` (Admin) 정상
- [ ] 필요 시 recovery `/run` 성공

## D. Telegram

- [ ] `TELEGRAM_ENABLED` / Bot Token / Chat ID
- [ ] Ops 사용 시 `TELEGRAM_OPS_ENABLED=true`
- [ ] `POST /api/v1/notification/test` (권한 있는 계정)
- [ ] `/status` `/help` 명령 응답

## E. AI / Ollama

- [ ] Ollama 프로세스 기동
- [ ] `GET /api/v1/ollama/status` → UP
- [ ] 설정 모델(`OLLAMA_MODEL`) pull 완료

## F. Runtime

- [ ] `GET /health` → UP (또는 degraded 원인 파악)
- [ ] `GET /version` 응답
- [ ] Scheduler 기동 로그 확인
- [ ] Position Exit Monitor enabled/interval 확인
- [ ] Kill Switch GET/activate/deactivate (Admin)
- [ ] Order Outbox worker 동작

## G. Frontend

- [ ] `npm run build` 성공
- [ ] Admin 로그인
- [ ] Operations Center / Telegram / Ollama 화면
- [ ] User 로그인·Paper 조회

## H. 최종

- [ ] `pytest` 통과
- [ ] `scripts/verify_release.ps1` (있는 경우) 통과
- [ ] KNOWN_ISSUES.md 숙지
- [ ] Live 주문은 **별도 승인** 후에만

---

## Backup & Restore (요약)

### Backup

```powershell
# 도구·schema dump 스모크
python scripts/verify_db_backup.py

# 전체 백업 예시 (운영 호스트)
pg_dump -h $env:DB_HOST -U $env:DB_USER -d $env:DB_NAME -Fc -f backup_$(Get-Date -Format yyyyMMdd_HHmm).dump
```

### Restore (주의: 데이터 덮어쓰기)

```powershell
# 목록 확인
pg_restore -l backup_YYYYMMDD_HHMM.dump

# 복원 (빈 DB 또는 전용 복구 인스턴스에서)
pg_restore -h $env:DB_HOST -U $env:DB_USER -d $env:DB_NAME --clean --if-exists backup_YYYYMMDD_HHMM.dump
python -m alembic -c alembic.ini upgrade head
```

상세: `docs/manual/백업복구매뉴얼.md`, `docs/manual/DB관리매뉴얼.md`
