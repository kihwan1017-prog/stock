# README_STEP60 — Production Deployment (Windows)

## 목적

Release Candidate(STEP59) 이후, **Windows 운영 배포·업데이트·복구** 절차를 구축합니다.

- Docker **제외**
- 자동매매 비즈니스 로직 **미변경**
- 운영 편의·안정성 중심

---

## 운영 환경 요약

| 구성 | 역할 |
|------|------|
| Python 3.12 + FastAPI/uvicorn | API · lifecycle · scheduler 일부 |
| PostgreSQL | 영속 데이터 |
| Ollama | 로컬 AI |
| Telegram | 알림/Ops |
| Broker (키움) | 시세·주문 (mock/live) |
| Windows Service (NSSM) | 자동 시작·재시작 |
| Batch (`ops\*.bat`) | 수동 운영 |
| 로그 | `E:\StockTrading\logs` (+ stdout JSON) |
| 환경설정 | `E:\StockTrading\secrets\stock-platform.env` |

---

## 배포 구조

```
코드 (git, 업데이트됨)
  D:\Projects\stock-platform\
    .venv\          # 의존성 (보통 유지)
    src\            # 앱
    ops\            # 운영 스크립트
    frontend\

운영 데이터 (업데이트 시 유지)
  E:\StockTrading\
    secrets\        # env
    backups\        # DB dump
    logs\
    config\
    data\
    temp\

AI 모델
  Ollama 기본 경로 (사용자 프로필) — 코드와 분리
```

---

## 스크립트 (`ops/`)

| 파일 | 역할 |
|------|------|
| `start_server.bat` | API 기동 + PID |
| `stop_server.bat` | 중지 |
| `restart_server.bat` | 재시작 |
| `health_check.bat` | `/health` |
| `backup_db.bat` | `pg_dump` + secrets 스냅샷 |
| `restore_db.bat` | `pg_restore` (YES 확인) |
| `update_project.bat` | Backup→Stop→Pull→Migrate→Start→Health |
| `deploy_check.bat` | DB·alembic·health 점검 |
| `install_nssm_service.ps1` | 서비스 등록 |
| `uninstall_nssm_service.ps1` | 서비스 제거 |
| `env.production.example` | 운영 env 템플릿 |

---

## 문서

| 문서 | 내용 |
|------|------|
| [INSTALL.md](INSTALL.md) | 설치 |
| [OPERATIONS.md](OPERATIONS.md) | 운영·장애·로그·백업 정책 |
| [ops/NSSM_SERVICE.md](ops/NSSM_SERVICE.md) | 서비스 등록 |
| [RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md) | 배포 체크 |
| [KNOWN_ISSUES.md](KNOWN_ISSUES.md) | 잔여 이슈 |

---

## 백업 · 복구

- **백업:** `ops\backup_db.bat` → `E:\StockTrading\backups\stock_*.dump`  
- **복구:** 서버 중지 → `ops\restore_db.bat <dump>` → 기동·health  
- **정책:** 일간 14일 / 주간 8주 / 월간 12개월 (OPERATIONS.md)

---

## 검증 (2026-07-20)

| 검사 | 결과 |
|------|------|
| `pytest` | **340 passed**, 3 skipped |
| frontend lint / typecheck / test / build | PASS (lint warning 2) |
| `ops\_common.bat` 경로 | PROJECT_ROOT / STOCK_OPS_ROOT 정상 |

```powershell
.\.venv\Scripts\python.exe -m pytest -q
cd frontend
npm run lint; npm run typecheck; npm run test; npm run build
cd ..\ops
cmd /c "call _common.bat & set PROJECT_ROOT"
.\health_check.bat   # after server start
```

---

## 제약

- 공개망 직접 노출 비권장 (VPN/사설망)
- Live 주문은 체크리스트·별도 승인 후
- Docker/compose 없음 (의도적)
