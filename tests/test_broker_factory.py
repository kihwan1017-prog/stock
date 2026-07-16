import pytest
from stock_platform.broker.factory import BrokerAdapterFactory
from stock_platform.broker.kiwoom.adapter import KiwoomBrokerAdapter
from stock_platform.broker.models import BrokerEnvironment
from stock_platform.broker.paper.adapter import PaperBrokerAdapter

def test_paper_adapter():
    assert isinstance(
        BrokerAdapterFactory.create(BrokerEnvironment.PAPER, "KIWOOM"),
        PaperBrokerAdapter,
    )

def test_live_kiwoom_adapter():
    assert isinstance(
        BrokerAdapterFactory.create(BrokerEnvironment.LIVE, "KIWOOM"),
        KiwoomBrokerAdapter,
    )

def test_unsupported_broker():
    with pytest.raises(ValueError):
        BrokerAdapterFactory.create(BrokerEnvironment.LIVE, "UNKNOWN")
