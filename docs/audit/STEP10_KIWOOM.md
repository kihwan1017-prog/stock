# STEP 10 — 키움증권 기능 상세 검증

> 작성일: 2026-07-22  
> 원칙: 실주문 없음 · Mock 기본 유지

## 1. 분석 결과
- 주문 경로: sync http_client + KiwoomBrokerAdapter
- 계좌/미체결: async legacy client
- 시세: roker.kiwoom.market (STEP6)
- WS: ws_client 활성, execution_ws_client dead
- get_order: UnsupportedBrokerFeatureError (inquiry 사용)

## 2. 수정
- token expires_at UTC 정규화
- Live transition에 GLOBAL_LIVE_ORDER_ENABLED 검사
- Adapter live 시 global+kiwoom 이중 게이트

## 3. 테스트
Mock 경로·token·cancel·factory 관련 통과. Live 플래그 기본 false.

## 4. 남은 문제
3중 REST/2중 WS, OrderRecovery 미연결, submit adapter 테스트 skip, return_code 일부 미검증

## 5. 권장 커밋
ix(step10): harden kiwoom token expiry and live transition gates
