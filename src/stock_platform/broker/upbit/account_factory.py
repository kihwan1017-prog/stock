from __future__ import annotations

from stock_platform.broker.upbit.private_client import (
    UpbitPrivateClient,
)
from stock_platform.common.settings import get_settings


def build_upbit_private_client(
    *,
    require_credentials: bool = True,
) -> UpbitPrivateClient:
    """설정 기반 private 클라이언트.

    require_credentials=False 이면 status 조회처럼 키 없이도 생성한다.
    """

    settings = get_settings()
    if require_credentials and not settings.upbit_use_mock:
        settings.validate_upbit_credentials()
    return UpbitPrivateClient(settings=settings)
