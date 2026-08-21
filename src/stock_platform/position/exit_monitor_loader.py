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

        # 계좌(user)별 임계값 캐시 — Paper는 사용자 기본 설정 적용
        threshold_by_user: dict[int | None, ExitThresholds] = {}

        positions: list[ManagedPosition] = []
        skipped: list[str] = []
        account_unrealized: dict[int, Decimal] = {}

        for row in open_rows:
            account = accounts.get(row.account_id)
            # STEP 8-5-5 — Recovery Pause 계좌는 Exit 주문 생성 제외
            if account is not None:
                from stock_platform.broker.recovery_lock import (
                    RecoveryAccountLockService,
                )

                if RecoveryAccountLockService(
                    self._session
                ).is_trading_paused(
                    paper_account_id=int(row.account_id),
                    broker_code="PAPER",
                ):
                    skipped.append(
                        f"paused:{row.exchange_code}/{row.symbol}"
                    )
                    continue
            owner_id = (
                int(account.user_id)
                if account is not None and account.user_id is not None
                else None
            )
            if owner_id not in threshold_by_user:
                threshold_by_user[owner_id] = self._resolve_thresholds(
                    user_id=owner_id
                )
            thresholds = threshold_by_user[owner_id]

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

        live_positions, live_skipped = self._load_upbit_live_positions(
            threshold_by_user=threshold_by_user,
        )
        positions.extend(live_positions)
        skipped.extend(live_skipped)

        kiwoom_positions, kiwoom_skipped = (
            self._load_kiwoom_strategy_owned_live_positions(
                threshold_by_user=threshold_by_user,
            )
        )
        positions.extend(kiwoom_positions)
        skipped.extend(kiwoom_skipped)

        daily_loss_triggered = False
        for account_id, unrealized_sum in (
            account_unrealized.items()
        ):
            account = accounts.get(account_id)
            if account is None:
                continue
            owner_id = (
                int(account.user_id)
                if account.user_id is not None
                else None
            )
            if owner_id not in threshold_by_user:
                threshold_by_user[owner_id] = self._resolve_thresholds(
                    user_id=owner_id
                )
            thresholds = threshold_by_user[owner_id]
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
                    # LIVE는 Kill/일손실 강제청산 금지 — OES fail-closed
                    force_exit_reason=(
                        None
                        if str(item.environment).upper() == "LIVE"
                        else force_reason
                    ),
                    user_broker_account_id=(
                        item.user_broker_account_id
                    ),
                    owner_user_id=item.owner_user_id,
                    environment=item.environment,
                    snapshot_synchronized_at=(
                        item.snapshot_synchronized_at
                    ),
                )
                for item in positions
            ]

        return LoadedExitContext(
            positions=positions,
            kill_switch_active=kill_switch_active,
            daily_loss_triggered=daily_loss_triggered,
            skipped_symbols=skipped,
        )

    def _resolve_thresholds(
        self,
        *,
        user_id: int | None = None,
        user_broker_account_id: int | None = None,
    ) -> ExitThresholds:
        # STEP8-2: 사용자/UBA ResolvedRiskPolicy 우선, 없으면 ENV/strategy.risk_policy
        if user_id is not None or user_broker_account_id is not None:
            from stock_platform.risk_engine.resolved_policy import (
                ResolvedRiskPolicyResolver,
            )

            resolved = ResolvedRiskPolicyResolver(
                self._session
            ).resolve(
                user_id=(int(user_id) if user_id is not None else None),
                user_broker_account_id=user_broker_account_id,
            )
            return ExitThresholds(
                stop_loss_ratio=resolved.stop_loss_rate,
                take_profit_ratio=resolved.take_profit_rate,
                trailing_stop_ratio=resolved.trailing_stop_rate,
                relative_loss_ratio=None,
                daily_loss_limit=resolved.daily_max_loss_amount,
            )

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

    def _load_upbit_live_positions(
        self,
        *,
        threshold_by_user: dict[int | None, ExitThresholds],
    ) -> tuple[list[ManagedPosition], list[str]]:
        """UPBIT LIVE 스냅샷 → ManagedPosition. 플래그 OFF면 빈 목록.

        KIWOOM LIVE는 로드하지 않는다. 시세는 QuoteSnapshot (REST 금지).
        """

        settings = get_settings()
        if not bool(
            getattr(
                settings,
                "position_exit_monitor_live_upbit_enabled",
                False,
            )
        ):
            return [], []

        from stock_platform.broker.recovery_lock import (
            RecoveryAccountLockService,
        )
        from stock_platform.position.exit_monitor_live import (
            list_upbit_live_position_rows,
            resolve_trailing_high_water,
            resolve_upbit_live_price,
        )

        stale_seconds = float(
            getattr(
                settings,
                "autotrading_market_feed_stale_seconds",
                30.0,
            )
            or 30.0
        )
        lock = RecoveryAccountLockService(self._session)
        positions: list[ManagedPosition] = []
        skipped: list[str] = []
        threshold_by_uba: dict[int, ExitThresholds] = {}

        rows = list_upbit_live_position_rows(self._session)
        for row, uba in rows:
            uba_id = int(uba.user_broker_account_id)
            symbol = str(row.symbol or "").upper()
            if uba_id <= 0 or not symbol:
                continue
            # 수동/기존 보유 vs strategy-owned 구분 — 의도치 않은 청산 방지
            try:
                from stock_platform.operation.upbit_full_market.constants import (
                    is_any_full_market,
                )
                from stock_platform.operation.upbit_full_market.service import (
                    UpbitFullMarketAssignmentService,
                )

                fma = UpbitFullMarketAssignmentService(self._session)
                st = fma.status_dict(uba_id)
                mode = str(st.get("mode") or "")
                if is_any_full_market(mode):
                    if not fma.is_strategy_owned_symbol(uba_id, symbol):
                        skipped.append(
                            f"manual_holding:LIVE:{uba_id}/{symbol}"
                        )
                        continue
                else:
                    # FIXED: template/current 외 심볼은 EXIT 대상 제외
                    fixed_syms = {
                        str(st.get("template_symbol") or "").upper(),
                        str(st.get("current_symbol") or "").upper(),
                    }
                    fixed_syms.discard("")
                    if fixed_syms and symbol not in fixed_syms:
                        skipped.append(
                            f"manual_holding:LIVE:{uba_id}/{symbol}"
                        )
                        continue
            except Exception:  # noqa: BLE001
                pass
            if lock.is_trading_paused(
                user_broker_account_id=uba_id,
                broker_code="UPBIT",
            ):
                skipped.append(f"paused:LIVE:{uba_id}/{symbol}")
                continue

            current_price = resolve_upbit_live_price(
                self._session,
                symbol=symbol,
                stale_seconds=stale_seconds,
            )
            if current_price is None:
                skipped.append(
                    f"stale_or_missing:LIVE:{uba_id}/{symbol}"
                )
                continue

            owner_id = (
                int(uba.user_id)
                if getattr(uba, "user_id", None) is not None
                else None
            )
            if uba_id not in threshold_by_uba:
                threshold_by_uba[uba_id] = self._resolve_thresholds(
                    user_id=owner_id,
                    user_broker_account_id=uba_id,
                )
            thresholds = threshold_by_uba[uba_id]
            entry = Decimal(str(row.average_purchase_price or 0))
            if entry <= ZERO:
                skipped.append(f"no_entry:LIVE:{uba_id}/{symbol}")
                continue

            highest, trailing_ok = resolve_trailing_high_water(
                row,
                entry=entry,
                current_price=current_price,
            )
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
            trailing_ratio = (
                thresholds.trailing_stop_ratio
                if trailing_ok
                else None
            )
            qty = Decimal(str(row.quantity or 0))
            if qty <= ZERO:
                continue
            positions.append(
                ManagedPosition(
                    account_id=0,
                    exchange_code=str(
                        row.exchange_code or "UPBIT"
                    ).upper()
                    or "UPBIT",
                    symbol=symbol,
                    quantity=qty,
                    entry_price=entry,
                    current_price=current_price,
                    highest_price=highest,
                    stop_loss_price=stop_loss_price,
                    take_profit_price=take_profit_price,
                    trailing_stop_ratio=trailing_ratio,
                    relative_loss_ratio=None,
                    broker_code="UPBIT",
                    user_broker_account_id=uba_id,
                    owner_user_id=owner_id,
                    environment="LIVE",
                    snapshot_synchronized_at=getattr(
                        row, "synchronized_at", None
                    ),
                )
            )
        return positions, skipped

    def _load_kiwoom_strategy_owned_live_positions(
        self,
        *,
        threshold_by_user: dict[int | None, ExitThresholds],
    ) -> tuple[list[ManagedPosition], list[str]]:
        """KIWOOM LIVE — OPEN strategy binding 만. 수동 보유 제외.

        플래그 OFF면 빈 목록. 시세는 QuoteSnapshot/price repo (REST 금지).
        """

        settings = get_settings()
        if not bool(
            getattr(
                settings,
                "position_exit_monitor_live_kiwoom_enabled",
                False,
            )
        ):
            return [], []

        from stock_platform.broker.recovery_lock import (
            RecoveryAccountLockService,
        )
        from stock_platform.risk_engine.strategy_owned_entities import (
            BINDING_STATUS_OPEN,
            OWNERSHIP_STRATEGY,
            StrategyPositionBindingEntity,
        )

        lock = RecoveryAccountLockService(self._session)
        positions: list[ManagedPosition] = []
        skipped: list[str] = []
        threshold_by_uba: dict[int, ExitThresholds] = {}

        bindings = list(
            self._session.scalars(
                select(StrategyPositionBindingEntity).where(
                    StrategyPositionBindingEntity.broker_code == "KIWOOM",
                    StrategyPositionBindingEntity.status
                    == BINDING_STATUS_OPEN,
                    StrategyPositionBindingEntity.ownership_code
                    == OWNERSHIP_STRATEGY,
                )
            )
        )
        for binding in bindings:
            uba_id = int(binding.user_broker_account_id)
            symbol = str(binding.symbol or "").upper()
            qty = Decimal(str(binding.owned_quantity or 0))
            if uba_id <= 0 or not symbol or qty <= ZERO:
                continue
            if lock.is_trading_paused(
                user_broker_account_id=uba_id,
                broker_code="KIWOOM",
            ):
                skipped.append(f"paused:LIVE:{uba_id}/{symbol}")
                continue

            entry = Decimal(str(binding.entry_price or 0))
            if entry <= ZERO:
                skipped.append(f"no_entry:LIVE:{uba_id}/{symbol}")
                continue

            current_price = self._resolve_current_price(
                exchange_code="KRX",
                symbol=symbol,
                fallback=entry,
            )
            if current_price is None:
                skipped.append(
                    f"stale_or_missing:LIVE:{uba_id}/{symbol}"
                )
                continue

            # owner_user_id — UBA row 조회 없이 threshold만 계좌 단위 resolve
            if uba_id not in threshold_by_uba:
                threshold_by_uba[uba_id] = self._resolve_thresholds(
                    user_broker_account_id=uba_id,
                )
            thresholds = threshold_by_uba[uba_id]
            stop_loss_price = (
                entry * (ONE - thresholds.stop_loss_ratio)
            ).quantize(Decimal("1"), rounding=ROUND_DOWN)
            take_profit_price = (
                entry * (ONE + thresholds.take_profit_ratio)
            ).quantize(Decimal("1"), rounding=ROUND_DOWN)
            trailing_ratio = thresholds.trailing_stop_ratio
            highest = max(entry, current_price)

            positions.append(
                ManagedPosition(
                    account_id=0,
                    exchange_code="KRX",
                    symbol=symbol,
                    quantity=qty,
                    entry_price=entry,
                    current_price=current_price,
                    highest_price=highest,
                    stop_loss_price=stop_loss_price,
                    take_profit_price=take_profit_price,
                    trailing_stop_ratio=trailing_ratio,
                    relative_loss_ratio=thresholds.relative_loss_ratio,
                    broker_code="KIWOOM",
                    user_broker_account_id=uba_id,
                    owner_user_id=None,
                    environment="LIVE",
                    snapshot_synchronized_at=None,
                )
            )
        return positions, skipped

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
