# README_STEP32_9_TO_15

STEP32-8 이후 프로젝트에 병합하는 통합 확장 패키지입니다.

## 포함 기능
- STEP32-9 Position Engine
- STEP32-10 Portfolio Engine
- STEP32-11 Risk Engine
- STEP32-12 Market Scheduler
- STEP32-13 Strategy Engine
- STEP32-14 Ollama/Qwen AI Ranking
- STEP32-15 Dashboard API / Notification

> 이 ZIP은 기존 STEP32-1~32-8 전체 원본이 아니라 추가 적용용 overlay입니다.
> 적용 전 `D:\Projects\stock-platform`을 Git 커밋하거나 백업하십시오.

## 적용
```powershell
cd D:\Projects\stock-platform
pip install -r requirements_step32_9_to_15.txt
$env:PYTHONPATH = "D:\Projects\stock-platform\src"
pytest -q tests\step32
```

기존 FastAPI 애플리케이션에 다음 라우터를 등록합니다.
```python
from stock_platform.api.v1.step32_router import router as step32_router
app.include_router(step32_router)
```

Alembic migration의 `down_revision`은 현재 STEP32-8 migration revision 값으로 교체하십시오.
