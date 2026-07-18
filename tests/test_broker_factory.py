import pytest

from stock_platform.broker.factory import BrokerAdapterFactory
from stock_platform.broker.models import BrokerEnvironment
from stock_platform.broker.paper.adapter import PaperBrokerAdapter


def test_create_paper_adapter():
    adapter = BrokerAdapterFactory.create(
        BrokerEnvironment.PAPER,
        "KIWOOM",
    )
    assert isinstance(adapter, PaperBrokerAdapter)


def test_create_live_adapter_requires_session_and_flag(
    monkeypatch,
):
    monkeypatch.setenv("KIWOOM_LIVE_ORDER_ENABLED", "false")
    from stock_platform.common.settings import get_settings

    get_settings.cache_clear()
    try:
        with pytest.raises(PermissionError):
            BrokerAdapterFactory.create(
                BrokerEnvironment.LIVE,
                "KIWOOM",
                session=object(),
            )
    finally:
        get_settings.cache_clear()


def test_create_unknown_live_broker_raises():
    with pytest.raises(ValueError):
        BrokerAdapterFactory.create(
            BrokerEnvironment.LIVE,
            "UNKNOWN",
        )
