# STEP26-4 워크포워드 검증

파라미터 조합을 전체 기간에 한 번만 최적화하지 않고,
학습 구간과 이후 검증 구간을 순차적으로 이동시키며 평가합니다.

## 처리 방식

```text
학습 12개월 → 검증 3개월
      ↓
3개월 이동
      ↓
학습 12개월 → 검증 3개월
      ↓
반복
```

각 학습 구간에서 다음 파라미터 조합을 실행합니다.

```text
short_windows
long_windows
stop_loss_ratios
take_profit_ratios
position_ratios
```

학습 점수가 가장 높은 조합을 바로 다음 검증 구간에 적용합니다.

## 학습 점수

```text
총 수익률
- 최대 낙폭
+ 승률 × 0.1
```

## 결과 항목

- 학습·검증 기간
- 구간별 선택 파라미터
- 학습 백테스트 실행 ID
- 검증 백테스트 실행 ID
- 학습 점수
- 검증 수익률
- 검증 최대낙폭
- 검증 승률
- 검증 거래 수
- 평균 검증 수익률
- 복리 검증 수익률
- 수익 구간 비율
- 파라미터 변경 횟수
- 실패 구간 및 오류

각 학습·검증 백테스트는 STEP26-2 테이블에 저장됩니다.

```text
backtest.backtest_run
backtest.backtest_trade
backtest.backtest_equity
```

## 적용 파일

```text
src/stock_platform/backtest/walk_forward_models.py
src/stock_platform/backtest/walk_forward_service.py
src/stock_platform/backtest/walk_forward_report.py
src/stock_platform/backtest/__init__.py
src/stock_platform/api/v1/walk_forward.py
src/stock_platform/api/router.py
tests/test_walk_forward_validation_service.py
```

신규 테이블은 없어 Alembic 작업은 필요 없습니다.

## API

```text
POST /api/v1/walk-forward
```

요청 예:

```json
{
  "exchange_code": "KRX",
  "symbol": "005930",
  "start_date": "2020-01-01",
  "end_date": "2026-06-30",
  "initial_capital": 10000000,
  "train_months": 12,
  "test_months": 3,
  "short_windows": [5, 10, 20],
  "long_windows": [20, 60, 120],
  "stop_loss_ratios": [0.03, 0.05],
  "take_profit_ratios": [0.08, 0.10],
  "position_ratios": [0.10, 0.20],
  "fee_ratio": 0.00015,
  "sell_tax_ratio": 0.0018,
  "slippage_ratio": 0.001
}
```

## 조합 제한

구간별 파라미터 조합 수는 최대 200개입니다.

먼저 아래처럼 작은 조합으로 테스트하세요.

```json
{
  "short_windows": [5, 10],
  "long_windows": [20, 60],
  "stop_loss_ratios": [0.03],
  "take_profit_ratios": [0.10],
  "position_ratios": [0.20]
}
```

## 해석 기준

전체기간 백테스트는 좋은데 워크포워드 검증 수익률이 낮다면
과최적화 가능성이 큽니다.

다음 항목을 함께 확인하세요.

- 수익 구간 비율
- 검증구간 평균 수익률
- 검증구간 최대낙폭
- 파라미터 변경 횟수
- 실패 구간 수
- 거래 횟수가 너무 적지 않은지

## 테스트

```powershell
cd D:\Projects\stock-platform
.\.venv\Scripts\Activate.ps1
$env:PYTHONPATH = "D:\Projects\stock-platform\src"

python -m pytest `
    tests\test_walk_forward_validation_service.py `
    -q
```

## Git 커밋

```powershell
git add `
    README_STEP26_4.md `
    src\stock_platform\backtest\walk_forward_models.py `
    src\stock_platform\backtest\walk_forward_service.py `
    src\stock_platform\backtest\walk_forward_report.py `
    src\stock_platform\backtest\__init__.py `
    src\stock_platform\api\v1\walk_forward.py `
    src\stock_platform\api\router.py `
    tests\test_walk_forward_validation_service.py

git commit -m "feat(backtest): add walk forward validation"
```

다음 단계는 STEP26-5 포트폴리오 다종목 백테스트입니다.
