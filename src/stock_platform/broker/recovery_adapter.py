"""STEP 8-4 — 공통 Recovery Adapter 계약."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol

from stock_platform.common.json_safe import to_jsonable


@dataclass(frozen=True, slots=True)
class AccountRecoveryContext:
    """계좌 단위 Recovery 식별자."""

    user_id: int | None
    broker_code: str
    market_type: str  # STOCK | CRYPTO | ALL
    paper_account_id: int | None = None
    user_broker_account_id: int | None = None
    account_ref_masked: str | None = None
    # 환경변수 공용 키움 등 — 평문 계좌번호는 로그에 남기지 말 것
    account_number_for_broker: str | None = None
    trigger_type: str = "MANUAL"  # STARTUP | SCHEDULER | MANUAL | RETRY
    requested_by: str | None = None
    allow_auto_create_external_orders: bool = False
    timeout_seconds: float = 60.0

    @property
    def scope_key(self) -> str:
        if self.user_broker_account_id is not None:
            acct = f"uba:{self.user_broker_account_id}"
        elif self.paper_account_id is not None:
            acct = f"paper:{self.paper_account_id}"
        else:
            acct = "acct:system"
        return (
            f"user:{self.user_id or 'none'}|"
            f"{acct}|broker:{self.broker_code}|"
            f"mkt:{self.market_type}"
        )


@dataclass
class AdapterRecoveryResult:
    """Broker Adapter 공통 결과."""

    status: str  # SUCCESS | PARTIAL | FAILED | MANUAL_REVIEW | SKIPPED
    broker_code: str
    paper_account_id: int | None = None
    user_broker_account_id: int | None = None
    user_id: int | None = None
    started_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    finished_at: datetime | None = None
    open_orders_checked: int = 0
    orders_updated: int = 0
    fills_created: int = 0
    balances_updated: int = 0
    positions_updated: int = 0
    conflicts_found: int = 0
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    retry_required: bool = False
    # STEP 8-15A — fail-closed: Adapter 기본은 Pause 유지 권고
    # (Runtime은 성공 시에도 Pause를 자동 해제하지 않음)
    trading_should_remain_paused: bool = True
    detail: dict[str, Any] = field(default_factory=dict)

    def finish(self) -> AdapterRecoveryResult:
        self.finished_at = datetime.now(timezone.utc)
        return self

    def to_dict(self) -> dict[str, Any]:
        # Decimal 등 JSONB 비호환 타입을 str로 보존 (float 변환 금지)
        return to_jsonable(
            {
                "status": self.status,
                "broker_code": self.broker_code,
                "paper_account_id": self.paper_account_id,
                "user_broker_account_id": self.user_broker_account_id,
                "user_id": self.user_id,
                "started_at": self.started_at.isoformat(),
                "finished_at": (
                    self.finished_at.isoformat()
                    if self.finished_at
                    else None
                ),
                "open_orders_checked": self.open_orders_checked,
                "orders_updated": self.orders_updated,
                "fills_created": self.fills_created,
                "balances_updated": self.balances_updated,
                "positions_updated": self.positions_updated,
                "conflicts_found": self.conflicts_found,
                "errors": list(self.errors),
                "warnings": list(self.warnings),
                "retry_required": self.retry_required,
                "trading_should_remain_paused": (
                    self.trading_should_remain_paused
                ),
                "detail": dict(self.detail),
            }
        )


class RecoveryAdapter(Protocol):
    """Broker별 Recovery 계약."""

    broker_code: str

    def supports(self, context: AccountRecoveryContext) -> bool:
        ...

    async def recover(
        self, context: AccountRecoveryContext
    ) -> AdapterRecoveryResult:
        ...
