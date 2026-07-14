# STEP23-1 위험관리 엔진

주문 전 포지션 크기와 손절·익절·트레일링 스톱 조건을 계산합니다.

## 포지션 크기 방식

```text
FIXED_AMOUNT
FIXED_RATIO
RISK_BASED
```

### FIXED_AMOUNT

고정 금액으로 주문합니다.

### FIXED_RATIO

총 평가금액의 지정 비율로 주문합니다.

### RISK_BASED

1회 최대 손실 허용액을 기준으로 주문금액을 계산합니다.

```text
주문금액
=
총 평가금액 × 1회 위험비율 ÷ 손절비율
```

계산된 주문금액에는 다음 제한이 적용됩니다.

- 보유 현금
- 종목당 최대 투자비율
- 최대 보유 종목 수
- 최소 주문금액

## 청산 조건

- 고정 손절
- 고정 익절
- 트레일링 스톱
- 조건 미충족 시 HOLD

## 적용 파일

```text
src/stock_platform/risk/__init__.py
src/stock_platform/risk/models.py
src/stock_platform/risk/engine.py
src/stock_platform/api/v1/risk.py
src/stock_platform/api/router.py
tests/test_risk_management_engine.py
```

이번 단계에는 신규 테이블이 없으므로 Alembic 작업은 필요 없습니다.

## 테스트

```powershell
cd D:\Projects\stock-platform
.\.venv\Scripts\Activate.ps1
$env:PYTHONPATH = "D:\Projects\stock-platform\src"

python -m pytest `
    tests\test_risk_management_engine.py `
    -q
```

## API

포지션 계획:

```text
POST /api/v1/risk/position-plan
```

요청 예:

```json
{
  "portfolio_value": 10000000,
  "available_cash": 5000000,
  "current_price": 100000,
  "current_position_count": 1,
  "policy": {
    "position_sizing_mode": "RISK_BASED",
    "risk_per_trade_ratio": 0.01,
    "stop_loss_ratio": 0.05,
    "take_profit_ratio": 0.10,
    "trailing_stop_ratio": 0.03,
    "maximum_position_ratio": 0.20,
    "maximum_positions": 5,
    "minimum_order_amount": 10000
  }
}
```

청산 판단:

```text
POST /api/v1/risk/exit-decision
```

## 주의

이 엔진은 계산 결과만 반환하며 실제 주문을 전송하지 않습니다.
실거래 연결 전 모의투자와 백테스트 검증이 필요합니다.

## Git 커밋

```powershell
git add `
    README_STEP23_1.md `
    src\stock_platform\risk `
    src\stock_platform\api\v1\risk.py `
    src\stock_platform\api\router.py `
    tests\test_risk_management_engine.py

git commit -m "feat(risk): add position sizing and exit engine"
```

다음 단계는 STEP23-2 위험관리 정책과 포지션 계획 DB 저장입니다.
