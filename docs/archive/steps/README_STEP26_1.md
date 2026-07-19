# STEP26-1 통합 백테스트 엔진

저장된 일봉 데이터를 이용해 단일 종목 이동평균 전략을 백테스트합니다.

## 기본 전략

```text
진입:
단기 이동평균이 장기 이동평균을 상향 돌파

청산:
손절
익절
이동평균 하향 돌파
백테스트 종료일 강제 청산
```

## 반영 비용

- 매수·매도 수수료
- 매도세
- 슬리피지

## 계산 지표

- 초기 자본
- 최종 평가금액
- 총 수익률
- 총 손익
- 최대 낙폭
- 거래 횟수
- 승리·패배 횟수
- 승률
- 평균 거래 수익률
- 거래 상세 내역
- 일별 자산 곡선

## 적용 파일

```text
src/stock_platform/backtest/__init__.py
src/stock_platform/backtest/models.py
src/stock_platform/backtest/strategy.py
src/stock_platform/backtest/engine.py
src/stock_platform/backtest/service.py
src/stock_platform/api/v1/backtests.py
src/stock_platform/api/router.py
tests/test_backtest_engine.py
```

신규 테이블은 없으므로 Alembic 작업은 필요 없습니다.

## API

```text
POST /api/v1/backtests/moving-average
```

요청 예:

```json
{
  "exchange_code": "KRX",
  "symbol": "005930",
  "start_date": "2023-01-01",
  "end_date": "2026-07-14",
  "initial_capital": 10000000,
  "short_window": 5,
  "long_window": 20,
  "stop_loss_ratio": 0.05,
  "take_profit_ratio": 0.10,
  "position_ratio": 0.20,
  "fee_ratio": 0.00015,
  "sell_tax_ratio": 0.0018,
  "slippage_ratio": 0.001
}
```

업비트는 매도세가 없으므로 다음처럼 설정할 수 있습니다.

```json
{
  "exchange_code": "UPBIT",
  "symbol": "KRW-BTC",
  "start_date": "2023-01-01",
  "end_date": "2026-07-14",
  "initial_capital": 10000000,
  "short_window": 5,
  "long_window": 20,
  "stop_loss_ratio": 0.05,
  "take_profit_ratio": 0.10,
  "position_ratio": 0.20,
  "fee_ratio": 0.0005,
  "sell_tax_ratio": 0,
  "slippage_ratio": 0.001
}
```

## 테스트

```powershell
cd D:\Projects\stock-platform
.\.venv\Scripts\Activate.ps1
$env:PYTHONPATH = "D:\Projects\stock-platform\src"

python -m pytest `
    tests\test_backtest_engine.py `
    -q
```

## Git 커밋

```powershell
git add `
    README_STEP26_1.md `
    src\stock_platform\backtest `
    src\stock_platform\api\v1\backtests.py `
    src\stock_platform\api\router.py `
    tests\test_backtest_engine.py

git commit -m "feat(backtest): add moving average backtest engine"
```

다음 단계는 STEP26-2 백테스트 실행 결과 DB 저장과 전략 파라미터 비교입니다.
