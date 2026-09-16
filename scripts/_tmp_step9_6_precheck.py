"""STEP 9-6 임시 precheck — 민감정보 미출력."""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import func, select

from stock_platform.broker.live_transition_entities import (
    LiveTradingTransitionEntity,
)
from stock_platform.broker.live_transition_service import (
    LiveTradingTransitionService,
)
from stock_platform.common.settings import get_settings, resolve_env_file
from stock_platform.database.session import get_session_factory
from stock_platform.order.entities import TradingOrderEntity
from stock_platform.risk_engine.resolved_policy import (
    ResolvedRiskPolicyResolver,
)
from stock_platform.trading.account_models import UserBrokerAccount

UBA = 58


def main() -> None:
    settings = get_settings()
    print("env_file", resolve_env_file())
    print("global_live", settings.global_live_order_enabled)
    print("upbit_live", settings.upbit_live_order_enabled)
    print("upbit_mock", settings.upbit_use_mock)

    session = get_session_factory()()
    try:
        uba = session.get(UserBrokerAccount, UBA)
        assert uba is not None
        now = datetime.now(timezone.utc)
        exp = uba.arm_expires_at
        rem = None
        if exp is not None:
            if exp.tzinfo is None:
                exp = exp.replace(tzinfo=timezone.utc)
            rem = round((exp - now).total_seconds(), 1)
        print(
            "uba",
            {
                "live": uba.live_order_enabled,
                "arm": uba.live_armed,
                "remaining_sec": rem,
                "expires_kst": (
                    exp.astimezone(ZoneInfo("Asia/Seoul")).isoformat()
                    if exp
                    else None
                ),
                "user_id": uba.user_id,
                "broker": uba.broker_code,
            },
        )
        orders = session.scalar(
            select(func.count())
            .select_from(TradingOrderEntity)
            .where(TradingOrderEntity.user_broker_account_id == UBA)
        )
        print("orders", orders)

        active = LiveTradingTransitionService(session).get_active()
        print("transition_active", active is not None)
        if active is not None:
            print(
                "transition",
                {
                    "id": active.transition_id,
                    "status": active.activation_status,
                    "enabled": active.enabled,
                    "expires_at": str(active.expires_at),
                    "broker": active.broker_code,
                    "uba": active.user_broker_account_id,
                },
            )

        n = session.scalar(
            select(func.count()).select_from(LiveTradingTransitionEntity)
        )
        print("transition_rows", n)
        rows = session.scalars(
            select(LiveTradingTransitionEntity)
            .order_by(LiveTradingTransitionEntity.transition_id.desc())
            .limit(5)
        ).all()
        for row in rows:
            print(
                "row",
                {
                    "id": row.transition_id,
                    "status": row.activation_status,
                    "enabled": row.enabled,
                    "expires": str(row.expires_at),
                    "broker": row.broker_code,
                    "uba": row.user_broker_account_id,
                    "ready": (row.validation_payload or {}).get("ready"),
                },
            )

        policy = ResolvedRiskPolicyResolver(session).resolve(
            user_id=int(uba.user_id),
            user_broker_account_id=UBA,
        )
        print(
            "policy",
            {
                "max_order_quantity": str(policy.max_order_quantity),
                "daily_order_limit": policy.daily_order_limit,
                "max_open_orders": policy.max_open_orders,
                "arm_ttl": policy.arm_ttl_seconds,
            },
        )
    finally:
        session.close()
    print("now_kst", datetime.now(ZoneInfo("Asia/Seoul")).isoformat())


if __name__ == "__main__":
    main()
