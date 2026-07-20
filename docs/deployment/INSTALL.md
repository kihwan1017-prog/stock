# 설치 가이드 — stock-platform v1.0

> **STEP60 정식 문서:** 저장소 루트 [INSTALL.md](../../INSTALL.md)  
> 운영: [OPERATIONS.md](../../OPERATIONS.md) · 스크립트: `ops\`

## 요구 사항

- Windows 10/11
- Python 3.12+
- PostgreSQL 16/17 (Windows 서비스)
- Ollama (로컬 AI)
- Git
- (선택) NSSM — Windows Service

> Docker는 사용하지 않습니다.

## 설치 순서 (요약)

1. 저장소 클론 후 `python -m venv .venv` → `pip install -r requirements.txt`
2. `ops\env.production.example` → `E:\StockTrading\secrets\stock-platform.env`
3. `alembic upgrade head`
4. `ops\start_server.bat` 또는 `ops\install_nssm_service.ps1`
5. `ops\health_check.bat` / `ops\deploy_check.bat`

수동 uvicorn (참고):

```powershell
$env:PYTHONPATH = "D:\Projects\stock-platform\src"
.\.venv\Scripts\uvicorn.exe stock_platform.api.main:app --host 127.0.0.1 --port 8000 --app-dir src
```
