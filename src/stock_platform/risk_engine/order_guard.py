"""STEP 8-2 — ResolvedRiskPolicy 기반 주문 가드."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from stock_platform.order.entities import TradingOrderEntity
from stock_platform.risk_engine.account_state_service import (
    RiskAccountStateService,
)
from stock_platform.risk_engine.integration_models import (
    RiskCheckedOrderResult,
)
from stock_platform.risk_engine.models import (
    RiskDecisionLevel,
    RiskEvaluationResult,
    RiskOrderRequest,
    RiskOrderSide,
)
from stock_platform.risk_engine.position_limit_models import (
    PositionLimitPolicy,
)
from stock_platform.risk_engine.position_limit_rule import (
    DatabasePositionLimitRule,
)
from stock_platform.risk_engine.resolved_policy import (
    ResolvedRiskPolicyResolver,
)
from stock_platform.risk_engine.runtime import realtime_risk_engine
from stock_platform.trading.account_models import PaperPosition


ZERO = Decimal("0")


class DatabaseBackedRiskOrderGuard:
    def __init__(
        self,
        session: Session,
        *,
        broker_code: str = "KIWOOM",
    ) -> None:
        self._session = session
        self._broker_code = broker_code
        self._account_state_service = RiskAccountStateService(session)
        self._resolver = ResolvedRiskPolicyResolver(session)

    def check(
        self,
        *,
        account_number: str,
        account_id: int,
        exchange_code: str,
        symbol: str,
        side: str,
        quantity: Decimal,
        price: Decimal,
        user_id: int | None = None,
        user_broker_account_id: int | None = None,
        order_source: str = "MANUAL",
        is_risk_reducing: bool = False,
        # STEP 8-5-13 — PAPER는 paper_stock_follow_krx_calendar로 게이트
        environment: str = "LIVE",
    ) -> RiskCheckedOrderResult:
        from stock_platform.risk_engine.models import RiskEvaluationResult
        from stock_platform.trading.account_identity import (
            AccountIdentityErrorCode,
        )

        environment_upper = (environment or "LIVE").upper()
        now = datetime.now(timezone.utc)

        def _reject(code: str) -> RiskCheckedOrderResult:
            return RiskCheckedOrderResult(
                allowed=False,
                blocked_reason=code,
                evaluation=RiskEvaluationResult(
                    decision=RiskDecisionLevel.BLOCK,
                    allowed=False,
                    evaluated_at=now,
                    order_amount=quantity * price,
                    results=[],
                ),
            )

        # STEP 8-5-18 — LIVE는 UBA, Paper는 paper_account_id 필수
        if environment_upper == "LIVE":
            if user_broker_account_id is None:
                code = (
                    AccountIdentityErrorCode.LEGACY_ACCOUNT_NUMBER_ONLY.value
                    if (account_number or "").strip()
                    else AccountIdentityErrorCode.UBA_REQUIRED.value
                )
                return _reject(code)
        else:
            if account_id is None or int(account_id) <= 0:
                return _reject(
                    AccountIdentityErrorCode.PAPER_ACCOUNT_REQUIRED.value
                )

        resolved = self._resolver.resolve(
            user_id=user_id,
            user_broker_account_id=user_broker_account_id,
        )
        policy = resolved.to_engine_policy()

        # LIVE: UBA ACTIVE Snapshot / Paper: 레거시 load + PaperPosition 보강
        if environment_upper == "LIVE":
            try:
                account_state = self._account_state_service.load_by_uba(
                    user_broker_account_id=int(user_broker_account_id),
                    exchange_code=exchange_code,
                    symbol=symbol,
                )
            except LookupError:
                from stock_platform.risk_engine.models import RiskAccountState

                account_state = RiskAccountState(
                    cash_balance=ZERO,
                    total_asset_value=ZERO,
                    invested_amount=ZERO,
                    daily_realized_profit_loss=ZERO,
                    daily_unrealized_profit_loss=ZERO,
                    open_position_count=0,
                    symbol_position_quantity=ZERO,
                )
        else:
            try:
                account_state = self._account_state_service.load_by_paper_account(
                    paper_account_id=int(account_id),
                    exchange_code=exchange_code,
                    symbol=symbol,
                )
            except LookupError:
                from stock_platform.risk_engine.models import RiskAccountState

                account_state = RiskAccountState(
                    cash_balance=ZERO,
                    total_asset_value=ZERO,
                    invested_amount=ZERO,
                    daily_realized_profit_loss=ZERO,
                    daily_unrealized_profit_loss=ZERO,
                    open_position_count=0,
                    symbol_position_quantity=ZERO,
                )

        # Paper 계좌면 포지션 수를 PaperPosition 기준으로 보강
        paper_open = self._paper_open_position_count(account_id)
        if paper_open is not None:
            from stock_platform.risk_engine.models import RiskAccountState

            account_state = RiskAccountState(
                cash_balance=account_state.cash_balance,
                total_asset_value=account_state.total_asset_value,
                invested_amount=account_state.invested_amount,
                daily_realized_profit_loss=(
                    account_state.daily_realized_profit_loss
                ),
                daily_unrealized_profit_loss=(
                    account_state.daily_unrealized_profit_loss
                ),
                open_position_count=max(
                    account_state.open_position_count, paper_open
                ),
                symbol_position_quantity=(
                    self._paper_symbol_qty(
                        account_id, exchange_code, symbol
                    )
                    or account_state.symbol_position_quantity
                ),
            )

        order = RiskOrderRequest(
            exchange_code=exchange_code,
            symbol=symbol,
            side=RiskOrderSide(side.upper()),
            quantity=quantity,
            price=price,
            account_id=account_id,
            requested_at=datetime.now(timezone.utc),
            order_source=order_source.upper(),
            is_risk_reducing=is_risk_reducing,
            daily_ordered_amount=self._daily_ordered_amount(
                account_id=account_id,
                user_broker_account_id=user_broker_account_id,
            ),
            symbol_invested_amount=self._symbol_invested_amount(
                account_id=account_id,
                exchange_code=exchange_code,
                symbol=symbol,
            ),
        )

        # STEP 8-5-7/8-5-13 — KRX LIVE: Calendar Fail Closed (Upbit 제외)
        # PAPER는 paper_stock_follow_krx_calendar 설정으로 게이트한다
        # (LIVE는 설정과 무관하게 항상 Fail Closed).
        # LIVE_SHADOW는 실주문 전송 없이 Intent만 남기므로 장외에도 허용.
        from stock_platform.order.live_shadow import is_live_shadow_mode

        environment_upper = (environment or "LIVE").upper()
        shadow_mode = is_live_shadow_mode()
        calendar_gated = (
            not shadow_mode
            and self._broker_code.upper() == "KIWOOM"
            and exchange_code.upper() == "KRX"
            and (
                environment_upper == "LIVE"
                or self._paper_follows_krx_calendar()
            )
        )
        calendar_block = None
        if calendar_gated and not is_risk_reducing:
            try:
                from stock_platform.operation.calendar_repository import (
                    TradingCalendarRepository,
                )
                from stock_platform.operation.calendar_service import (
                    TradingCalendarService,
                )

                TradingCalendarService(
                    TradingCalendarRepository(self._session)
                ).require_live_order_session(
                    exchange_code="KRX",
                    moment=order.requested_at,
                    is_risk_reducing=is_risk_reducing,
                )
            except ValueError as exc:
                from stock_platform.risk_engine.models import RiskRuleResult

                calendar_block = RiskRuleResult(
                    rule_code="KRX_CALENDAR",
                    level=RiskDecisionLevel.BLOCK,
                    message=str(exc),
                )

        evaluation = realtime_risk_engine.evaluate(
            order=order,
            account=account_state,
            policy=policy,
        )

        position_result = DatabasePositionLimitRule(
            self._session,
            broker_code=self._broker_code,
            user_broker_account_id=user_broker_account_id,
            paper_account_id=(
                int(account_id) if environment_upper != "LIVE" else None
            ),
            default_policy=PositionLimitPolicy(),
        ).evaluate(
            order=order,
            account=account_state,
        )

        combined_results = [
            *evaluation.results,
            position_result,
        ]
        if calendar_block is not None:
            combined_results.insert(0, calendar_block)

        # STEP 8-5-13 — 평가 도중 Calendar Revision이 바뀌었는지 재확인
        # (TradingTimeRule 평가 시점과 송신 직전 사이의 경합 방지).
        revision_block = self._check_revision_race(
            evaluated_results=evaluation.results,
            gated=calendar_gated,
            exchange_code=exchange_code,
        )
        if revision_block is not None:
            combined_results.insert(0, revision_block)

        blocked = [
            item.message
            for item in combined_results
            if item.level == RiskDecisionLevel.BLOCK
        ]

        evaluation = RiskEvaluationResult(
            decision=(
                RiskDecisionLevel.BLOCK
                if blocked
                else evaluation.decision
            ),
            allowed=not bool(blocked),
            evaluated_at=evaluation.evaluated_at,
            order_amount=evaluation.order_amount,
            results=combined_results,
        )

        return RiskCheckedOrderResult(
            allowed=evaluation.allowed,
            blocked_reason=(
                "; ".join(blocked) if blocked else None
            ),
            evaluation=evaluation,
        )

    @staticmethod
    def _paper_follows_krx_calendar() -> bool:
        try:
            from stock_platform.common.settings import get_settings

            return bool(get_settings().paper_stock_follow_krx_calendar)
        except Exception:  # noqa: BLE001
            return True

    def _check_revision_race(
        self,
        *,
        evaluated_results,
        gated: bool,
        exchange_code: str,
    ):
        """TradingTimeRule 평가에 쓰인 Revision과 현재 DB Revision 비교.

        평가 시작~송신 직전 사이에 Calendar가 변경되면 즉시 재평가하지
        않고 안전하게 차단한다 (다음 재시도에서 최신 Revision으로 재평가).
        """

        if not gated:
            return None
        try:
            trading_time_result = next(
                (
                    r
                    for r in evaluated_results
                    if r.rule_code == "TRADING_TIME"
                ),
                None,
            )
            if trading_time_result is None:
                return None
            used_revision = (trading_time_result.detail or {}).get(
                "revision"
            )
            if used_revision is None:
                return None

            from stock_platform.operation.calendar_constants import (
                KRX_TIMEZONE,
            )
            from stock_platform.operation.calendar_repository import (
                TradingCalendarRepository,
            )

            calendar_date = datetime.now(
                ZoneInfo(KRX_TIMEZONE)
            ).date()
            current = TradingCalendarRepository(self._session).get_day(
                exchange_code=exchange_code.upper(),
                calendar_date=calendar_date,
            )
            current_revision = (
                int(getattr(current, "revision", 0) or 0)
                if current is not None
                else 0
            )
            if int(used_revision) == current_revision:
                return None

            try:
                from stock_platform.operation.session_timeline import (
                    invalidate_timeline_cache,
                )

                invalidate_timeline_cache(
                    exchange_code=exchange_code.upper()
                )
            except Exception:  # noqa: BLE001
                pass

            from stock_platform.risk_engine.models import RiskRuleResult

            return RiskRuleResult(
                rule_code="CALENDAR_REVISION_CHANGED",
                level=RiskDecisionLevel.BLOCK,
                message=(
                    "KRX calendar revision changed during risk "
                    "evaluation; retry required"
                ),
                detail={
                    "evaluated_revision": used_revision,
                    "current_revision": current_revision,
                },
            )
        except Exception:  # noqa: BLE001
            return None

    def _paper_open_position_count(
        self, account_id: int
    ) -> int | None:
        count = self._session.scalar(
            select(func.count())
            .select_from(PaperPosition)
            .where(
                PaperPosition.account_id == account_id,
                PaperPosition.quantity > ZERO,
            )
        )
        if count is None:
            return None
        return int(count)

    def _paper_symbol_qty(
        self,
        account_id: int,
        exchange_code: str,
        symbol: str,
    ) -> Decimal | None:
        qty = self._session.scalar(
            select(PaperPosition.quantity).where(
                PaperPosition.account_id == account_id,
                PaperPosition.exchange_code == exchange_code.upper(),
                PaperPosition.symbol == symbol.upper(),
            )
        )
        if qty is None:
            return None
        return Decimal(str(qty))

    def _daily_ordered_amount(
        self,
        *,
        account_id: int,
        user_broker_account_id: int | None,
    ) -> Decimal:
        """당일 BUY 주문 금액 합 (CREATED~FILLED 계열)."""

        today = datetime.now(timezone.utc).date()
        stmt = select(
            func.coalesce(
                func.sum(
                    TradingOrderEntity.order_quantity
                    * func.coalesce(
                        TradingOrderEntity.order_price, ZERO
                    )
                ),
                ZERO,
            )
        ).where(
            TradingOrderEntity.side_code == "BUY",
            TradingOrderEntity.status_code.notin_(
                ["REJECTED", "FAILED", "CANCELLED"]
            ),
            func.date(TradingOrderEntity.created_at) == today,
        )
        if user_broker_account_id is not None:
            stmt = stmt.where(
                TradingOrderEntity.user_broker_account_id
                == user_broker_account_id
            )
        else:
            stmt = stmt.where(
                TradingOrderEntity.account_id == account_id
            )
        value = self._session.scalar(stmt)
        return Decimal(str(value or 0))

    def _symbol_invested_amount(
        self,
        *,
        account_id: int,
        exchange_code: str,
        symbol: str,
    ) -> Decimal:
        row = self._session.scalar(
            select(PaperPosition).where(
                PaperPosition.account_id == account_id,
                PaperPosition.exchange_code == exchange_code.upper(),
                PaperPosition.symbol == symbol.upper(),
            )
        )
        if row is None:
            return ZERO
        return (
            Decimal(str(row.quantity))
            * Decimal(str(row.average_entry_price))
        )
