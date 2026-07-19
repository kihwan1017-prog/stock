# STEP21-4 후보선정 결과 저장

Top30 후보선정 실행과 결과를 PostgreSQL에 저장합니다.

## 신규 테이블

- strategy.candidate_run
- strategy.candidate_result

## Alembic 모델 등록

database/alembic/env.py에서 기존 모델 import 아래에 추가:

```python
from stock_platform.screener import persistence_models as screener_models  # noqa: F401
```

## 마이그레이션

```powershell
alembic revision --autogenerate -m "create candidate screening tables"
alembic upgrade head --sql
alembic upgrade head
```

생성 파일에는 strategy.candidate_run, strategy.candidate_result 생성만 있어야 합니다.
op.drop_table(...)이 있으면 적용하지 마세요.

## API

후보선정 실행 및 저장:

```text
POST /api/v1/candidate-runs
```

최신 결과 조회:

```text
GET /api/v1/candidate-runs/latest/KRX
```

## Git 커밋

```powershell
git add .
git commit -m "feat(screener): persist candidate screening results"
```
