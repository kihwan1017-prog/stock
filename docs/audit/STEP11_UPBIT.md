# STEP 11 — 업비트 기능 상세 검증

> 작성일: 2026-07-22 · 실주문 없음

## 1. 분석
JWT/query hash/nonce, mock 주문, live 이중 게이트, 시세·일봉, min notional(지정가/시장가매수) 구현됨.

## 2. 수정
- 주문 body에 identifier(client_order_id)
- PermissionError → BrokerOrderResult REJECTED (500 방지)
- /api/v1/upbit/* router에 
equire_admin (미인증 sync 차단)

## 3. 남은 문제
OrderRestClient rate limit, reconcile 미연동, 시장가 매도 notional, RateLimit→429 세분

## 4. 권장 커밋
ix(step11): secure upbit sync API and soft-fail live gates
