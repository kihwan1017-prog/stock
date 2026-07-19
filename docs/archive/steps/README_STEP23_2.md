# STEP23-2 위험관리 정책·포지션 계획 저장

STEP23-1의 계산 엔진 위에 위험관리 정책과 생성된 포지션 계획을
PostgreSQL에 저장합니다.

## 신규 테이블

```text
strategy.risk_policy
strategy.position_plan
```

## Alembic 모델 등록

`database/alembic/env.py`에 추가합니다.

```python
from stock_platform.risk import persistence_models as risk_models  # noqa: F401
```

## 마이그레이션

```powershell
alembic revision --autogenerate `
    -m "create risk policy and position plan tables"

alembic upgrade head --sql
alembic upgrade head
```

생성 파일에는 다음 두 테이블 생성만 있어야 합니다.

```text
strategy.risk_policy
strategy.position_plan
```

`op.drop_table(...)`이 있으면 적용하지 마세요.

## API

정책 생성:

```text
POST /api/v1/risk-policies
```

활성 정책 목록:

```text
GET /api/v1/risk-policies
```

포지션 계획 생성 및 저장:

```text
POST /api/v1/risk-policies/position-plans
```

## 정책 생성 요청 예

```json
{
  "policy_name": "기본 위험관리 정책",
  "position_sizing_mode": "RISK_BASED",
  "risk_per_trade_ratio": 0.01,
  "stop_loss_ratio": 0.05,
  "take_profit_ratio": 0.10,
  "trailing_stop_ratio": 0.03,
  "maximum_position_ratio": 0.20,
  "maximum_positions": 5,
  "minimum_order_amount": 10000
}
```

## 테스트

```powershell
$env:PYTHONPATH = "D:\Projects\stock-platform\src"

python -m pytest `
    tests\test_risk_service.py `
    -q
```

## Git 커밋

```powershell
git add `
    README_STEP23_2.md `
    database\alembic\env.py `
    database\alembic\versions `
    src\stock_platform\risk `
    src\stock_platform\api\v1\risk_policies.py `
    src\stock_platform\api\router.py `
    tests\test_risk_service.py

git commit -m "feat(risk): persist policies and position plans"
```

다음 단계는 STEP23-3 AI Top5와 위험관리 정책을 연결해
주문 후보 계획을 일괄 생성하는 단계입니다.
