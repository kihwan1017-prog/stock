"""STEP 8-5-5 — Strategy Runtime Scope (불변)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class AccountKind(StrEnum):
    PAPER = "PAPER"
    USER_BROKER = "USER_BROKER"


class RuntimeLifecycleStatus(StrEnum):
    CREATED = "CREATED"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    STOPPED = "STOPPED"
    ERROR = "ERROR"


class StrategyRuntimeScopeError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True, slots=True)
class StrategyRuntimeScope:
    """계좌·전략 단위 Runtime Scope — 전역 슬롯 대체."""

    user_id: int
    account_kind: AccountKind
    account_id: int
    strategy_id: int
    strategy_version: str
    market_type: str
    broker_code: str
    strategy_code: str = ""
    market_code: str = ""

    def __post_init__(self) -> None:
        if self.user_id <= 0:
            raise StrategyRuntimeScopeError(
                "user_required", "user_id must be > 0"
            )
        if self.account_id <= 0:
            raise StrategyRuntimeScopeError(
                "account_required", "account_id must be > 0"
            )
        if self.strategy_id <= 0:
            raise StrategyRuntimeScopeError(
                "strategy_required", "strategy_id must be > 0"
            )
        if not (self.strategy_version or "").strip():
            raise StrategyRuntimeScopeError(
                "version_required",
                "strategy_version is required",
            )
        if not (self.market_type or "").strip():
            raise StrategyRuntimeScopeError(
                "market_required", "market_type is required"
            )
        if not (self.broker_code or "").strip():
            raise StrategyRuntimeScopeError(
                "broker_required", "broker_code is required"
            )
        broker = self.broker_code.upper()
        if (
            self.account_kind == AccountKind.USER_BROKER
            and broker == "PAPER"
        ):
            raise StrategyRuntimeScopeError(
                "account_broker_mismatch",
                "LIVE UBA cannot use PAPER broker_code",
            )
        if (
            self.account_kind == AccountKind.PAPER
            and broker != "PAPER"
        ):
            raise StrategyRuntimeScopeError(
                "paper_broker_required",
                "Paper scope requires broker_code=PAPER",
            )

    @property
    def user_broker_account_id(self) -> int | None:
        if self.account_kind == AccountKind.USER_BROKER:
            return self.account_id
        return None

    @property
    def paper_account_id(self) -> int | None:
        if self.account_kind == AccountKind.PAPER:
            return self.account_id
        return None

    @property
    def scope_key(self) -> str:
        """개인정보·계좌번호 원문 없이 안정적인 키."""

        acct = (
            f"uba:{self.account_id}"
            if self.account_kind == AccountKind.USER_BROKER
            else f"paper:{self.account_id}"
        )
        return "|".join(
            [
                f"user:{self.user_id}",
                acct,
                f"sid:{self.strategy_id}",
                f"ver:{self.strategy_version.strip()}",
                f"type:{self.market_type.upper()}",
                f"broker:{self.broker_code.upper()}",
            ]
        )

    def masked_for_log(self) -> dict[str, Any]:
        return {
            "scope_key": self.scope_key,
            "user_id": self.user_id,
            "account_kind": self.account_kind.value,
            "account_id": self.account_id,
            "strategy_id": self.strategy_id,
            "strategy_version": self.strategy_version,
            "market_type": self.market_type,
            "broker_code": self.broker_code,
            "strategy_code": self.strategy_code or None,
        }

    def matches_account(
        self,
        *,
        paper_account_id: int | None = None,
        user_broker_account_id: int | None = None,
    ) -> bool:
        if (
            self.account_kind == AccountKind.PAPER
            and paper_account_id is not None
        ):
            return self.account_id == int(paper_account_id)
        if (
            self.account_kind == AccountKind.USER_BROKER
            and user_broker_account_id is not None
        ):
            return self.account_id == int(user_broker_account_id)
        return False
