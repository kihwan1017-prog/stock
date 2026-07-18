from stock_platform.broker.adapter import BrokerAdapter
from stock_platform.broker.kiwoom.adapter import KiwoomBrokerAdapter
from stock_platform.broker.live_transition_guard import (
    LiveTradingTransitionGuard,
)
from stock_platform.broker.models import BrokerEnvironment
from stock_platform.broker.paper.adapter import PaperBrokerAdapter
from stock_platform.common.settings import get_settings


class BrokerAdapterFactory:
    @staticmethod
    def create(
        environment: BrokerEnvironment,
        broker_code: str,
        *,
        session=None,
    ) -> BrokerAdapter:
        if environment == BrokerEnvironment.PAPER:
            return PaperBrokerAdapter()

        if (
            environment == BrokerEnvironment.LIVE
            and broker_code.upper() == "KIWOOM"
        ):
            settings = get_settings()
            if not settings.kiwoom_live_order_enabled:
                raise PermissionError(
                    "KIWOOM_LIVE_ORDER_ENABLED must be true"
                )
            if session is None:
                raise PermissionError(
                    "Live adapter requires DB session for "
                    "transition approval check"
                )
            LiveTradingTransitionGuard(
                session
            ).require_active()
            return KiwoomBrokerAdapter()

        raise ValueError(
            f"Unsupported broker: environment={environment}, "
            f"broker={broker_code}"
        )
