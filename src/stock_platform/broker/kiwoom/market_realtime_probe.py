"""UBA REAL credential로 시세 WS LOGIN/REG ACK probe. 주문 없음."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from stock_platform.broker.credential_adapter_factory import (
    build_kiwoom_order_config_from_vault,
    resolve_uba_credential,
)
from stock_platform.broker.kiwoom.market_realtime_client import (
    KiwoomMarketRealtimeClient,
)
from stock_platform.broker.kiwoom.token_cache import KiwoomTokenCache
from stock_platform.broker.kiwoom.token_client import KiwoomTokenClient
from stock_platform.broker.kiwoom.ws_config import KiwoomMarketWebSocketConfig


async def probe_kiwoom_real_market_ws(
    session: Session,
    *,
    user_broker_account_id: int,
    symbols: list[str],
    idle_seconds: float = 1.0,
) -> dict[str, Any]:
    # probe/시세 경로는 last_used write-lock 불필요
    resolved = resolve_uba_credential(
        session,
        user_broker_account_id,
        expected_broker="KIWOOM",
        touch_last_used=False,
    )
    config = build_kiwoom_order_config_from_vault(resolved)
    if bool(config.use_mock):
        return {
            "attempted": False,
            "reason": "UBA_CREDENTIAL_IS_MOCK",
        }
    token_cache = KiwoomTokenCache(KiwoomTokenClient(config))
    client = KiwoomMarketRealtimeClient(
        config=KiwoomMarketWebSocketConfig.for_real_host(),
        token_cache=token_cache,
    )
    result = await client.probe_login_and_register(
        symbols,
        idle_seconds=idle_seconds,
    )
    result["attempted"] = True
    result["user_broker_account_id"] = int(user_broker_account_id)
    result["create_cancel_amend"] = {"create": 0, "cancel": 0, "amend": 0}
    return result
