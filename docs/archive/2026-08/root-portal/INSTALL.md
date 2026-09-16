# INSTALL.md — Windows 운영 서버 설치 (v1.0.0)

Docker는 사용하지 않습니다. Windows 10/11 + 로컬 프로세스 기준입니다.  
Go-Live: [GO_LIVE_CHECKLIST.md](GO_LIVE_CHECKLIST.md) · 운영: [RUNBOOK.md](RUNBOOK.md)

상세 한글 매뉴얼: [docs/manual/설치매뉴얼.md](docs/manual/설치매뉴얼.md)  
설정 상세: [docs/deployment/CONFIGURATION.md](docs/deployment/CONFIGURATION.md)

---

## 1. 요구 사항

| 구성 | 버전/비고 |
|------|-----------|
| OS | Windows 10/11 |
| Python | 3.12+ |
| PostgreSQL | 16/17 (Windows Service) |
| Ollama | 로컬 AI (선택이나 AI 기능 시 필수) |
| Git | 업데이트용 |
| NSSM | 서비스 등록 시 (선택) |
| PostgreSQL client | `pg_dump` / `pg_restore` PATH |

---

## 2. 권장 디렉터리 구조

```
D:\Projects\stock-platform\     # 코드 (git) — 업데이트 대상
  .venv\
  src\
  ops\                          # 운영 스크립트
  frontend\

E:\StockTrading\                # 운영 데이터 (업데이트 시 유지)
  secrets\stock-platform.env    # 비밀 설정
  backups\                      # DB 덤프
  logs\                         # 앱/서비스 로그
  config\                       # 추가 운영 설정 사본
  data\                         # 임시·캐시성 데이터
  temp\
```

**업데이트 시 유지:** `E:\StockTrading\**`, `.venv` 는 재생성 가능하나 보통 유지, Ollama 모델(`%USERPROFILE%\.ollama` 등)

**교체 가능:** 소스 트리 (`git pull`), `frontend/.next` 빌드 산출물

---

## 3. 설치 순서

### 3.1 PostgreSQL

1. PostgreSQL 설치 → Windows 서비스 자동 시작 확인  
2. DB/유저 생성 (`stock_platform` / `stock_app`)  
3. `bin` 폴더를 PATH에 추가 (`pg_dump` 확인)

### 3.2 Python / 프로젝트

```powershell
cd D:\Projects\stock-platform
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 3.3 환경변수

```powershell
# 템플릿 복사
New-Item -ItemType Directory -Force E:\StockTrading\secrets | Out-Null
Copy-Item .\ops\env.production.example E:\StockTrading\secrets\stock-platform.env

# 메모장/편집기로 값 수정 (JWT_SECRET, DB_PASSWORD, ADMIN_API_KEY, CORS 등)
notepad E:\StockTrading\secrets\stock-platform.env
```

앱은 `E:\StockTrading\secrets\stock-platform.env` 를 기본으로 로드합니다  
(`src/stock_platform/common/settings.py`).

운영 체크:

- `APP_ENV=production`
- `JWT_DEV_AUTO_SECRET=false`
- `CORS_ALLOW_ORIGINS` = 실제 Admin Origin
- Live 주문 전에는 `KIWOOM_LIVE_ORDER_ENABLED=false`

### 3.4 DB 마이그레이션

```powershell
$env:PYTHONPATH = "D:\Projects\stock-platform\src"
cd D:\Projects\stock-platform
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m alembic current
```

### 3.5 Ollama (선택)

1. Ollama 설치·기동  
2. `ollama pull <OLLAMA_MODEL>`  
3. `OLLAMA_BASE_URL` 확인

### 3.6 초기 기동

```powershell
cd D:\Projects\stock-platform\ops
.\start_server.bat
.\health_check.bat
.\deploy_check.bat
```

또는 NSSM 서비스:

```powershell
# 관리자 PowerShell
cd D:\Projects\stock-platform
.\ops\install_nssm_service.ps1
```

### 3.7 Frontend (Admin/User Web)

```powershell
cd D:\Projects\stock-platform\frontend
copy .env.example .env.local
# NEXT_PUBLIC_API_BASE_URL 수정
npm install
npm run build
npm run start
```

---

## 4. 설치 후 확인

| 항목 | 방법 |
|------|------|
| Health | `ops\health_check.bat` 또는 `GET /health` |
| DB | `scripts\test_db_connection.py` |
| Docs 숨김 | 운영에서 `/docs` → 404 |
| Signup | 운영에서 `/api/v1/auth/signup` → 403 |
| 체크리스트 | [RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md) |

---

## 5. 다음 문서

- [OPERATIONS.md](OPERATIONS.md) — 시작/중지/업데이트/장애  
- [README_STEP60.md](README_STEP60.md) — STEP60 요약  
- [KNOWN_ISSUES.md](KNOWN_ISSUES.md) — 잔여 제약
