# STEP32-5 키움 토큰 캐시·호출 제한·주문 복구

이번 단계에서는 다음 기능을 추가합니다.

```text
접근토큰 메모리 캐시
만료 5분 전 자동 재발급
HTTP 401/403 발생 시 토큰 1회 재발급
주문 TR 초당 5회 제한
조회 TR 초당 5회 제한
미체결 ka10075 조회
체결 ka10076 조회
서버 재시작 후 미체결 주문 복구
연속조회 cont-yn / next-key 처리
```

키움 공식 안내상 국내주식 주문 TR과 조회 TR은
각각 계좌별·토큰별 초당 5회입니다.

## 추가 파일

```text
src/stock_platform/broker/kiwoom/token_cache.py
src/stock_platform/broker/kiwoom/rate_limiter.py
src/stock_platform/broker/kiwoom/http_client.py
src/stock_platform/broker/kiwoom/inquiry_models.py
src/stock_platform/broker/kiwoom/inquiry_mapper.py
src/stock_platform/broker/kiwoom/inquiry_client.py
src/stock_platform/broker/kiwoom/recovery.py
tests/test_kiwoom_token_cache.py
tests/test_kiwoom_rate_limiter.py
tests/test_kiwoom_http_client.py
tests/test_kiwoom_inquiry_mapper.py
```

다음 파일은 교체합니다.

```text
src/stock_platform/broker/kiwoom/adapter.py
```

## 환경변수

```dotenv
KIWOOM_USE_MOCK=true
KIWOOM_LIVE_ORDER_ENABLED=false
KIWOOM_APP_KEY=발급받은_앱키
KIWOOM_SECRET_KEY=발급받은_시크릿키
KIWOOM_ACCOUNT_NUMBER=계좌번호
KIWOOM_HTTP_TIMEOUT_SECONDS=10
```

## 중요한 확인 사항

`ka10075`, `ka10076`의 세부 요청 Body는 키움 API 명세서
버전과 계좌 설정에 따라 필요한 검색조건이 추가될 수 있습니다.

그래서 `KiwoomOrderInquiryClient`는 다음 인수를 지원합니다.

```python
extra_body={
    "all_stk_tp": "0",
    "trde_tp": "0",
}
```

키움 공식 명세서에서 현재 계정에 필요한 필드명을 확인한 뒤
`extra_body`에 전달하세요.

## 복구 호출 예

```python
summary = KiwoomOrderRecoveryService(
    session=session,
    inquiry_client=inquiry_client,
).recover_pending_orders(
    account_number=settings.kiwoom_account_number
)
```

복구 동작:

```text
키움 미체결 조회
→ broker_order_id로 로컬 주문 조회
→ 체결수량·미체결수량 동기화
→ 부분 체결이면 PARTIALLY_FILLED 상태 반영
```

키움에만 존재하고 로컬 DB에 없는 주문은 자동 생성하지 않고
`missing_local_orders`로 집계합니다. 실거래 안전을 위한 정책입니다.

## 테스트

```powershell
$env:PYTHONPATH = "D:\\Projects\\stock-platform\\src"

python -m pytest `
  tests\\test_kiwoom_token_cache.py `
  tests\\test_kiwoom_rate_limiter.py `
  tests\\test_kiwoom_http_client.py `
  tests\\test_kiwoom_inquiry_mapper.py `
  tests\\test_kiwoom_order_mapper.py `
  tests\\test_order_dispatcher.py `
  -q
```

## Git

```powershell
git add README_STEP32_5.md `
  src\\stock_platform\\broker\\kiwoom `
  tests\\test_kiwoom_token_cache.py `
  tests\\test_kiwoom_rate_limiter.py `
  tests\\test_kiwoom_http_client.py `
  tests\\test_kiwoom_inquiry_mapper.py

git commit -m "feat(broker): add Kiwoom token cache and order recovery"
```

다음 단계는 STEP32-6 키움 취소·정정 주문과 멱등성 처리입니다.
