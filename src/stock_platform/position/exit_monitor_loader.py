"""Paper 포지션 + 시세 + 리스크 정책 → ManagedPosition 로더."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
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


def _protective_prices(
    *,
    entry: Decimal,
    thresholds: "ExitThresholds",
    quantize: str = "0.00000001",
) -> tuple[Decimal | None, Decimal | None]:
    """DISABLED(None ratio)면 해당 가격 None — REAL trigger 없음."""

    stop_loss_price = None
    take_profit_price = None
    if thresholds.stop_loss_ratio is not None:
        stop_loss_price = (
            entry * (ONE - thresholds.stop_loss_ratio)
        ).quantize(Decimal(quantize), rounding=ROUND_DOWN)
    if thresholds.take_profit_ratio is not None:
        take_profit_price = (
            entry * (ONE + thresholds.take_profit_ratio)
        ).quantize(Decimal(quantize), rounding=ROUND_DOWN)
    return stop_loss_price, take_profit_price


@dataclass(frozen=True, slots=True)
class ExitThresholds:
    # DISABLED면 None — REAL 가격 트리거 미생성
    stop_loss_ratio: Decimal | None
    take_profit_ratio: Decimal | None
    trailing_stop_ratio: Decimal | None
    relative_loss_ratio: Decimal | None
    daily_loss_limit: Decimal
    trailing_activation_ratio: Decimal | None = None
    max_hold_seconds: int | None = None


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
            stop_loss_price, take_profit_price = _protective_prices(
                entry=entry,
                thresholds=thresholds,
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
                    binding_id=item.binding_id,
                    holding_seconds=item.holding_seconds,
                    max_hold_seconds=item.max_hold_seconds,
                    trailing_activation_ratio=(
                        item.trailing_activation_ratio
                    ),
                    trailing_armed=item.trailing_armed,
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
                trailing_activation_ratio=resolved.trailing_activation_rate,
                max_hold_seconds=(
                    resolved.max_hold_seconds
                    if resolved.max_hold_effective_enabled
                    else None
                ),
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
            # Exit SoT: canonical strategy_position_binding (upbit binding drift 허용)
            try:
                from stock_platform.operation.upbit_full_market.constants import (
                    is_any_full_market,
                )
                from stock_platform.operation.upbit_full_market.service import (
                    UpbitFullMarketAssignmentService,
                )
                from stock_platform.risk_engine.strategy_owned_entities import (
                    BINDING_STATUS_OPEN,
                    OWNERSHIP_MANUAL,
                    OWNERSHIP_STRATEGY,
                    OWNERSHIP_UNKNOWN,
                    StrategyPositionBindingEntity,
                )

                fma = UpbitFullMarketAssignmentService(self._session)
                st = fma.status_dict(uba_id)
                mode = str(st.get("mode") or "")
                canonical = self._session.scalar(
                    select(StrategyPositionBindingEntity).where(
                        StrategyPositionBindingEntity.user_broker_account_id
                        == uba_id,
                        StrategyPositionBindingEntity.broker_code == "UPBIT",
                        StrategyPositionBindingEntity.symbol == symbol,
                        StrategyPositionBindingEntity.status
                        == BINDING_STATUS_OPEN,
                    )
                )
                ownership = (
                    str(getattr(canonical, "ownership_code", "") or "")
                    .strip()
                    .upper()
                    if canonical is not None
                    else ""
                )
                if ownership in {OWNERSHIP_MANUAL, OWNERSHIP_UNKNOWN}:
                    skipped.append(
                        f"manual_holding:LIVE:{uba_id}/{symbol}"
                    )
                    continue
                if is_any_full_market(mode):
                    # STRATEGY_OWNED canonical 우선; 없으면 레거시 upbit binding
                    strategy_owned = ownership == OWNERSHIP_STRATEGY or (
                        canonical is None
                        and fma.is_strategy_owned_symbol(uba_id, symbol)
                    )
                    if not strategy_owned:
                        skipped.append(
                            f"manual_holding:LIVE:{uba_id}/{symbol}"
                        )
                        continue
                else:
                    # FIXED: template/current 외는 canonical STRATEGY_OWNED만 허용
                    fixed_syms = {
                        str(st.get("template_symbol") or "").upper(),
                        str(st.get("current_symbol") or "").upper(),
                    }
                    fixed_syms.discard("")
                    if (
                        fixed_syms
                        and symbol not in fixed_syms
                        and ownership != OWNERSHIP_STRATEGY
                    ):
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
                activation_rate=thresholds.trailing_activation_ratio,
            )
            stop_loss_price, take_profit_price = _protective_prices(
                entry=entry,
                thresholds=thresholds,
            )
            trailing_ratio = (
                thresholds.trailing_stop_ratio
                if trailing_ok
                else None
            )
            qty = Decimal(str(row.quantity or 0))
            if qty <= ZERO:
                continue
            # OPEN binding 필수 — CLOSED 후 trailing/telegram spam 방지
            from stock_platform.position.exit_monitor_live import (
                STATE_TRAILING_ARMED,
                has_blocking_live_exit_sell,
                is_live_exit_eligible,
                load_open_strategy_binding,
                read_exit_lifecycle,
            )

            open_binding = load_open_strategy_binding(
                self._session,
                user_broker_account_id=uba_id,
                symbol=symbol,
                broker_code="UPBIT",
            )
            blocking = has_blocking_live_exit_sell(
                self._session,
                user_broker_account_id=uba_id,
                symbol=symbol,
                snapshot_synchronized_at=getattr(
                    row, "synchronized_at", None
                ),
            )
            eligible, skip_reason = is_live_exit_eligible(
                quantity=qty,
                binding=open_binding,
                has_active_exit_order=blocking,
            )
            if not eligible:
                skipped.append(
                    f"TRAILING_EVALUATION_SKIPPED:{skip_reason}"
                    f":LIVE:{uba_id}/{symbol}"
                )
                continue
            binding_id = (
                int(open_binding.binding_id)
                if open_binding is not None
                and getattr(open_binding, "binding_id", None) is not None
                else None
            )
            # 보유초 — OPEN binding.opened_at 기준 (프로세스 시작 시각 금지)
            holding_seconds: int | None = None
            opened_at = (
                getattr(open_binding, "opened_at", None)
                if open_binding is not None
                else None
            )
            if isinstance(opened_at, datetime):
                opened_utc = (
                    opened_at
                    if opened_at.tzinfo is not None
                    else opened_at.replace(tzinfo=timezone.utc)
                )
                holding_seconds = max(
                    0,
                    int(
                        (
                            datetime.now(timezone.utc) - opened_utc
                        ).total_seconds()
                    ),
                )

            # trailing_armed: lifecycle 또는 peak gain >= activation
            life = read_exit_lifecycle(getattr(row, "raw_data", None))
            trailing_armed = (
                str(life.get("state") or "").upper() == STATE_TRAILING_ARMED
            )
            act = thresholds.trailing_activation_ratio
            if (
                not trailing_armed
                and entry > ZERO
                and highest > entry
            ):
                peak_gain = (highest - entry) / entry
                if act is None:
                    trailing_armed = True  # 레거시 any-profit
                elif peak_gain >= act:
                    trailing_armed = True

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
                    binding_id=binding_id,
                    holding_seconds=holding_seconds,
                    max_hold_seconds=thresholds.max_hold_seconds,
                    trailing_activation_ratio=(
                        thresholds.trailing_activation_ratio
                    ),
                    trailing_armed=trailing_armed,
                )
            )
        return positions, skipped

    def _load_kiwoom_strategy_owned_live_positions(
        self,
        *,
        threshold_by_user: dict[int | None, ExitThresholds],
    ) -> tuple[list[ManagedPosition], list[str]]:
        """KIWOOM LIVE — OPEN strategy binding 만. 수동 보유 제외.

        플래그 OFF면 빈 목록(+ flag_off skip). 시세는 KRX QuoteSnapshot (REST 금지).
        """

        settings = get_settings()
        if not bool(
            getattr(
                settings,
                "position_exit_monitor_live_kiwoom_enabled",
                False,
            )
        ):
            # 관측: OFF 로 unmanaged 인 이유를 남긴다 (주문 없음)
            return [], ["flag_off:LIVE_KIWOOM"]

        from stock_platform.broker.recovery_lock import (
            RecoveryAccountLockService,
        )
        from stock_platform.position.exit_monitor_live import (
            has_blocking_live_exit_sell,
            is_live_exit_eligible,
            resolve_kiwoom_live_price,
        )
        from stock_platform.risk_engine.strategy_owned_entities import (
            BINDING_STATUS_OPEN,
            OWNERSHIP_STRATEGY,
            StrategyPositionBindingEntity,
        )
        from stock_platform.trading.account_models import UserBrokerAccount

        lock = RecoveryAccountLockService(self._session)
        positions: list[ManagedPosition] = []
        skipped: list[str] = []
        threshold_by_uba: dict[int, ExitThresholds] = {}
        stale_seconds = float(
            getattr(
                settings,
                "autotrading_market_feed_stale_seconds",
                30.0,
            )
            or 30.0
        )

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

            # pending/inflight EXIT 있으면 로드 제외 (Upbit 패리티)
            blocking = has_blocking_live_exit_sell(
                self._session,
                user_broker_account_id=uba_id,
                symbol=symbol,
                snapshot_synchronized_at=None,
            )
            eligible, skip_reason = is_live_exit_eligible(
                quantity=qty,
                binding=binding,
                has_active_exit_order=blocking,
            )
            if not eligible:
                skipped.append(
                    f"TRAILING_EVALUATION_SKIPPED:{skip_reason}"
                    f":LIVE:{uba_id}/{symbol}"
                )
                continue

            current_price = resolve_kiwoom_live_price(
                self._session,
                symbol=symbol,
                stale_seconds=stale_seconds,
            )
            if current_price is None:
                skipped.append(
                    f"stale_or_missing:LIVE:{uba_id}/{symbol}"
                )
                continue

            uba = self._session.get(UserBrokerAccount, uba_id)
            owner_id = (
                int(uba.user_id)
                if uba is not None and getattr(uba, "user_id", None) is not None
                else None
            )
            if uba_id not in threshold_by_uba:
                threshold_by_uba[uba_id] = self._resolve_thresholds(
                    user_id=owner_id,
                    user_broker_account_id=uba_id,
                )
            thresholds = threshold_by_uba[uba_id]
            stop_loss_price, take_profit_price = _protective_prices(
                entry=entry,
                thresholds=thresholds,
                quantize="1",
            )
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
                    owner_user_id=owner_id,
                    environment="LIVE",
                    snapshot_synchronized_at=None,
                    binding_id=int(binding.binding_id),
                    trailing_armed=True,
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
