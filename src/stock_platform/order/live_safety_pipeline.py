"""STEP 8-7 — LIVE 주문 최종 검증 Pipeline.

Broker Adapter 호출 직전(및 OrderExecution submit)에서
User → Account → LIVE 승인 → Risk → Kill Switch → Amount → Qty
→ Duplicate → Market Time → Broker Health 순으로 검사한다.
하나라도 실패하면 주문 전송 금지.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from stock_platform.order.live_safety_audit import (
    BROKER_HEALTH_REJECT,
    DAILY_LIMIT_REJECT,
    DUPLICATE_ORDER_REJECT,
    LIVE_ORDER_SUBMITTED,
    LIVE_REJECTED,
    LOSS_LIMIT_REJECT,
    MARKET_TIME_REJECT,
    ORDER_AMOUNT_REJECT,
    ORDER_QTY_REJECT,
    emit_live_order_telegram,
    emit_live_safety_audit,
)
from stock_platform.order.entities import TradingOrderEntity
from stock_platform.order.live_open_order_exposure import (
    evaluate_live_open_order_exposure,
)
from stock_platform.risk_engine.kill_switch_guard import (
    KillSwitchUnavailableError,
    PersistentKillSwitchGuard,
)
from stock_platform.risk_engine.resolved_policy import (
    ResolvedRiskPolicyResolver,
)
from stock_platform.trading.account_models import UserBrokerAccount

ZERO = Decimal("0")
KST = ZoneInfo("Asia/Seoul")


@dataclass(frozen=True, slots=True)
class LiveSafetyDecision:
    allowed: bool
    reason_code: str
    audit_event_type: str | None = None
    detail: dict[str, Any] = field(default_factory=dict)


class LiveOrderSafetyPipeline:
    """LIVE 환경 전용. PAPER/MOCK 주문에는 호출하지 않는다."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def evaluate(
        self,
        *,
        user_id: int | None,
        user_broker_account_id: int,
        broker_code: str,
        exchange_code: str,
        symbol: str,
        side: str,
        quantity: Decimal,
        price: Decimal,
        strategy_id: str | None = None,
        run_id: str | None = None,
        actor: str = "LIVE_SAFETY",
        operator: str | None = None,
        environment: str = "LIVE",
        is_risk_reducing: bool = False,
        skip_market_hours: bool = False,
        emit_side_effects: bool = True,
        arm_token: str | None = None,
        reference_price: Decimal | None = None,
        require_arm: bool = True,
        order_type: str | None = None,
    ) -> LiveSafetyDecision:
        env = (environment or "LIVE").upper()
        if env != "LIVE":
            return LiveSafetyDecision(
                allowed=True,
                reason_code="NOT_LIVE",
                detail={"environment": env},
            )

        uba_id = int(user_broker_account_id)
        broker = (broker_code or "").strip().upper()
        exchange = (exchange_code or "").strip().upper()
        sym = (symbol or "").strip().upper()
        side_u = (side or "").strip().upper()
        qty = Decimal(str(quantity))
        px = Decimal(str(price))
        amount = (qty * px).quantize(Decimal("0.01"))
        base_detail: dict[str, Any] = {
            "user_id": user_id,
            "account_id": uba_id,
            "user_broker_account_id": uba_id,
            "broker_code": broker,
            "exchange_code": exchange,
            "symbol": sym,
            "side": side_u,
            "quantity": str(qty),
            "price": str(px),
            "amount": str(amount),
            "strategy_id": strategy_id,
            "run_id": run_id,
            "operator": operator or actor,
        }

        def _fail(
            reason: str,
            audit_type: str,
            extra: dict[str, Any] | None = None,
        ) -> LiveSafetyDecision:
            detail = {**base_detail, **(extra or {}), "reason_code": reason}
            if emit_side_effects:
                emit_live_safety_audit(
                    self._session,
                    event_type=audit_type,
                    actor=actor,
                    run_id=run_id,
                    user_id=user_id,
                    account_id=uba_id,
                    strategy_id=strategy_id,
                    symbol=sym,
                    detail=detail,
                    commit=False,
                )
                emit_live_order_telegram(
                    event_type=audit_type,
                    title=f"LIVE order rejected: {reason}",
                    message=(
                        f"{broker} {sym} {side_u} qty={qty} "
                        f"price={px} amount={amount} — {reason}"
                    ),
                    detail=detail,
                )
            return LiveSafetyDecision(
                allowed=False,
                reason_code=reason,
                audit_event_type=audit_type,
                detail=detail,
            )

        # 1) Account
        uba = self._session.get(UserBrokerAccount, uba_id)
        if uba is None:
            return _fail("ACCOUNT_NOT_FOUND", LIVE_REJECTED)
        if not bool(uba.is_active):
            return _fail("ACCOUNT_INACTIVE", LIVE_REJECTED)
        if user_id is not None and int(uba.user_id) != int(user_id):
            return _fail("ACCOUNT_USER_MISMATCH", LIVE_REJECTED)
        resolved_user_id = int(uba.user_id)
        base_detail["user_id"] = resolved_user_id

        # 2) LIVE 승인 (관리자 ON 필수)
        if not bool(getattr(uba, "live_order_enabled", False)):
            return _fail("LIVE_ORDER_DISABLED", LIVE_REJECTED)

        # 2b) STEP 8-8 — ARM + Token (만료 시 LIVE OFF)
        if require_arm:
            from stock_platform.order.live_safety_audit import (
                ARM_TOKEN_REJECT,
                LIVE_ARM_EXPIRED,
            )
            from stock_platform.trading.live_arm_service import LiveArmService

            arm_service = LiveArmService(self._session)
            # 원문 token이 있으면 challenge, 없으면 UBA ARM state만 검증
            ok_arm, arm_reason = arm_service.validate_arm_authorization(
                uba_id,
                arm_token=arm_token,
                require_token_challenge=False,
            )
            if not ok_arm:
                audit = (
                    LIVE_ARM_EXPIRED
                    if arm_reason == "LIVE_ARM_EXPIRED"
                    else ARM_TOKEN_REJECT
                )
                return _fail(arm_reason, audit)

        # 2b2) Unattended lease — ENTRY만 차단 (protective EXIT 유지)
        is_entry = (not is_risk_reducing) and side_u in {
            "BUY",
            "BID",
            "LONG",
        }
        if is_entry:
            try:
                from stock_platform.trading.live_unattended_authorization_service import (
                    LiveUnattendedAuthorizationService,
                )

                unatt = LiveUnattendedAuthorizationService(self._session)
                active = unatt.get_active(uba_id)
                if active is not None and not unatt.is_entry_authorized(
                    uba_id
                ):
                    return _fail(
                        "UNATTENDED_ENTRY_BLOCKED",
                        LIVE_REJECTED,
                        {"unattended_status": active.status_code},
                    )
            except Exception:  # noqa: BLE001
                pass

        # 2c) KIWOOM LIMIT — 로컬 KRX tick (shared market quote 불필요)
        order_type_u = str(order_type or "").strip().upper()
        if broker == "KIWOOM" and order_type_u == "LIMIT":
            if qty <= ZERO:
                return _fail("INVALID_ORDER_QUANTITY", ORDER_QTY_REJECT)
            if px <= ZERO:
                return _fail("INVALID_ORDER_PRICE", ORDER_AMOUNT_REJECT)
            from stock_platform.position.lot_rounding import (
                is_krx_tick_aligned,
                krx_tick_size,
            )

            if not is_krx_tick_aligned(px):
                return _fail(
                    "INVALID_KRX_TICK_SIZE",
                    ORDER_AMOUNT_REJECT,
                    {
                        "tick_size": str(krx_tick_size(px)),
                        "price": str(px),
                    },
                )

        policy = ResolvedRiskPolicyResolver(self._session).resolve(
            user_id=resolved_user_id,
            user_broker_account_id=uba_id,
        )
        base_detail["max_order_amount"] = str(policy.max_order_amount)
        base_detail["max_order_quantity"] = str(policy.max_order_quantity)
        base_detail["daily_order_limit"] = int(policy.daily_order_limit)
        base_detail["duplicate_window_seconds"] = int(
            policy.duplicate_order_window_seconds
        )
        base_detail["max_open_orders"] = int(policy.max_open_orders)
        base_detail["max_slippage_rate"] = str(policy.max_slippage_rate)

        # 3) Risk 플래그 (paused / buy-sell)
        if policy.account_paused:
            return _fail("ACCOUNT_PAUSED", LIVE_REJECTED)
        if side_u == "BUY" and (
            not policy.buy_enabled or policy.sell_only
        ):
            return _fail("BUY_DISABLED", LIVE_REJECTED)
        if side_u == "SELL" and not policy.sell_enabled:
            return _fail("SELL_DISABLED", LIVE_REJECTED)

        # 4) Kill Switch
        try:
            PersistentKillSwitchGuard(self._session).require_order_allowed(
                side=side_u,
                allow_sell=True,
                exchange_code=exchange,
                user_broker_account_id=uba_id,
            )
        except KillSwitchUnavailableError:
            return _fail("KILL_SWITCH_UNAVAILABLE", LOSS_LIMIT_REJECT)
        except PermissionError:
            return _fail("KILL_SWITCH_ACTIVE", LOSS_LIMIT_REJECT)

        if qty <= ZERO:
            return _fail("INVALID_ORDER_QUANTITY", ORDER_QTY_REJECT)

        # 서버 EXIT 분류 — 클라이언트 is_risk_reducing 무시
        from stock_platform.risk_engine.exit_risk import (
            classify_risk_reducing_exit,
        )

        verified_exit = False
        if side_u == "SELL":
            exit_clf = classify_risk_reducing_exit(
                self._session,
                side=side_u,
                symbol=sym,
                exchange_code=exchange,
                quantity=qty,
                user_broker_account_id=uba_id,
                paper_account_id=None,
                environment=env,
                broker_code=broker,
            )
            if not exit_clf.is_risk_reducing_exit:
                return _fail(
                    exit_clf.reason_code or "NO_POSITION_TO_SELL",
                    LIVE_REJECTED,
                    {
                        "held_quantity": str(exit_clf.held_quantity),
                        "pending_sell_quantity": str(
                            exit_clf.pending_sell_quantity
                        ),
                        "sellable_quantity": str(exit_clf.sellable_quantity),
                    },
                )
            verified_exit = True
            is_risk_reducing = True
            base_detail["exit_verified"] = True
            base_detail["held_quantity"] = str(exit_clf.held_quantity)
            base_detail["pending_sell_quantity"] = str(
                exit_clf.pending_sell_quantity
            )
            base_detail["sellable_quantity"] = str(exit_clf.sellable_quantity)

        # UPBIT 최소 노셔널 — EXIT도 스킵하지 않음 (확정 가능한 LIMIT만)
        from stock_platform.broker.upbit.rules import (
            REASON_UPBIT_MIN_NOTIONAL_NOT_MET,
            UPBIT_MIN_NOTIONAL_KRW,
            evaluate_upbit_min_notional,
        )

        min_notional_reason = evaluate_upbit_min_notional(
            broker_code=broker,
            environment=env,
            side=side_u,
            order_type=str(order_type or "LIMIT"),
            quantity=qty,
            price=px if px > ZERO else None,
        )
        if min_notional_reason:
            return _fail(
                REASON_UPBIT_MIN_NOTIONAL_NOT_MET,
                LIVE_REJECTED,
                {
                    "minimum_notional": str(UPBIT_MIN_NOTIONAL_KRW),
                    "reason_code": REASON_UPBIT_MIN_NOTIONAL_NOT_MET,
                },
            )

        # 5) Order Amount — ENTRY 전용 (검증된 EXIT 스킵)
        if (not verified_exit) and amount > policy.max_order_amount:
            return _fail(
                "ORDER_AMOUNT_EXCEEDED",
                ORDER_AMOUNT_REJECT,
                {
                    "limit": str(policy.max_order_amount),
                    "order_amount": str(amount),
                },
            )

        # 6) Order Quantity — EXIT에도 안전 캡 유지
        if qty > policy.max_order_quantity:
            return _fail(
                "ORDER_QTY_EXCEEDED",
                ORDER_QTY_REJECT,
                {
                    "limit": str(policy.max_order_quantity),
                    "quantity": str(qty),
                },
            )

        # 7) Daily order count — ENTRY 전용
        daily_count = self._count_orders_today(uba_id)
        base_detail["daily_order_count"] = daily_count
        if (not verified_exit) and daily_count >= int(policy.daily_order_limit):
            return _fail(
                "DAILY_ORDER_LIMIT_EXCEEDED",
                DAILY_LIMIT_REJECT,
                {
                    "limit": int(policy.daily_order_limit),
                    "count": daily_count,
                },
            )

        # 8) Daily loss — ENTRY BLOCK (엔진은 SELL WARNING, 파이프라인은 EXIT 스킵)
        loss_hit = self._daily_loss_breached(
            user_broker_account_id=uba_id,
            limit=policy.daily_max_loss_amount,
        )
        if (not verified_exit) and loss_hit:
            return _fail(
                "DAILY_LOSS_LIMIT_REACHED",
                LOSS_LIMIT_REJECT,
                {"limit": str(policy.daily_max_loss_amount)},
            )

        # 9) Duplicate window — EXIT에도 유지 (idempotency)
        window = int(policy.duplicate_order_window_seconds)
        if window > 0 and self._is_duplicate(
            user_broker_account_id=uba_id,
            symbol=sym,
            side=side_u,
            price=px,
            quantity=qty,
            window_seconds=window,
        ):
            return _fail(
                "DUPLICATE_ORDER",
                DUPLICATE_ORDER_REJECT,
                {"window_seconds": window},
            )

        # 9b) STEP 8-8 — max open orders (ENTRY 전용; EXIT는 pending SELL로 제한)
        from stock_platform.order.live_safety_audit import (
            ANOMALY_ORDER_RATE,
            LOOP_DETECTED,
            OPEN_ORDER_LIMIT,
            SLIPPAGE_REJECT,
        )

        if broker == "UPBIT" and not verified_exit:
            # UPBIT ENTRY: local + unmapped remote. 상태 불명이면 fail-closed.
            exposure = evaluate_live_open_order_exposure(
                self._session,
                uba_id=uba_id,
                broker_code=broker,
                environment=env,
            )
            base_detail.update(exposure.as_detail())
            if not exposure.remote_state_ok:
                return _fail(
                    str(exposure.reason_code or "REMOTE_OPEN_CHECK_FAILED"),
                    OPEN_ORDER_LIMIT,
                    {
                        "limit": int(policy.max_open_orders),
                        "count": exposure.canonical_count,
                        "remote_open_state": exposure.remote_state,
                    },
                )
            open_count = int(exposure.canonical_count)
        else:
            open_count = self._count_open_orders(uba_id)
            base_detail["open_order_count"] = open_count
        if (not verified_exit) and open_count >= int(policy.max_open_orders):
            return _fail(
                "OPEN_ORDER_LIMIT_EXCEEDED",
                OPEN_ORDER_LIMIT,
                {
                    "limit": int(policy.max_open_orders),
                    "count": open_count,
                },
            )

        # 9c) Slippage (reference_price 있을 때만)
        if reference_price is not None and reference_price > ZERO:
            slip = self._slippage_ratio(
                side=side_u,
                order_price=px,
                reference_price=Decimal(str(reference_price)),
            )
            limit = Decimal(str(policy.max_slippage_rate))
            base_detail["slippage_ratio"] = str(slip)
            if slip > limit:
                return _fail(
                    "SLIPPAGE_EXCEEDED",
                    SLIPPAGE_REJECT,
                    {
                        "slippage_ratio": str(slip),
                        "limit": str(limit),
                        "reference_price": str(reference_price),
                    },
                )

        # 9d) 1분 주문 폭주 — ENTRY 스팸 방지 (검증된 EXIT 스킵)
        per_min = self._count_orders_since(
            uba_id, seconds=60
        )
        if (not verified_exit) and per_min >= int(policy.anomaly_orders_per_minute):
            return _fail(
                "ANOMALY_ORDER_RATE",
                ANOMALY_ORDER_RATE,
                {
                    "count_1m": per_min,
                    "limit": int(policy.anomaly_orders_per_minute),
                },
            )

        # 9e) BUY/SELL loop 감지 — ENTRY 전용
        loop_window = int(policy.loop_detect_window_seconds)
        if (
            (not verified_exit)
            and loop_window > 0
            and self._detect_flip_loop(
                user_broker_account_id=uba_id,
                symbol=sym,
                next_side=side_u,
                window_seconds=loop_window,
            )
        ):
            return _fail(
                "ORDER_LOOP_DETECTED",
                LOOP_DETECTED,
                {"window_seconds": loop_window},
            )

        # 10) Market time (주식/KRX만 — Paper/Mock 제외는 호출측 책임)
        if (
            not skip_market_hours
            and exchange in {"KRX", "KOSPI", "KOSDAQ"}
            and broker == "KIWOOM"
        ):
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
                    is_risk_reducing=is_risk_reducing,
                )
            except ValueError as exc:
                return _fail(
                    "MARKET_CLOSED",
                    MARKET_TIME_REJECT,
                    {"error": str(exc)[:200]},
                )
            except Exception as exc:  # noqa: BLE001
                return _fail(
                    "MARKET_TIME_UNAVAILABLE",
                    MARKET_TIME_REJECT,
                    {"error": f"{type(exc).__name__}: {exc}"[:200]},
                )

        # 11) Broker Health
        try:
            from stock_platform.operation.live_health_gate import (
                LiveHealthBlockedError,
                assert_live_orders_allowed,
            )

            assert_live_orders_allowed(self._session)
        except LiveHealthBlockedError as exc:
            return _fail(
                "BROKER_HEALTH_BLOCKED",
                BROKER_HEALTH_REJECT,
                {"error": str(exc)[:200]},
            )
        except Exception as exc:  # noqa: BLE001
            return _fail(
                "BROKER_HEALTH_UNAVAILABLE",
                BROKER_HEALTH_REJECT,
                {"error": f"{type(exc).__name__}: {exc}"[:200]},
            )

        # Env live flags (추가 Fail Closed)
        try:
            from stock_platform.broker.live_config_gate import (
                evaluate_live_flag_consistency,
            )

            cfg = evaluate_live_flag_consistency(
                broker_code=broker,
                session=self._session,
                user_broker_account_id=uba_id,
            )
            if cfg.code in {
                "LIVE_FLAG_MISMATCH_KIWOOM",
                "GLOBAL_LIVE_OFF",
                "UPBIT_LIVE_OFF",
                "UPBIT_MOCK_LIVE_CONFLICT",
            }:
                return _fail(cfg.code, LIVE_REJECTED)
            if cfg.code == "LIVE_MOCK_CONFLICT" and broker == "KIWOOM":
                from stock_platform.broker.kiwoom.execution_env import (
                    kiwoom_global_mock_blocks_live_execution,
                )

                if kiwoom_global_mock_blocks_live_execution(
                    self._session,
                    user_broker_account_id=uba_id,
                ):
                    return _fail(cfg.code, LIVE_REJECTED)
            elif cfg.code == "LIVE_MOCK_CONFLICT" and broker != "UPBIT":
                return _fail(cfg.code, LIVE_REJECTED)
            if broker == "KIWOOM" and cfg.code == "KIWOOM_LIVE_OFF":
                return _fail("KIWOOM_LIVE_OFF", LIVE_REJECTED)
        except Exception as exc:  # noqa: BLE001
            return _fail(
                "LIVE_FLAG_CHECK_FAILED",
                LIVE_REJECTED,
                {"error": f"{type(exc).__name__}"},
            )

        if emit_side_effects:
            # 성공 경로 — submit 직전 알림은 호출측에서 ORDER_SUBMITTED로도 보냄
            pass

        return LiveSafetyDecision(
            allowed=True,
            reason_code="LIVE_SAFETY_PASS",
            detail=base_detail,
        )

    def notify_submitted(
        self,
        *,
        decision_detail: dict[str, Any],
        order_id: int | None,
        client_order_id: str | None,
        run_id: str | None,
        actor: str,
        user_id: int | None,
        account_id: int | None,
        strategy_id: str | None,
        symbol: str | None,
    ) -> None:
        detail = {
            **decision_detail,
            "order_id": order_id,
            "client_order_id": client_order_id,
        }
        emit_live_safety_audit(
            self._session,
            event_type=LIVE_ORDER_SUBMITTED,
            actor=actor,
            run_id=run_id,
            user_id=user_id,
            account_id=account_id,
            strategy_id=strategy_id,
            symbol=symbol,
            order_id=order_id,
            client_order_id=client_order_id,
            detail=detail,
            commit=False,
        )
        emit_live_order_telegram(
            event_type=LIVE_ORDER_SUBMITTED,
            title="LIVE order submitted",
            message=(
                f"order={order_id} account={account_id} "
                f"symbol={symbol} qty={detail.get('quantity')} "
                f"price={detail.get('price')} amount={detail.get('amount')}"
            ),
            detail=detail,
        )

    def _count_orders_today(self, uba_id: int) -> int:
        # 미전송 내부 폐기(UNSUBMITTED_LIVE_RETIRED)는 Risk 일일 건수에서 제외
        from stock_platform.order.daily_risk_order_count import (
            count_daily_risk_orders,
        )

        return count_daily_risk_orders(self._session, int(uba_id))

    def _is_duplicate(
        self,
        *,
        user_broker_account_id: int,
        symbol: str,
        side: str,
        price: Decimal,
        quantity: Decimal,
        window_seconds: int,
    ) -> bool:
        since = datetime.now(timezone.utc) - timedelta(seconds=window_seconds)
        row = self._session.scalar(
            select(TradingOrderEntity)
            .where(
                TradingOrderEntity.user_broker_account_id
                == user_broker_account_id,
                TradingOrderEntity.symbol == symbol.upper(),
                TradingOrderEntity.side_code == side.upper(),
                TradingOrderEntity.order_quantity == quantity,
                TradingOrderEntity.order_price == price,
                TradingOrderEntity.created_at >= since,
            )
            .order_by(TradingOrderEntity.order_id.desc())
            .limit(1)
        )
        return row is not None

    def _count_open_orders(self, uba_id: int) -> int:
        open_statuses = (
            "CREATED",
            "PENDING",
            "SENT",
            "ACCEPTED",
            "PARTIALLY_FILLED",
            "CANCEL_REQUESTED",
            "REPLACE_REQUESTED",
        )
        count = self._session.scalar(
            select(func.count())
            .select_from(TradingOrderEntity)
            .where(
                TradingOrderEntity.user_broker_account_id == uba_id,
                TradingOrderEntity.status_code.in_(open_statuses),
            )
        )
        return int(count or 0)

    def _count_orders_since(self, uba_id: int, *, seconds: int) -> int:
        since = datetime.now(timezone.utc) - timedelta(seconds=seconds)
        count = self._session.scalar(
            select(func.count())
            .select_from(TradingOrderEntity)
            .where(
                TradingOrderEntity.user_broker_account_id == uba_id,
                TradingOrderEntity.created_at >= since,
            )
        )
        return int(count or 0)

    @staticmethod
    def _slippage_ratio(
        *,
        side: str,
        order_price: Decimal,
        reference_price: Decimal,
    ) -> Decimal:
        if reference_price <= ZERO:
            return ZERO
        if side.upper() == "BUY":
            # 매수: 주문가 > 현재가면 불리
            if order_price <= reference_price:
                return ZERO
            return (
                (order_price - reference_price) / reference_price
            ).quantize(Decimal("0.000001"))
        # 매도: 주문가 < 현재가면 불리
        if order_price >= reference_price:
            return ZERO
        return (
            (reference_price - order_price) / reference_price
        ).quantize(Decimal("0.000001"))

    def _detect_flip_loop(
        self,
        *,
        user_broker_account_id: int,
        symbol: str,
        next_side: str,
        window_seconds: int,
    ) -> bool:
        """동일 종목 BUY↔SELL 교차 반복(최근 3건+신규) 감지."""

        since = datetime.now(timezone.utc) - timedelta(seconds=window_seconds)
        rows = list(
            self._session.scalars(
                select(TradingOrderEntity)
                .where(
                    TradingOrderEntity.user_broker_account_id
                    == user_broker_account_id,
                    TradingOrderEntity.symbol == symbol.upper(),
                    TradingOrderEntity.created_at >= since,
                )
                .order_by(TradingOrderEntity.created_at.desc())
                .limit(3)
            )
        )
        if len(rows) < 3:
            return False
        sides = [next_side.upper()] + [r.side_code.upper() for r in rows]
        # 신규 포함 4개 중 교차: B S B S 또는 S B S B
        pattern = sides[:4]
        flips = sum(
            1
            for i in range(1, len(pattern))
            if pattern[i] != pattern[i - 1]
        )
        return flips >= 3 and len(set(pattern)) == 2

    def _daily_loss_breached(
        self,
        *,
        user_broker_account_id: int,
        limit: Decimal,
    ) -> bool:
        """account_daily_loss 기준으로 일손실 한도 도달 여부."""

        if limit <= ZERO:
            return False
        try:
            from stock_platform.risk_engine.daily_loss_entities import (
                AccountDailyLossEntity,
            )

            today = datetime.now(KST).date()
            row = self._session.scalar(
                select(AccountDailyLossEntity).where(
                    AccountDailyLossEntity.user_broker_account_id
                    == user_broker_account_id,
                    AccountDailyLossEntity.trading_date == today,
                )
            )
            if row is None:
                return False
            if str(row.status_code).upper() in {
                "BREACHED",
                "LIMIT_REACHED",
                "KILL",
            }:
                return True
            current_loss = Decimal(str(row.current_loss_amount or 0))
            return current_loss >= limit
        except Exception:  # noqa: BLE001
            return False
