"""KRX collector REST host 분리.

Runtime WS / process KIWOOM_USE_MOCK 은 유지한다.
일봉·종목 마스터 수집만 REAL REST host를 쓸 수 있다.
"""

from __future__ import annotations

from stock_platform.broker.kiwoom.execution_env import KIWOOM_REAL_EXECUTION_BASE
from stock_platform.broker.kiwoom.market.auth import KiwoomTokenManager
from stock_platform.broker.kiwoom.market.client import KiwoomRestClient


def build_kiwoom_market_data_client(
    *,
    use_real_rest: bool = True,
) -> KiwoomRestClient:
    """시장데이터 REST 클라이언트.

    use_real_rest=True 이면 api.kiwoom.com (주문/WS ENV와 분리).
    False 이면 process KIWOOM_USE_MOCK host.
    """

    base_url = KIWOOM_REAL_EXECUTION_BASE if use_real_rest else None
    token_manager = KiwoomTokenManager(base_url=base_url)
    return KiwoomRestClient(
        token_manager=token_manager,
        base_url=base_url,
    )
