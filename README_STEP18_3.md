# STEP 18-3 - Kiwoom Daily Sync 검증

이 패키지는 STEP17, STEP18-1B, STEP18-2가 정상 적용되었는지
실제 환경에서 검증하는 스크립트를 제공합니다.

## 포함 파일

```text
scripts/check_step18_files.ps1
scripts/verify_kiwoom_daily_sync.py
README_STEP18_3.md
```

기존 소스 파일은 덮어쓰지 않습니다.

## 1. 압축 해제

다음 프로젝트 루트에 압축을 풉니다.

```text
D:\Projects\stock-platform
```

## 2. 필수 파일 확인

```powershell
cd D:\Projects\stock-platform
.\.venv\Scripts\Activate.ps1

powershell -ExecutionPolicy Bypass `
    -File scripts\check_step18_files.ps1
```

## 3. 키움 설정

다음 외부 비밀파일에 실제 키가 있어야 합니다.

```text
E:\StockTrading\secrets\stock-platform.env
```

```dotenv
KIWOOM_APP_KEY=발급받은_앱키
KIWOOM_SECRET_KEY=발급받은_시크릿키
KIWOOM_USE_MOCK=true
```

## 4. 종목 등록

삼성전자가 없다면 한 번 실행합니다.

```powershell
psql -U stock_app -h localhost -p 5432 -d stock_platform `
    -c "INSERT INTO market.instrument (asset_type, exchange_code, symbol, name) VALUES ('STOCK', 'KRX', '005930', '삼성전자') ON CONFLICT (exchange_code, symbol) DO NOTHING;"
```

## 5. 저장하지 않고 수집 검증

최근 5일 범위를 요청하되 DB에는 저장하지 않습니다.

```powershell
python scripts\verify_kiwoom_daily_sync.py `
    --symbol 005930 `
    --exchange KRX `
    --days 5
```

이 명령은 다음을 확인합니다.

- 키움 환경설정
- `market.instrument`, `market.price_daily`
- 키움 접근토큰 발급
- `ka10081` 일봉 호출
- 일봉 Parser

토큰 값은 화면에 출력하지 않습니다.

## 6. 실제 DB 저장

수집 결과를 `market.price_daily`에 UPSERT합니다.

```powershell
python scripts\verify_kiwoom_daily_sync.py `
    --symbol 005930 `
    --exchange KRX `
    --days 30 `
    --apply
```

## 7. 결과 확인

```powershell
psql -U stock_app -h localhost -p 5432 -d stock_platform `
    -c "SELECT trade_date, open_price, high_price, low_price, close_price, volume, source FROM market.price_daily ORDER BY trade_date DESC LIMIT 20;"
```

## 8. 전체 단위 테스트

```powershell
$env:PYTHONPATH = "D:\Projects\stock-platform\src"

python -m pytest `
    tests\test_kiwoom_auth.py `
    tests\test_kiwoom_client.py `
    tests\test_kiwoom_daily_parser.py `
    tests\test_kiwoom_daily_collector.py `
    tests\test_kiwoom_daily_sync_service.py `
    -q
```

## 9. Git 커밋

```powershell
git add `
    README_STEP18_3.md `
    scripts\check_step18_files.ps1 `
    scripts\verify_kiwoom_daily_sync.py

git commit -m "test(kiwoom): add daily sync verification scripts"
```

STEP18 검증이 성공하면 다음 단계는 STEP19 업비트 일봉 수집기입니다.
