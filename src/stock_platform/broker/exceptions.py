class BrokerError(RuntimeError):
    """브로커 주문/계좌 본선 오류."""


class BrokerConnectionError(BrokerError):
    pass


class BrokerAuthenticationError(BrokerError):
    pass


class BrokerOrderRejectedError(BrokerError):
    pass


class UnsupportedBrokerFeatureError(BrokerError):
    """브로커가 해당 기능을 지원하지 않음.

    성공처럼 빈 값/가짜 결과를 반환하지 말고 이 예외를 사용한다.
    """
