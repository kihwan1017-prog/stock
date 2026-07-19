# 설치 가이드 — stock-platform v1.0

## 요구 사항

- Windows 10/11
- Python 3.12+
- PostgreSQL 17 (Windows 서비스)
- Ollama (로컬 AI)
- Git

> Docker는 사용하지 않습니다.

## 설치 순서

1. 저장소 클론
```powershell
git clone https://github.com/kihwan1017-prog/stock.git
cd stock
```

2. 가상환경
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

3. 환경변수
- `E:\StockTrading\secrets\stock-platform.env` 생성
- `.env.example` 값을 참고해 DB/키움/업비트/알림/ADMIN_API_KEY 설정

4. DB 마이그레이션
```powershell
$env:PYTHONPATH = "D:\Projects\stock-platform\src"
.\.venv\Scripts\python.exe -m alembic upgrade head
.\.venv\Scripts\python.exe -m alembic heads
```

5. 서버 기동
```powershell
$env:PYTHONPATH = "D:\Projects\stock-platform\src"
.\.venv\Scripts\uvicorn.exe stock_platform.api.main:app --host 0.0.0.0 --port 8000
```

6. 확인
- `GET http://127.0.0.1:8000/health`
- `GET http://127.0.0.1:8000/api/v1/system/dashboard`
