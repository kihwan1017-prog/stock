"""시세 REST 호환 패키지 (STEP6).

구현은 `stock_platform.broker.*.market` 으로 이전했다.
기존 `from stock_platform.brokers...` import 는 이 래퍼를 통해
**동일 클래스 객체**를 가리킨다 (예외 isinstance 유지).
"""
