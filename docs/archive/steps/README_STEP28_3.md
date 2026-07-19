# STEP28-3 키움 계좌·보유종목 동기화

키움 REST 계좌 API를 조회해 PostgreSQL에 최신 계좌 및 보유종목
스냅샷을 저장합니다.

## 키움 공식 TR

```text
계좌번호조회          ka00001
예수금상세현황요청    kt00001
계좌평가잔고내역요청  kt00018
URL                   /api/dostk/acnt
```

## 신규 테이블

```text
trading.broker_account_snapshot
trading.broker_position_snapshot
```

## Alembic 모델 등록

`database/alembic/env.py`에 추가합니다.

```python
from stock_platform.broker import account_models as broker_account_models  # noqa: F401
```

## 마이그레이션

```powershell
alembic revision --autogenerate `
    -m "create broker account snapshot tables"

alembic upgrade head --sql
alembic upgrade head
```

생성된 마이그레이션에는 위 두 테이블 생성만 있어야 합니다.
예상하지 않은 `drop_table`이 있으면 적용하지 마세요.

## 안전 설정

```dotenv
KIWOOM_USE_MOCK=true
KIWOOM_LIVE_ORDER_ENABLED=false
```

계좌 조회는 모의투자 환경에서 먼저 확인하세요.

## API

동기화:

```text
POST /api/v1/broker/kiwoom/account/sync
```

저장된 결과 조회:

```text
GET /api/v1/broker/kiwoom/account/{account_number}
```

## router.py 추가

```python
from stock_platform.api.v1.kiwoom_account_sync import (
    router as kiwoom_account_sync_router,
)
```

```python
api_router.include_router(
    kiwoom_account_sync_router
)
```

## 주의

키움 TR 응답은 축약 필드명을 사용합니다. Mapper는 여러 별칭을
허용하고 원본 응답을 `raw_data`에 보관합니다.

실제 모의투자 응답에서 필드명이 다르면
`kiwoom/account_mapper.py`의 별칭만 조정하세요.

## 테스트

```powershell
$env:PYTHONPATH = "D:\Projects\stock-platform\src"

python -m pytest `
    tests\test_kiwoom_account_mapper.py `
    -q
```

## Git 커밋

```powershell
git add `
    README_STEP28_3.md `
    database\alembic\env.py `
    database\alembic\versions `
    src\stock_platform\broker\account_dto.py `
    src\stock_platform\broker\account_models.py `
    src\stock_platform\broker\account_repository.py `
    src\stock_platform\broker\kiwoom\account_client.py `
    src\stock_platform\broker\kiwoom\account_mapper.py `
    src\stock_platform\broker\kiwoom\account_sync_service.py `
    src\stock_platform\broker\kiwoom\account_factory.py `
    src\stock_platform\api\v1\kiwoom_account_sync.py `
    src\stock_platform\api\router.py `
    tests\test_kiwoom_account_mapper.py

git commit -m "feat(broker): synchronize Kiwoom account snapshots"
```

다음 단계는 STEP28-4 키움 미체결 주문 조회·정정·취소입니다.
