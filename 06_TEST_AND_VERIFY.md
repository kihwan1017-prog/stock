# 테스트 및 검증

## STEP34 테스트

```powershell
cd D:\Projects\stock-platform
.\.venv\Scripts\Activate.ps1
$env:PYTHONPATH = "D:\Projects\stock-platform\src"
pytest -q tests\step34
```

## Import 확인

```powershell
python -c "from stock_platform.indicator.calculator import sma, ema, rsi; print('STEP34 import OK')"
```

## 계산 확인

```powershell
python -c "from stock_platform.indicator.calculator import sma; print(sma([1,2,3,4,5], 5))"
```

예상:

```text
3.0
```

## 서버 및 API 확인

```powershell
uvicorn stock_platform.api.main:app --reload --app-dir src
```

새 PowerShell 창:

```powershell
Invoke-RestMethod http://127.0.0.1:8000/api/v1/indicator/health
```

## 자주 발생하는 오류

### ModuleNotFoundError: stock_platform

```powershell
$env:PYTHONPATH = "D:\Projects\stock-platform\src"
```

### 404 Not Found

Router가 등록되지 않은 상태입니다. `main.py` 또는 `api/v1/router.py`를 확인하십시오.

### Alembic revision 오류

```powershell
alembic heads
alembic history
```

`down_revision`을 다시 확인하십시오.
