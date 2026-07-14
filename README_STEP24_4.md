# STEP24-4 일봉 종가 기반 자동 체결 시뮬레이터

저장된 일봉 종가를 사용해 미체결 모의 주문을 자동으로 체결하고
모의 계좌와 포지션에 반영합니다.

## 지원 방식

```text
MARKET
LIMIT BUY
LIMIT SELL
```

## 체결 기준

### 시장가

지정 일자의 종가로 체결합니다.

### 지정가 매수

```text
종가 <= 지정가
```

일 때 체결합니다.

### 지정가 매도

```text
종가 >= 지정가
```

일 때 체결합니다.

## 추가 옵션

- 슬리피지 비율
- 부분 체결 비율
- 단일 주문 시뮬레이션
- 해당 종목의 미체결 주문 일괄 시뮬레이션

## 적용 파일

```text
src/stock_platform/trading/simulation_models.py
src/stock_platform/trading/simulation_service.py
src/stock_platform/trading/__init__.py
src/stock_platform/api/v1/paper_simulation.py
src/stock_platform/api/router.py
tests/test_daily_close_fill_simulator.py
```

신규 테이블은 없으므로 Alembic 작업은 필요 없습니다.

## API

단일 주문:

```text
POST /api/v1/paper-simulation/orders/{order_id}/daily-close
```

미체결 주문 일괄:

```text
POST /api/v1/paper-simulation/open-orders/daily-close
```

## 요청 예

```json
{
  "account_id": 1,
  "exchange_code": "KRX",
  "symbol": "005930",
  "trade_date": "2026-07-13",
  "slippage_ratio": 0.001,
  "fill_ratio": 1
}
```

`slippage_ratio=0.001`이면:

- 매수: 종가보다 0.1% 높은 가격
- 매도: 종가보다 0.1% 낮은 가격

으로 체결합니다.

`fill_ratio=0.5`이면 남은 수량의 50%만 부분 체결합니다.

## 테스트

```powershell
cd D:\Projects\stock-platform
.\.venv\Scripts\Activate.ps1
$env:PYTHONPATH = "D:\Projects\stock-platform\src"

python -m pytest `
    tests\test_daily_close_fill_simulator.py `
    -q
```

## Git 커밋

```powershell
git add `
    README_STEP24_4.md `
    src\stock_platform\trading\simulation_models.py `
    src\stock_platform\trading\simulation_service.py `
    src\stock_platform\trading\__init__.py `
    src\stock_platform\api\v1\paper_simulation.py `
    src\stock_platform\api\router.py `
    tests\test_daily_close_fill_simulator.py

git commit -m "feat(trading): add daily close fill simulator"
```

다음 단계는 STEP25 스케줄러와 운영 작업 이력 관리입니다.
