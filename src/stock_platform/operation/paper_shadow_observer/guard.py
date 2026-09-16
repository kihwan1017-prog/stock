"""PAPER SHADOW 관찰 전용 차단기.

주문/Outbox/Broker 경로를 호출하면 즉시 실패한다.
운영 Risk Engine·OES 구현을 변경하지 않는다.
"""

from __future__ import annotations

import os
from typing import Any, NoReturn

# 프로세스 기본값: 관찰 전용
os.environ.setdefault("SHADOW_OBSERVATION_ONLY", "true")

SHADOW_OBSERVATION_ONLY_ENV = "SHADOW_OBSERVATION_ONLY"

FORBIDDEN_CALLS = (
    "submit_order",
    "create_order",
    "enqueue_outbox",
    "broker_order",
    "position_mutation",
)


class ShadowOrderIsolationError(RuntimeError):
    """관찰 전용 경로에서 주문 계열 호출이 감지됨."""


def observation_only_enabled() -> bool:
    raw = (os.environ.get(SHADOW_OBSERVATION_ONLY_ENV) or "true").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def assert_observation_only() -> None:
    if not observation_only_enabled():
        raise ShadowOrderIsolationError(
            "SHADOW_OBSERVATION_ONLY must stay true for this observer"
        )


def blocked_call(name: str) -> NoReturn:
    """OES/Outbox/Broker 호출 자리. 실제 구현에 연결하지 않는다."""

    raise ShadowOrderIsolationError(
        f"{name} is blocked in SHADOW observation-only mode"
    )


def blocked_submit_order(*_args: Any, **_kwargs: Any) -> NoReturn:
    blocked_call("submit_order")


def blocked_create_order(*_args: Any, **_kwargs: Any) -> NoReturn:
    blocked_call("create_order")


def blocked_enqueue_outbox(*_args: Any, **_kwargs: Any) -> NoReturn:
    blocked_call("enqueue_outbox")


def blocked_broker_order(*_args: Any, **_kwargs: Any) -> NoReturn:
    blocked_call("broker_order")


def blocked_position_mutation(*_args: Any, **_kwargs: Any) -> NoReturn:
    blocked_call("position_mutation")
