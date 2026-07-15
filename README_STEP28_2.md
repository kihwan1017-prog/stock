# STEP28-2 키움 REST 주문 어댑터

키움 OAuth 토큰 발급과 국내주식 매수·매도 주문 Adapter를 추가합니다.

## 공식 명세에서 확인한 값

```text
운영: https://api.kiwoom.com
모의: https://mockapi.kiwoom.com
토큰: POST /oauth2/token
토큰 TR: au10001
주문 경로: /api/dostk/ordr
매수 TR: kt10000
매도 TR: kt10001
정정 TR: kt10002
취소 TR: kt10003
```

## 안전 설정

```dotenv
KIWOOM_USE_MOCK=true
KIWOOM_LIVE_ORDER_ENABLED=false
```

`trde_tp`의 시장가·지정가 값은 현재 키움 공식 명세에서 직접 확인해 설정하세요.
코드에 추정값을 넣지 않았습니다.

```dotenv
KIWOOM_MARKET_TRADE_TYPE=
KIWOOM_LIMIT_TRADE_TYPE=
```

실전 주문은 활성화하지 마세요.

## 테스트

```powershell
$env:PYTHONPATH = "D:\Projects\stock-platform\src"

python -m pytest `
    tests\test_kiwoom_order_mapper.py `
    tests\test_kiwoom_token_provider.py `
    -q
```

## Git 커밋

```powershell
git add README_STEP28_2.md src\stock_platform\broker\kiwoom tests\test_kiwoom_order_mapper.py tests\test_kiwoom_token_provider.py
git commit -m "feat(broker): add Kiwoom REST order adapter"
```

다음 단계는 STEP28-3 키움 계좌·보유종목 동기화입니다.
