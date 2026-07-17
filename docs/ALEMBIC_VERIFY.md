# Alembic 검증 (Windows / Docker 미사용)

```powershell
cd D:\Projects\stock-platform
.\.venv\Scripts\Activate.ps1
$env:PYTHONPATH = "D:\Projects\stock-platform\src"

# 1) head는 반드시 하나
python -m alembic heads

# 2) 현재 DB revision
python -m alembic current

# 3) history
python -m alembic history

# 4) (선택) 테스트 DB에서 upgrade/downgrade
# stock_platform_test DB를 준비한 뒤 DATABASE URL을 테스트 DB로 바꿔 실행
# python -m alembic upgrade head
# python -m alembic downgrade -1
# python -m alembic upgrade head
```

표준 경로: `database/alembic/` (`alembic.ini` script_location)
Overlay 참고용: `docs/migration-overlays/` (적용 금지)
