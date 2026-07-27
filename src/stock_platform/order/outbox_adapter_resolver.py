"""Outbox → BrokerAdapter 라우팅 (PAPER 기본, LIVE는 이중 게이트)."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from stock_platform.broker.adapter import BrokerAdapter
from stock_platform.broker.factory import BrokerAdapterFactory
from stock_platform.broker.models import BrokerEnvironment
from stock_platform.broker.paper.adapter import PaperBrokerAdapter
from stock_platform.broker.upbit.adapter import UpbitBrokerAdapter
from stock_platform.common.settings import get_settings


def resolve_outbox_adapter(
    payload: dict[str, Any],
    *,
    session: Session | None = None,
    default_adapter: BrokerAdapter | None = None,
) -> BrokerAdapter:
    """
    payload.environment / broker_code 로 어댑터 선택.

    - environment 미지정 또는 PAPER → Paper (업비트는 mock 어댑터)
    - LIVE → Factory + transition 가드
    """

    fallback = default_adapter or PaperBrokerAdapter()
    broker_code = str(
        payload.get("broker_code") or "PAPER"
    ).strip().upper()
    environment = str(
        payload.get("environment") or "PAPER"
    ).strip().upper()

    if environment == BrokerEnvironment.LIVE.value:
        if session is None:
            raise PermissionError(
                "LIVE outbox dispatch requires DB session"
            )
        uba_raw = payload.get("user_broker_account_id")
        uba_id = (
            None if uba_raw in (None, "") else int(uba_raw)
        )
        return BrokerAdapterFactory.create(
            BrokerEnvironment.LIVE,
            broker_code,
            session=session,
            user_broker_account_id=uba_id,
            credential_ref=(
                None
                if payload.get("credential_ref") in (None, "")
                else str(payload.get("credential_ref"))
            ),
            uses_system_shared_credential=bool(
                payload.get("uses_system_shared_credential")
            ),
        )

    # PAPER 경로: 업비트는 mock adapter로 주문 경로 스모크
    if broker_code == "UPBIT":
        return UpbitBrokerAdapter(settings=get_settings())
    return fallback
