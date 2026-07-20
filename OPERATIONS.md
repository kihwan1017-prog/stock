# OPERATIONS.md — Windows 운영 매뉴얼 (STEP60)

자동매매 **비즈니스 로직은 변경하지 않습니다.**  
이 문서는 기동·중지·업데이트·백업·장애 대응 절차만 다룹니다.

관련: [INSTALL.md](INSTALL.md) · [RUNBOOK.md](RUNBOOK.md) · [GO_LIVE_CHECKLIST.md](GO_LIVE_CHECKLIST.md) · [INCIDENT_RESPONSE.md](INCIDENT_RESPONSE.md) · [RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md) · [docs/manual/장애대응매뉴얼.md](docs/manual/장애대응매뉴얼.md)

**제품 버전:** v1.1.0 · 결정: GO (CONDITIONAL) ([FINAL_RELEASE_REPORT_v1.1.0.md](FINAL_RELEASE_REPORT_v1.1.0.md))

---

## 1. 일상 운영

| 작업 | 명령 |
|------|------|
| 시작 | `ops\start_server.bat` |
| 중지 | `ops\stop_server.bat` |
| 재시작 | `ops\restart_server.bat` |
| Health | `ops\health_check.bat` |
| 배포 점검 | `ops\deploy_check.bat` |
| DB 백업 | `ops\backup_db.bat` |
| DB 복구 | `ops\restore_db.bat <dump경로>` |
| 업데이트 | `ops\update_project.bat` |

NSSM 사용 시:

```powershell
nssm start StockPlatformAPI
nssm stop StockPlatformAPI
nssm restart StockPlatformAPI
nssm status StockPlatformAPI
```

---

## 2. 배포 전 확인

1. `APP_ENV=production` · secrets 파일 존재  
2. DB 연결 (`deploy_check.bat` 또는 `test_db_connection.py`)  
3. Broker mock/live 플래그 의도 확인  
4. Telegram / Ollama (사용 시)  
5. `GET /health`  
6. Scheduler / Kill Switch / Position Exit Monitor  
7. [RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md) 전체

---

## 3. 업데이트 절차

`ops\update_project.bat` 가 아래를 자동 수행합니다.

1. **Backup** — `pg_dump` + secrets 스냅샷  
2. **Stop** — API 중지  
3. **Update** — `git pull` + `pip install -r requirements.txt`  
4. **Migration** — `alembic upgrade head`  
5. **Start** — 서버 기동  
6. **Health Check**

수동 시에도 **반드시 Backup → Stop → Update → Migration → Start → Health** 순서를 지키세요.

프론트 업데이트:

```powershell
cd frontend
npm install
npm run build
# Next 프로세스 재시작
```

---

## 4. 장애 복구

### 4.1 API 무응답

1. `health_check.bat`  
2. `E:\StockTrading\logs\` 최신 out/err 또는 NSSM `service_*.log`  
3. `restart_server.bat` 또는 `nssm restart StockPlatformAPI`  
4. 지속 시 DB·포트 충돌·디스크 확인

### 4.2 DB 복구

1. `stop_server.bat`  
2. `restore_db.bat E:\StockTrading\backups\stock_YYYYMMDD_HHMMSS.dump` (`YES` 확인)  
3. `alembic current`  
4. `start_server.bat` → `health_check.bat`

### 4.3 환경변수 복구

1. `E:\StockTrading\secrets\stock-platform.env` 백업본 복원  
   (`backups\stock-platform.env.*.bak`)  
2. 서비스/프로세스 재시작  
3. 기동 실패 로그의 JWT/ADMIN/CORS/DB 메시지 확인

### 4.4 Broker 재연결

1. Admin: recovery status  
2. 필요 시 recovery run (Admin 인증)  
3. Live 플래그·모의 교차 설정 재확인  
4. WS 연속 실패 시 mock/네트워크/키 점검

### 4.5 Scheduler

- API lifecycle 내 스케줄러는 프로세스 재시작으로 복구  
- 별도 `scripts\run_scheduler.py` / Task Scheduler 사용 시 해당 작업 재시작  
- Admin scheduler 화면·잡 이력 확인

### 4.6 Ollama

1. Ollama Windows 앱/서비스 상태  
2. `ollama list` / `GET /api/v1/ollama/status`  
3. 모델 재 pull  
4. API는 Ollama 없이도 degrade 기동 가능(기능만 제한)

### 4.7 Kill Switch / 긴급 중단

1. Admin Kill Switch activate  
2. 필요 시 Live 주문 플래그 off 후 재기동  
3. `stop_server.bat`

---

## 5. 로그 관리

| 종류 | 위치 | 비고 |
|------|------|------|
| Application (uvicorn) | `E:\StockTrading\logs\uvicorn_*.log` | bat 기동 시 |
| Service | `E:\StockTrading\logs\service_stdout.log` / `_stderr.log` | NSSM |
| Audit / Order / AI | 앱 구조화 로그(stdout JSON) + DB 이력 | 시크릿 마스킹 유지 |
| Scheduler | 동일 앱 로그 · job_run_history | |

**정책 (권장)**

| 항목 | 값 |
|------|----|
| Rotation | NSSM 10MB 로테이션 / bat 로그는 일자·시각 파일 |
| Retention (앱 로그) | 14~30일 |
| Retention (감사·주문 관련) | 90일 이상 권장 |
| 금지 | JWT·API Key·비밀번호 평문 로그 |

정리 예:

```powershell
Get-ChildItem E:\StockTrading\logs -Filter *.log |
  Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-30) } |
  Remove-Item -Force
```

---

## 6. 백업 정책

| 대상 | 주기 | 보관 | 방법 |
|------|------|------|------|
| DB full dump | **일간** | 14일 | `ops\backup_db.bat` |
| DB full dump | **주간** | 8주 | 주 1회 별도 폴더 복사 |
| DB full dump | **월간** | 12개월 | 월말 아카이브 |
| secrets `.env` | 백업 시 동봉 | DB와 동일 | ACL 제한 |
| 전략·설정(DB) | DB 덤프에 포함 | — | — |
| 코드 | git remote | — | `git push` |
| 로그 | 선택 주간 | 4주 | zip |

배포·마이그레이션·Live 전환 **직전**에는 추가 백업 필수.

검증: `python scripts\verify_db_backup.py`

---

## 7. Windows Service (NSSM)

문서화된 절차는 [ops/NSSM_SERVICE.md](ops/NSSM_SERVICE.md) 참고.

요약:

- 자동 시작: `SERVICE_AUTO_START`  
- 비정상 종료: `AppExit Default Restart` + `AppRestartDelay 5000`  
- 로그 로테이션: `AppRotateFiles` / `AppRotateBytes`

---

## 8. 운영 체크리스트 (짧게)

- [ ] Broker 연결  
- [ ] DB  
- [ ] Telegram  
- [ ] AI (Ollama)  
- [ ] Scheduler  
- [ ] Risk Engine / Kill Switch  
- [ ] Position Monitor  
- [ ] Notification  
- [ ] Backup 최신본 존재
