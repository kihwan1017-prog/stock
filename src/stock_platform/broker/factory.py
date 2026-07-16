from stock_platform.broker.adapter import BrokerAdapter
from stock_platform.broker.kiwoom.adapter import KiwoomBrokerAdapter
from stock_platform.broker.models import BrokerEnvironment
from stock_platform.broker.paper.adapter import PaperBrokerAdapter

class BrokerAdapterFactory:
    @staticmethod
    def create(environment: BrokerEnvironment, broker_code: str) -> BrokerAdapter:
        if environment == BrokerEnvironment.PAPER:
            return PaperBrokerAdapter()
        if environment == BrokerEnvironment.LIVE and broker_code.upper() == "KIWOOM":
            return KiwoomBrokerAdapter()
        raise ValueError(f"Unsupported broker: environment={environment}, broker={broker_code}")
