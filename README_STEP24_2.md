# STEP24-2 모의 계좌·포지션·손익 관리

모의 주문 체결 결과를 계좌에 반영하고 현금, 평균매입가,
실현손익, 미실현손익을 계산합니다.

## 신규 테이블

```text
trading.paper_account
trading.paper_position
trading.paper_trade
```

## Alembic 모델 등록

`database/alembic/env.py`에 추가합니다.

```python
from stock_platform.trading import account_models as trading_account_models  # noqa: F401
```

STEP24-1 모델 import도 유지해야 합니다.

```python
from stock_platform.trading import models as trading_models  # noqa: F401
from stock_platform.trading import account_models as trading_account_models  # noqa: F401
```

## 마이그레이션

```powershell
alembic revision --autogenerate `
    -m "create paper account position and trade tables"

alembic upgrade head --sql
alembic upgrade head
```

생성 파일에는 아래 테이블 생성만 있어야 합니다.

```text
trading.paper_account
trading.paper_position
trading.paper_trade
```

`op.drop_table(...)`이 있으면 적용하지 마세요.

## API

계좌 생성:

```text
POST /api/v1/paper-accounts
```

체결 반영:

```text
POST /api/v1/paper-accounts/{account_id}/fills
```

보유 포지션:

```text
GET /api/v1/paper-accounts/{account_id}/positions
```

계좌 평가:

```text
POST /api/v1/paper-accounts/{account_id}/valuation
```

## 계좌 생성 예

```json
{
  "account_name": "기본 모의계좌",
  "initial_cash": 10000000,
  "currency_code": "KRW"
}
```

## 매수 체결 반영 예

```json
{
  "exchange_code": "KRX",
  "symbol": "005930",
  "side": "BUY",
  "quantity": 10,
  "fill_price": 70000,
  "order_id": 1
}
```

## 계좌 평가 요청 예

가격 키는 `거래소:종목코드` 형식입니다.

```json
{
  "prices": {
    "KRX:005930": 72000,
    "UPBIT:KRW-BTC": 150000000
  }
}
```

## 계산 항목

- 가용 현금
- 평균매입가
- 보유수량
- 포지션 평가금액
- 실현손익
- 미실현손익
- 미실현 수익률
- 총 계좌 평가금액
- 보유 중 최고가

## 테스트

```powershell
cd D:\Projects\stock-platform
.\.venv\Scripts\Activate.ps1
$env:PYTHONPATH = "D:\Projects\stock-platform\src"

python -m pytest `
    tests\test_paper_account_service.py `
    -q
```

## Git 커밋

```powershell
git add `
    README_STEP24_2.md `
    database\alembic\env.py `
    database\alembic\versions `
    src\stock_platform\trading\account_models.py `
    src\stock_platform\trading\account_repository.py `
    src\stock_platform\trading\account_service.py `
    src\stock_platform\api\v1\paper_accounts.py `
    src\stock_platform\api\router.py `
    tests\test_paper_account_service.py

git commit -m "feat(trading): add paper account positions and pnl"
```

다음 단계는 STEP24-3 모의 주문 체결과 계좌 반영을 자동 연결하는 단계입니다.
