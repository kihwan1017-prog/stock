class BrokerError(RuntimeError):
    pass

class BrokerConnectionError(BrokerError):
    pass

class BrokerAuthenticationError(BrokerError):
    pass

class BrokerOrderRejectedError(BrokerError):
    pass
