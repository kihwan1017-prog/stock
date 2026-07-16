# STEP32-4 실제 키움 REST 주문 Adapter

공식 키움 REST 사양에 맞춰 접근토큰 발급과 국내주식 매수·매도 주문을 연결합니다.

## 공식 사양 반영

```text
운영: https://api.kiwoom.com
모의: https://mockapi.kiwoom.com
토큰: POST /oauth2/token
주문: POST /api/dostk/ordr
매수 api-id: kt10000
매도 api-id: kt10001
```

필수 주문 헤더:

```text
authorization: Bearer {token}
api-id: kt10000 또는 kt10001
Content-Type: application/json;charset=UTF-8
```

주문 Body:

```text
dmst_stex_tp
stk_cd
ord_qty
ord_uv
trde_tp
```

## 환경변수

`stock-platform.env`:

```dotenv
KIWOOM_USE_MOCK=true
KIWOOM_LIVE_ORDER_ENABLED=false

KIWOOM_APP_KEY=발급받은_앱키
KIWOOM_SECRET_KEY=발급받은_시크릿키
KIWOOM_HTTP_TIMEOUT_SECONDS=10
```

이 단계에서는 `KIWOOM_ORDER_WS_PATH`와
`KIWOOM_ORDER_WS_SUBSCRIBE_JSON`을 추가하지 않습니다.
REST 주문 전송에는 WebSocket 설정이 필요하지 않습니다.

## 안전장치

운영 서버 주문은 아래 두 조건을 모두 만족해야 합니다.

```dotenv
KIWOOM_USE_MOCK=false
KIWOOM_LIVE_ORDER_ENABLED=true
```

모의투자 검증 전에는 두 번째 값을 `false`로 유지하세요.

## 의존성

```powershell
pip install httpx
```

또는 `requirements.txt`에 추가:

```text
httpx>=0.27,<1
```

## 테스트

```powershell
$env:PYTHONPATH = "D:\Projects\stock-platform\src"

python -m pytest `
  tests\test_kiwoom_order_mapper.py `
  tests\test_kiwoom_token_client.py `
  tests\test_kiwoom_rest_adapter.py `
  tests\test_order_dispatcher.py `
  -q
```

테스트는 실제 주문을 전송하지 않습니다.

## 적용 파일

```text
src/stock_platform/broker/kiwoom/config.py
src/stock_platform/broker/kiwoom/token_client.py
src/stock_platform/broker/kiwoom/order_mapper.py
src/stock_platform/broker/kiwoom/adapter.py
src/stock_platform/broker/factory.py
tests/test_kiwoom_order_mapper.py
tests/test_kiwoom_token_client.py
tests/test_kiwoom_rest_adapter.py
README_STEP32_4.md
```

## 주의

- 모의투자는 KRX만 지원합니다.
- 국내주식 주문 TR은 공식 안내상 토큰별 초당 5회 제한입니다.
- 현재 토큰을 주문마다 발급하므로 운영 전에는 토큰 캐시를 추가해야 합니다.
- 취소·정정·주문조회는 후속 단계에서 구현합니다.

## Git

```powershell
git add README_STEP32_4.md requirements.txt `
  src\stock_platform\broker\kiwoom `
  src\stock_platform\broker\factory.py `
  tests\test_kiwoom_order_mapper.py `
  tests\test_kiwoom_token_client.py `
  tests\test_kiwoom_rest_adapter.py

git commit -m "feat(broker): connect Kiwoom REST stock orders"
```

다음 단계는 STEP32-5 토큰 캐시·호출 제한·주문 조회 및 복구입니다.
