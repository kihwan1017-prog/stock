"""Paper 포지션 + 시세 + 리스크 정책 → ManagedPosition 로더."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.common.settings import get_settings
from stock_platform.markets.repository import (
    PriceDailyRepository,
)
from stock_platform.markets.service import (
    InstrumentNotFoundError,
    PriceDailyService,
)
from stock_platform.position.exit_monitor import (
    ManagedPosition,
)
from stock_platform.risk.repository import RiskRepository
from stock_platform.risk_engine.kill_switch_service import (
    KillSwitchService,
)
from stock_platform.risk_engine.runtime import (
    realtime_risk_policy,
)
from stock_platform.trading.account_models import (
    PaperAccount,
    PaperPosition,
)


logger = structlog.get_logger(__name__)

ONE = Decimal("1")
ZERO = Decimal("0")


@dataclass(frozen=True, slots=True)
class ExitThresholds:
    stop_loss_ratio: Decimal
    take_profit_ratio: Decimal
    trailing_stop_ratio: Decimal | None
    relative_loss_ratio: Decimal | None
    daily_loss_limit: Decimal


@dataclass(frozen=True, slots=True)
class LoadedExitContext:
    positions: list[ManagedPosition]
    kill_switch_active: bool
    daily_loss_triggered: bool
    skipped_symbols: list[str]


class PositionExitMonitorLoader:
    """DB 오픈 포지션을 청산 모니터 입력으로 변환한다."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._prices = PriceDailyService(
            PriceDailyRepository(session)
        )
        self._risk_repository = RiskRepository(session)
        self._kill_switch = KillSwitchService(session)

    def load(self) -> LoadedExitContext:
        thresholds = self._resolve_thresholds()
        kill_switch_active = self._kill_switch.is_active()

        open_rows = list(
            self._session.scalars(
                select(PaperPosition).where(
                    PaperPosition.quantity > ZERO
                )
            )
        )

        account_ids = {
            row.account_id for row in open_rows
        }
        # 빈 IN () 회피
        if account_ids:
            accounts = {
                account.account_id: account
                for account in self._session.scalars(
                    select(PaperAccount).where(
                        PaperAccount.account_id.in_(
                            account_ids
                        )
                    )
                )
            }
        else:
            accounts = {}

        positions: list[ManagedPosition] = []
        skipped: list[str] = []
        account_unrealized: dict[int, Decimal] = {}

        for row in open_rows:
            current_price = self._resolve_current_price(
                exchange_code=row.exchange_code,
                symbol=row.symbol,
                fallback=row.average_entry_price,
            )
            if current_price is None:
                skipped.append(
                    f"{row.exchange_code}/{row.symbol}"
                )
                continue

            highest = max(
                row.highest_price or ZERO,
                row.average_entry_price,
                current_price,
            )
            entry = row.average_entry_price
            stop_loss_price = (
                entry * (ONE - thresholds.stop_loss_ratio)
            ).quantize(
                Decimal("0.00000001"),
                rounding=ROUND_DOWN,
            )
            take_profit_price = (
                entry * (ONE + thresholds.take_profit_ratio)
            ).quantize(
                Decimal("0.00000001"),
                rounding=ROUND_DOWN,
            )

            unrealized = (
                (current_price - entry) * row.quantity
            ).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
            account_unrealized[row.account_id] = (
                account_unrealized.get(row.account_id, ZERO)
                + unrealized
            )

            positions.append(
                ManagedPosition(
                    account_id=row.account_id,
                    exchange_code=row.exchange_code,
                    symbol=row.symbol,
                    quantity=row.quantity,
                    entry_price=entry,
                    current_price=current_price,
                    highest_price=highest,
                    stop_loss_price=stop_loss_price,
                    take_profit_price=take_profit_price,
                    trailing_stop_ratio=(
                        thresholds.trailing_stop_ratio
                    ),
                    relative_loss_ratio=(
                        thresholds.relative_loss_ratio
                    ),
                    broker_code="PAPER",
                )
            )

        daily_loss_triggered = False
        for account_id, unrealized_sum in (
            account_unrealized.items()
        ):
            account = accounts.get(account_id)
            if account is None:
                continue
            combined = (
                Decimal(account.realized_profit_loss)
                + unrealized_sum
            )
            current_loss = max(-combined, ZERO)
            if current_loss >= thresholds.daily_loss_limit:
                daily_loss_triggered = True
                logger.info(
                    "position_exit_daily_loss_detected",
                    account_id=account_id,
                    current_loss=str(current_loss),
                    limit=str(thresholds.daily_loss_limit),
                )
                break

        force_reason: str | None = None
        if kill_switch_active:
            force_reason = "KILL_SWITCH"
        elif daily_loss_triggered:
            force_reason = "DAILY_LOSS"

        if force_reason is not None:
            positions = [
                ManagedPosition(
                    account_id=item.account_id,
                    exchange_code=item.exchange_code,
                    symbol=item.symbol,
                    quantity=item.quantity,
                    entry_price=item.entry_price,
                    current_price=item.current_price,
                    highest_price=item.highest_price,
                    stop_loss_price=item.stop_loss_price,
                    take_profit_price=item.take_profit_price,
                    trailing_stop_ratio=(
                        item.trailing_stop_ratio
                    ),
                    relative_loss_ratio=(
                        item.relative_loss_ratio
                    ),
                    broker_code=item.broker_code,
                    force_exit_reason=force_reason,
                )
                for item in positions
            ]

        return LoadedExitContext(
            positions=positions,
            kill_switch_active=kill_switch_active,
            daily_loss_triggered=daily_loss_triggered,
            skipped_symbols=skipped,
        )

    def _resolve_thresholds(self) -> ExitThresholds:
        settings = get_settings()
        stop_loss_ratio = Decimal(
            str(settings.position_exit_stop_loss_ratio)
        )
        take_profit_ratio = Decimal(
            str(settings.position_exit_take_profit_ratio)
        )
        trailing_raw = (
            settings.position_exit_trailing_stop_ratio
        )
        trailing_stop_ratio = (
            Decimal(str(trailing_raw))
            if trailing_raw is not None
            else None
        )
        relative_raw = (
            settings.position_exit_relative_loss_ratio
        )
        relative_loss_ratio = (
            Decimal(str(relative_raw))
            if relative_raw is not None
            else None
        )

        policy = self._risk_repository.get_policy(
            settings.scheduler_policy_id
        )
        if policy is not None and policy.is_active:
            stop_loss_ratio = Decimal(
                str(policy.stop_loss_ratio)
            )
            take_profit_ratio = Decimal(
                str(policy.take_profit_ratio)
            )
            if policy.trailing_stop_ratio is not None:
                trailing_stop_ratio = Decimal(
                    str(policy.trailing_stop_ratio)
                )

        return ExitThresholds(
            stop_loss_ratio=stop_loss_ratio,
            take_profit_ratio=take_profit_ratio,
            trailing_stop_ratio=trailing_stop_ratio,
            relative_loss_ratio=relative_loss_ratio,
            daily_loss_limit=Decimal(
                str(realtime_risk_policy.max_daily_loss)
            ),
        )

    def _resolve_current_price(
        self,
        *,
        exchange_code: str,
        symbol: str,
        fallback: Decimal,
    ) -> Decimal | None:
        try:
            latest = self._prices.get_latest(
                exchange_code,
                symbol,
            )
        except InstrumentNotFoundError:
            logger.warning(
                "position_exit_price_missing",
                exchange_code=exchange_code,
                symbol=symbol,
                reason="instrument_not_found",
            )
            if fallback > ZERO:
                return fallback
            return None
        except Exception as exc:
            logger.warning(
                "position_exit_price_missing",
                exchange_code=exchange_code,
                symbol=symbol,
                error=str(exc),
            )
            if fallback > ZERO:
                return fallback
            return None

        if latest is None:
            if fallback > ZERO:
                return fallback
            return None

        price = Decimal(str(latest.close_price))
        if price <= ZERO:
            if fallback > ZERO:
                return fallback
            return None
        return price
