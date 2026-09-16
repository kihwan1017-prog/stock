"""KIWOOM REAL 시세 runtime 등록 dry-readiness. Runtime START 없음."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.broker.kiwoom.execution_env import (
    kiwoom_uba_has_explicit_real_execution,
)
from stock_platform.broker.kiwoom.market_realtime_contract import (
    MARKET_TRADE_TYPE,
    MOCK_FEED_FALLBACK_ON_REAL_WS_DOWN,
    REST_POLLING_IS_LIVE_RUNTIME_SOT,
)
from stock_platform.common.settings import get_settings
from stock_platform.strategy_deployment.definition_entities import (
    AccountStrategyLinkEntity,
    StrategyDefinitionEntity,
)
from stock_platform.strategy_deployment.ownership import market_compatible
from stock_platform.trading.account_models import UserBrokerAccount


def evaluate_kiwoom_market_runtime_registration(
    session: Session,
    *,
    user_broker_account_id: int = 1381,
    strategy_id: int = 17579,
    symbol: str = "034310",
) -> dict[str, Any]:
    """등록 가능 여부. LIVE/ARM/Runner START 판정이 아님."""

    uba_id = int(user_broker_account_id)
    sid = int(strategy_id)
    symbol_u = str(symbol).strip().upper()
    settings = get_settings()

    uba = session.get(UserBrokerAccount, uba_id)
    strategy = session.get(StrategyDefinitionEntity, sid)
    link = session.scalar(
        select(AccountStrategyLinkEntity).where(
            AccountStrategyLinkEntity.user_broker_account_id == uba_id,
            AccountStrategyLinkEntity.strategy_id == sid,
        )
    )
    strategy_active = bool(strategy is not None and strategy.is_active)
    link_active = bool(link is not None and link.is_active)
    owner_ok = bool(
        uba is not None
        and strategy is not None
        and int(uba.user_id) == int(strategy.user_id or 0)
        and str(uba.broker_code or "").upper() == "KIWOOM"
    )
    market_ok = False
    if strategy is not None:
        market_ok = market_compatible(
            market_type=str(strategy.market_type or "STOCK"),
            account_broker="KIWOOM",
        )
    real_exec = False
    if uba is not None:
        real_exec = kiwoom_uba_has_explicit_real_execution(session, uba_id)
    market_env = (
        "MOCK" if settings.kiwoom_market_data_is_mock else "REAL"
    )
    contract_ok = str(settings.kiwoom_ws_market_type or "").upper() == (
        MARKET_TRADE_TYPE
    )
    auto_start = bool(settings.kiwoom_market_realtime_auto_start)

    blockers: list[str] = []
    if uba is None or not bool(uba.is_active):
        blockers.append("UBA_INACTIVE")
    if not strategy_active:
        blockers.append("STRATEGY_INACTIVE")
    if not link_active:
        blockers.append("LINK_INACTIVE")
    if not owner_ok:
        blockers.append("OWNER_SCOPE_MISMATCH")
    if not market_ok:
        blockers.append("MARKET_INCOMPATIBLE")
    if not real_exec:
        blockers.append("CREDENTIAL_NOT_EXPLICIT_REAL")
    if not contract_ok:
        blockers.append("MARKET_TYPE_NOT_OFFICIAL_0B")
    if auto_start:
        blockers.append("MARKET_WS_AUTO_START_MUST_STAY_FALSE")

    registration_ready = not blockers
    return {
        "runtime_registration_ready": registration_ready,
        "warmup_ready": False,
        "runtime_start_allowed": False,
        "runner_start_allowed": False,
        "live_activation_allowed": False,
        "scope": {
            "broker_code": "KIWOOM",
            "user_broker_account_id": uba_id,
            "strategy_id": sid,
            "symbol": symbol_u,
        },
        "strategy_active": strategy_active,
        "link_active": link_active,
        "owner_compatible": owner_ok,
        "market_compatible": market_ok,
        "credential_real": real_exec,
        "official_market_type": MARKET_TRADE_TYPE,
        "process_market_environment": market_env,
        "kiwoom_use_mock": bool(settings.kiwoom_use_mock),
        "kiwoom_market_data_is_mock": bool(settings.kiwoom_market_data_is_mock),
        "real_execution_requires_real_market_data": True,
        "mock_signal_rejected_for_real_runtime": True,
        "rest_polling_is_live_runtime_sot": REST_POLLING_IS_LIVE_RUNTIME_SOT,
        "mock_fallback_on_ws_down": MOCK_FEED_FALLBACK_ON_REAL_WS_DOWN,
        "market_realtime_auto_start": auto_start,
        "blockers": blockers,
        "note": (
            "process market env may still inherit KIWOOM_USE_MOCK; "
            "set KIWOOM_MARKET_DATA_USE_MOCK=false for next-session REAL feed "
            "without changing UBA order credential"
        ),
    }
