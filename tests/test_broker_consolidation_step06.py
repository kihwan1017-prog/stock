"""STEP6 — broker 통합: 호환 래퍼 identity · 미지원 기능."""

from __future__ import annotations

import pytest

from stock_platform.broker.exceptions import (
    UnsupportedBrokerFeatureError,
)
from stock_platform.broker.kiwoom.market.exceptions import (
    KiwoomError as CanonicalKiwoomError,
    KiwoomRequestError as CanonicalKiwoomRequestError,
)
from stock_platform.broker.upbit.exceptions import (
    UpbitError as CanonicalUpbitError,
    UpbitRateLimitError as CanonicalUpbitRateLimitError,
)
from stock_platform.brokers.kiwoom.exceptions import (
    KiwoomError as CompatKiwoomError,
    KiwoomRequestError as CompatKiwoomRequestError,
)
from stock_platform.brokers.upbit.exceptions import (
    UpbitError as CompatUpbitError,
    UpbitRateLimitError as CompatUpbitRateLimitError,
)


@pytest.mark.unit
def test_brokers_compat_reexports_same_exception_classes() -> None:
    """래퍼와 canonical 이 동일 클래스여야 exception_handlers isinstance 가 유지된다."""

    assert CompatKiwoomError is CanonicalKiwoomError
    assert CompatKiwoomRequestError is CanonicalKiwoomRequestError
    assert CompatUpbitError is CanonicalUpbitError
    assert CompatUpbitRateLimitError is CanonicalUpbitRateLimitError


@pytest.mark.unit
def test_brokers_compat_reexports_clients() -> None:
    from stock_platform.broker.kiwoom.market.client import (
        KiwoomRestClient as CanonicalKiwoom,
    )
    from stock_platform.broker.upbit.market.client import (
        UpbitQuotationClient as CanonicalUpbit,
    )
    from stock_platform.brokers.kiwoom.client import (
        KiwoomRestClient as CompatKiwoom,
    )
    from stock_platform.brokers.upbit.client import (
        UpbitQuotationClient as CompatUpbit,
    )

    assert CompatKiwoom is CanonicalKiwoom
    assert CompatUpbit is CanonicalUpbit


@pytest.mark.unit
def test_async_rate_limiter_canonical_path() -> None:
    from stock_platform.broker.common.async_rate_limiter import (
        AsyncSlidingWindowRateLimiter as Canonical,
    )
    from stock_platform.brokers.kiwoom.rate_limiter import (
        AsyncSlidingWindowRateLimiter as Compat,
    )

    assert Compat is Canonical


@pytest.mark.unit
def test_unsupported_broker_feature_is_broker_error() -> None:
    from stock_platform.broker.exceptions import BrokerError

    exc = UnsupportedBrokerFeatureError("not supported")
    assert isinstance(exc, BrokerError)
    with pytest.raises(UnsupportedBrokerFeatureError):
        raise UnsupportedBrokerFeatureError("x")
