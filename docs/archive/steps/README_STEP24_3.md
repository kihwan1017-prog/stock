# STEP24-3 모의 주문 체결과 계좌 반영 자동 연결

STEP24-1 모의 주문과 STEP24-2 모의 계좌를 연결합니다.

하나의 API 호출로 다음 작업을 처리합니다.

```text
모의 주문 체결
    ↓
주문 상태 변경
    ↓
모의 계좌 현금 반영
    ↓
포지션 수량·평균매입가 반영
    ↓
paper_trade 원장 생성
```

## 적용 파일

```text
src/stock_platform/trading/execution_service.py
src/stock_platform/trading/__init__.py
src/stock_platform/api/v1/paper_executions.py
src/stock_platform/api/router.py
tests/test_paper_execution_service.py
```

신규 테이블은 없으므로 Alembic 작업은 필요 없습니다.

## API

```text
POST /api/v1/paper-executions/fills
```

요청 예:

```json
{
  "account_id": 1,
  "order_id": 1,
  "fill_quantity": 10,
  "fill_price": 70000
}
```

응답에는 다음이 포함됩니다.

- 주문 상태
- 누적 체결수량
- 평균 체결가
- 계좌 가용현금
- 계좌 실현손익
- 체결금액
- 체결 실현손익

## 주의

현재 STEP24-1과 STEP24-2의 Repository가 각각 commit을 수행합니다.
따라서 DB 수준의 완전한 단일 트랜잭션으로 만들려면 다음 단계에서
Repository commit 정책을 Unit of Work 방식으로 개선하는 것이 좋습니다.

이번 단계는 기능 연결과 API 검증을 우선 제공합니다.

## 테스트

```powershell
cd D:\Projects\stock-platform
.\.venv\Scripts\Activate.ps1
$env:PYTHONPATH = "D:\Projects\stock-platform\src"

python -m pytest `
    tests\test_paper_execution_service.py `
    -q
```

## Git 커밋

```powershell
git add `
    README_STEP24_3.md `
    src\stock_platform\trading\execution_service.py `
    src\stock_platform\trading\__init__.py `
    src\stock_platform\api\v1\paper_executions.py `
    src\stock_platform\api\router.py `
    tests\test_paper_execution_service.py

git commit -m "feat(trading): connect paper fills to accounts"
```

다음 단계는 STEP24-4 자동 체결 시뮬레이터와 일봉 종가 기반 주문 실행입니다.
