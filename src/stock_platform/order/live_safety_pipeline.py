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
        price: Decimal | None,
        strategy_id: str | None = None,
        strategy_deployment_id: int | None = None,
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
        order_amount: Decimal | None = None,
        order_source: str | None = None,
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
        order_type_u = str(order_type or "").strip().upper()
        is_market = order_type_u == "MARKET"
        is_market_buy = is_market and side_u == "BUY"
        is_market_sell = is_market and side_u == "SELL"

        try:
            qty = Decimal(str(quantity))
        except Exception:  # noqa: BLE001 — 수량 파싱 실패는 domain reject
            return LiveSafetyDecision(
                allowed=False,
                reason_code="INVALID_ORDER_QUANTITY",
                audit_event_type=ORDER_QTY_REJECT,
                detail={"quantity": str(quantity)},
            )
        if qty <= ZERO:
            return LiveSafetyDecision(
                allowed=False,
                reason_code="INVALID_ORDER_QUANTITY",
                audit_event_type=ORDER_QTY_REJECT,
                detail={"quantity": str(qty)},
            )

        # LIMIT: price 필수 / MARKET BUY: quote(order_amount|KRW price) /
        # MARKET SELL: price=None 정상 (체결가 사전 확정 불가) — Decimal(str(None)) 금지
        px: Decimal | None = None
        if price is not None:
            try:
                px = Decimal(str(price))
            except Exception:  # noqa: BLE001
                return LiveSafetyDecision(
                    allowed=False,
                    reason_code="INVALID_ORDER_PRICE",
                    audit_event_type=ORDER_AMOUNT_REJECT,
                    detail={"price": str(price)},
                )

        amount: Decimal | None = None
        amount_basis = "NONE"
        if (
            is_market_buy
            and order_amount is not None
            and Decimal(str(order_amount)) > ZERO
        ):
            # UPBIT MARKET BUY: 노셔널은 KRW order_amount (qty*ref 아님)
            amount = Decimal(str(order_amount)).quantize(Decimal("0.01"))
            amount_basis = "MARKET_BUY_QUOTE"
            if px is None:
                px = amount  # 상세/감사용 KRW notional
        elif is_market_buy and px is not None and px > ZERO:
            # resolve_size가 order_price=KRW notional로 넘긴 경우
            amount = px.quantize(Decimal("0.01"))
            amount_basis = "MARKET_BUY_QUOTE"
        elif is_market_sell:
            ref = reference_price
            if ref is not None:
                try:
                    ref_d = Decimal(str(ref))
                except Exception:  # noqa: BLE001
                    ref_d = ZERO
                if ref_d > ZERO:
                    # 추정 노셔널만 (주문가 대체 아님, 0 위장 금지)
                    amount = (qty * ref_d).quantize(Decimal("0.01"))
                    amount_basis = "MARKET_SELL_REFERENCE_ESTIMATE"
            # price/ref 없으면 amount=None — qty·잔고·KILL/ARM 게이트로 fail-closed
        elif not is_market:
            if px is None or px <= ZERO:
                return LiveSafetyDecision(
                    allowed=False,
                    reason_code="LIMIT_PRICE_REQUIRED",
                    audit_event_type=ORDER_AMOUNT_REJECT,
                    detail={
                        "order_type": order_type_u or "LIMIT",
                        "side": side_u,
                        "price": None if price is None else str(price),
                    },
                )
            amount = (qty * px).quantize(Decimal("0.01"))
            amount_basis = "LIMIT_PRICE"
        else:
            # MARKET 이지만 BUY/SELL 분류 밖 — price 필수
            if px is None or px <= ZERO:
                return LiveSafetyDecision(
                    allowed=False,
                    reason_code="INVALID_ORDER_PRICE",
                    audit_event_type=ORDER_AMOUNT_REJECT,
                    detail={"order_type": order_type_u, "side": side_u},
                )
            amount = (qty * px).quantize(Decimal("0.01"))
            amount_basis = "ORDER_PRICE"

        base_detail: dict[str, Any] = {
            "user_id": user_id,
            "account_id": uba_id,
            "user_broker_account_id": uba_id,
            "broker_code": broker,
            "exchange_code": exchange,
            "symbol": sym,
            "side": side_u,
            "quantity": str(qty),
            "price": None if px is None else str(px),
            "amount": None if amount is None else str(amount),
            "amount_basis": amount_basis,
            "order_type": order_type_u or None,
            "strategy_id": strategy_id,
            "strategy_deployment_id": strategy_deployment_id,
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
                        f"price={px if px is not None else 'N/A'} "
                        f"amount={amount if amount is not None else 'N/A'} "
                        f"— {reason}"
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
            # 기존 OPEN AUTO protective exit quote stale → 신규 ENTRY 차단
            if broker == "UPBIT":
                try:
                    from stock_platform.trading.autotrading_master_gate import (
                        _evaluate_auto_exit_quote_freshness,
                    )

                    exit_q = _evaluate_auto_exit_quote_freshness(
                        self._session,
                        user_broker_account_id=uba_id,
                    )
                    if exit_q.get("applicable") and not exit_q.get("ok"):
                        return _fail(
                            "AUTO_EXIT_QUOTE_STALE",
                            LIVE_REJECTED,
                            {
                                "stale_symbols": exit_q.get(
                                    "stale_symbols"
                                ),
                                "policy": exit_q.get("policy"),
                            },
                        )
                except Exception:  # noqa: BLE001
                    pass

        # 2c) KIWOOM LIMIT — 로컬 KRX tick (shared market quote 불필요)
        if broker == "KIWOOM" and order_type_u == "LIMIT":
            if qty <= ZERO:
                return _fail("INVALID_ORDER_QUANTITY", ORDER_QTY_REJECT)
            if px is None or px <= ZERO:
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
            price=px if (px is not None and px > ZERO) else None,
            market_krw_amount=(
                amount
                if order_type_u == "MARKET" and side_u == "BUY"
                else None
            ),
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
        # MARKET SELL amount=None(추정 불가)이면 qty/잔고 게이트로 충분 — 0 위장 금지
        if (
            (not verified_exit)
            and amount is not None
            and amount > policy.max_order_amount
        ):
            return _fail(
                "ORDER_AMOUNT_EXCEEDED",
                ORDER_AMOUNT_REJECT,
                {
                    "limit": str(policy.max_order_amount),
                    "order_amount": str(amount),
                },
            )

        # 6) Order Quantity
        # ENTRY: hard reject. verified EXIT: max_order_quantity로 clamp
        # (부분 청산 후 remaining은 Exit Intent / 다음 tick이 처리)
        if qty > policy.max_order_quantity:
            if verified_exit:
                base_detail["requested_quantity"] = str(qty)
                base_detail["quantity_clamped_to_max_order"] = True
                base_detail["max_order_quantity_limit"] = str(
                    policy.max_order_quantity
                )
                qty = Decimal(str(policy.max_order_quantity))
                base_detail["quantity"] = str(qty)
                base_detail["effective_quantity"] = str(qty)
                # clamp 후 sellable 재확인 (pending 반영된 분류 기준)
                if qty > exit_clf.sellable_quantity:
                    return _fail(
                        "SELL_QUANTITY",
                        LIVE_REJECTED,
                        {
                            "held_quantity": str(exit_clf.held_quantity),
                            "pending_sell_quantity": str(
                                exit_clf.pending_sell_quantity
                            ),
                            "sellable_quantity": str(
                                exit_clf.sellable_quantity
                            ),
                            "requested_after_clamp": str(qty),
                        },
                    )
            else:
                return _fail(
                    "ORDER_QTY_EXCEEDED",
                    ORDER_QTY_REJECT,
                    {
                        "limit": str(policy.max_order_quantity),
                        "quantity": str(qty),
                    },
                )

        # 7) Daily ENTRY quota — EXIT(SELL)는 절대 미적용
        # UPBIT REAL AUTO BUY: portfolio_daily_entry_limit (BUY only) SoT
        # 기타 market/MANUAL: 기존 V1/V2 (Kiwoom 등 호환)
        # submit reservation은 최종 PASS 직전에서만 수행 (중간 실패 leak 방지)
        submit_reserve_plan: dict[str, Any] | None = None
        source_u = str(order_source or "").strip().upper()
        base_detail["order_source"] = source_u or None
        # SELL / verified EXIT → ENTRY quota 완전 분리 (표시용 count만)
        if side_u == "SELL" or verified_exit:
            base_detail["daily_entry_quota_applies"] = False
            base_detail["daily_order_count"] = self._count_orders_today(uba_id)
            if broker == "UPBIT":
                try:
                    from stock_platform.operation.upbit_full_market.portfolio_daily_entry_admission import (
                        resolve_portfolio_daily_entry_limit,
                    )
                    from stock_platform.operation.upbit_full_market.portfolio_daily_entry_count import (
                        summarize_portfolio_daily_entries,
                    )

                    lim = resolve_portfolio_daily_entry_limit(
                        self._session, uba_id
                    )
                    usage = summarize_portfolio_daily_entries(
                        self._session, uba_id, daily_limit=lim
                    )
                    base_detail["daily_entry_limit"] = usage["entry_limit"]
                    base_detail["daily_entry_used"] = usage["entry_count"]
                    base_detail["daily_exit_excluded_from_entry_quota"] = True
                except Exception:  # noqa: BLE001
                    pass
        elif (
            broker == "UPBIT"
            and side_u == "BUY"
            and (
                source_u == "AUTO"
                or (not source_u and strategy_id is not None)
            )
        ):
            from stock_platform.operation.upbit_full_market.constants import (
                REASON_DAILY_ENTRY_LIMIT_REACHED,
            )
            from stock_platform.operation.upbit_full_market.portfolio_daily_entry_admission import (
                MODE_UNLIMITED,
                resolve_portfolio_daily_entry_policy,
            )
            from stock_platform.operation.upbit_full_market.portfolio_daily_entry_count import (
                summarize_portfolio_daily_entries,
            )
            from stock_platform.order.order_limit_policy_v2 import (
                trading_date_kst,
            )

            day = trading_date_kst()
            mode, lim = resolve_portfolio_daily_entry_policy(
                self._session, uba_id
            )
            usage = summarize_portfolio_daily_entries(
                self._session,
                uba_id,
                daily_limit=lim,
                mode=mode,
            )
            base_detail["order_limit_policy_version"] = (
                "UPBIT_DAILY_ENTRY_V1"
            )
            base_detail["order_limit_trading_date"] = day.isoformat()
            base_detail["daily_entry_quota_applies"] = mode != MODE_UNLIMITED
            base_detail["daily_entry_limit_mode"] = mode
            base_detail["daily_entry_limit"] = usage["entry_limit"]
            base_detail["daily_entry_used"] = usage["entry_count"]
            base_detail["daily_entry_count_semantics"] = usage[
                "count_source"
            ]
            # legacy 필드 — 모니터링 호환 (의미는 ENTRY used/limit)
            base_detail["daily_order_limit"] = usage["entry_limit"]
            base_detail["daily_order_count"] = usage["entry_count"]
            if usage["blocking"]:
                return _fail(
                    REASON_DAILY_ENTRY_LIMIT_REACHED,
                    DAILY_LIMIT_REJECT,
                    {
                        "limit": usage["entry_limit"],
                        "count": usage["entry_count"],
                        "mode": mode,
                        "policy_version": "UPBIT_DAILY_ENTRY_V1",
                        "legacy_reason": "PORTFOLIO_DAILY_ENTRY_LIMIT",
                    },
                )
        elif not verified_exit:
            from stock_platform.order.order_limit_policy_v2 import (
                ORDER_LIMIT_V1,
                ORDER_LIMIT_V2,
                REASON_DAILY_FILLED_ENTRY_LIMIT,
                REASON_DAILY_ORDER_LIMIT,
                REASON_DAILY_SUBMIT_LIMIT,
                effective_v2_limits,
                parse_strategy_id,
                resolve_order_limit_policy_version,
                trading_date_kst,
            )
            from stock_platform.risk_engine.strategy_daily_order_usage_service import (
                StrategyDailyOrderUsageService,
            )

            day = trading_date_kst()
            sid = parse_strategy_id(strategy_id)
            version = resolve_order_limit_policy_version(
                trading_date=day,
                daily_submit_limit=policy.daily_submit_limit,
                daily_filled_entry_limit=policy.daily_filled_entry_limit,
            )
            base_detail["order_limit_policy_version"] = version
            base_detail["order_limit_trading_date"] = day.isoformat()

            if version == ORDER_LIMIT_V2 and sid is not None:
                submit_lim, filled_lim = effective_v2_limits(
                    daily_order_limit=int(policy.daily_order_limit),
                    daily_submit_limit=policy.daily_submit_limit,
                    daily_filled_entry_limit=policy.daily_filled_entry_limit,
                )
                usage_svc = StrategyDailyOrderUsageService(self._session)
                snap = usage_svc.snapshot(
                    user_broker_account_id=uba_id,
                    broker_code=broker,
                    strategy_id=sid,
                    deployment_id=strategy_deployment_id,
                    trading_date=day,
                )
                base_detail["daily_submit_limit"] = submit_lim
                base_detail["daily_filled_entry_limit"] = filled_lim
                base_detail["daily_submit_count"] = snap["submit_count"]
                base_detail["daily_filled_entry_count"] = snap[
                    "filled_entry_count"
                ]
                if snap["filled_entry_count"] >= filled_lim:
                    return _fail(
                        REASON_DAILY_FILLED_ENTRY_LIMIT,
                        DAILY_LIMIT_REJECT,
                        {
                            "limit": filled_lim,
                            "count": snap["filled_entry_count"],
                            "policy_version": ORDER_LIMIT_V2,
                        },
                    )
                if snap["submit_count"] >= submit_lim:
                    return _fail(
                        REASON_DAILY_SUBMIT_LIMIT,
                        DAILY_LIMIT_REJECT,
                        {
                            "limit": submit_lim,
                            "count": snap["submit_count"],
                            "policy_version": ORDER_LIMIT_V2,
                        },
                    )
                submit_reserve_plan = {
                    "user_broker_account_id": uba_id,
                    "broker_code": broker,
                    "strategy_id": sid,
                    "deployment_id": strategy_deployment_id,
                    "submit_limit": submit_lim,
                    "trading_date": day,
                }
            else:
                # V1 legacy — Kiwoom/비-UPBIT-AUTO (BUY+SELL CREATE)
                daily_count = self._count_orders_today(uba_id)
                base_detail["daily_order_count"] = daily_count
                base_detail["daily_order_limit"] = int(policy.daily_order_limit)
                if daily_count >= int(policy.daily_order_limit):
                    return _fail(
                        REASON_DAILY_ORDER_LIMIT,
                        DAILY_LIMIT_REJECT,
                        {
                            "limit": int(policy.daily_order_limit),
                            "count": daily_count,
                            "policy_version": ORDER_LIMIT_V1,
                        },
                    )

        # 8a) Account Hard Safety — Kill/CRITICAL만 (수동 MTM LIMIT_REACHED는 ENTRY 비차단)
        if not verified_exit:
            from stock_platform.risk_engine.strategy_owned_risk_service import (
                StrategyOwnedRiskService,
            )

            hard_block, hard_detail = StrategyOwnedRiskService(
                self._session
            ).account_hard_safety_blocks_entry(
                user_broker_account_id=uba_id,
            )
            base_detail["account_hard_safety"] = hard_detail
            if hard_block:
                return _fail(
                    "ACCOUNT_HARD_SAFETY_BLOCKED",
                    LOSS_LIMIT_REJECT,
                    hard_detail,
                )

        # 8a2) Symbol Ownership — AUTO ENTRY만 MANUAL/UNKNOWN/hold 차단
        if (
            not verified_exit
            and side_u == "BUY"
            and strategy_id is not None
        ):
            try:
                from stock_platform.trading.symbol_ownership import (
                    SymbolOwnershipService,
                )

                allowed, skip_reason, ownership = SymbolOwnershipService(
                    self._session
                ).entry_gate(
                    broker_code=broker,
                    user_broker_account_id=uba_id,
                    symbol=sym,
                )
                base_detail["symbol_ownership"] = ownership.to_dict()
                if not allowed:
                    return _fail(
                        skip_reason or "SYMBOL_OWNERSHIP_BLOCKED",
                        LIVE_REJECTED,
                        ownership.to_dict(),
                    )
            except Exception as exc:  # noqa: BLE001
                return _fail(
                    "SYMBOL_OWNERSHIP_UNKNOWN",
                    LIVE_REJECTED,
                    {"error": type(exc).__name__},
                )

        # 8b) Strategy Daily Loss — strategy-owned PnL만 (account_daily_loss 미사용)
        loss_hit, loss_detail = self._strategy_or_legacy_daily_loss_breached(
            user_broker_account_id=uba_id,
            broker_code=broker,
            strategy_id=strategy_id,
            strategy_deployment_id=strategy_deployment_id,
            limit=policy.daily_max_loss_amount,
        )
        base_detail["strategy_daily_loss"] = loss_detail
        if (not verified_exit) and loss_hit:
            return _fail(
                "DAILY_LOSS_LIMIT_REACHED",
                LOSS_LIMIT_REJECT,
                {
                    "limit": str(policy.daily_max_loss_amount),
                    **loss_detail,
                },
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

        if broker in {"UPBIT", "KIWOOM"} and not verified_exit:
            # ENTRY: AUTO open만 한도. MANUAL remote/pending 제외. UNKNOWN fail-closed.
            exposure = evaluate_live_open_order_exposure(
                self._session,
                uba_id=uba_id,
                broker_code=broker,
                environment=env,
            )
            base_detail.update(exposure.as_detail())
            base_detail["auto_open_order_limit"] = int(policy.max_open_orders)
            if not exposure.remote_state_ok:
                return _fail(
                    str(exposure.reason_code or "REMOTE_OPEN_CHECK_FAILED"),
                    OPEN_ORDER_LIMIT,
                    {
                        "limit": int(policy.max_open_orders),
                        "auto_open_orders": exposure.auto_open_count,
                        "manual_open_orders": exposure.manual_open_count,
                        "unknown_open_orders": exposure.unknown_open_count,
                        "remote_open_state": exposure.remote_state,
                    },
                )
            if int(exposure.unknown_open_count) > 0 or (
                exposure.reason_code == "ORDER_OWNERSHIP_UNKNOWN"
            ):
                return _fail(
                    "ORDER_OWNERSHIP_UNKNOWN",
                    OPEN_ORDER_LIMIT,
                    {
                        "limit": int(policy.max_open_orders),
                        "auto_open_orders": exposure.auto_open_count,
                        "manual_open_orders": exposure.manual_open_count,
                        "unknown_open_orders": exposure.unknown_open_count,
                    },
                )
            open_count = int(exposure.auto_open_count)
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
                    "auto_open_orders": open_count,
                },
            )

        # 9c) Slippage — MARKET BUY: unit price 없음 / MARKET SELL: 주문가 미확정 → 스킵
        if (
            reference_price is not None
            and reference_price > ZERO
            and px is not None
            and px > ZERO
            and not (order_type_u == "MARKET" and side_u == "BUY")
            and not (order_type_u == "MARKET" and side_u == "SELL")
        ):
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

        # V2: 최종 PASS 직전 atomic submit reservation
        if submit_reserve_plan is not None:
            from stock_platform.order.order_limit_policy_v2 import (
                ORDER_LIMIT_V2,
                REASON_DAILY_SUBMIT_LIMIT,
            )
            from stock_platform.risk_engine.strategy_daily_order_usage_service import (
                StrategyDailyOrderUsageService,
            )

            ok, reserved = StrategyDailyOrderUsageService(
                self._session
            ).try_reserve_submit(**submit_reserve_plan)
            base_detail["daily_submit_count"] = reserved.get(
                "submit_count", base_detail.get("daily_submit_count")
            )
            if not ok:
                return _fail(
                    REASON_DAILY_SUBMIT_LIMIT,
                    DAILY_LIMIT_REJECT,
                    {
                        "limit": submit_reserve_plan["submit_limit"],
                        "count": reserved.get("submit_count"),
                        "policy_version": ORDER_LIMIT_V2,
                    },
                )
            base_detail["submit_reserved"] = True
            base_detail["submit_reserve_strategy_id"] = submit_reserve_plan[
                "strategy_id"
            ]
            base_detail["submit_reserve_deployment_id"] = int(
                submit_reserve_plan.get("deployment_id") or 0
            )
            base_detail["submit_reserve_trading_date"] = (
                submit_reserve_plan["trading_date"].isoformat()
            )

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
        price: Decimal | None,
        quantity: Decimal,
        window_seconds: int,
    ) -> bool:
        since = datetime.now(timezone.utc) - timedelta(seconds=window_seconds)
        price_clause = (
            TradingOrderEntity.order_price.is_(None)
            if price is None
            else (TradingOrderEntity.order_price == price)
        )
        row = self._session.scalar(
            select(TradingOrderEntity)
            .where(
                TradingOrderEntity.user_broker_account_id
                == user_broker_account_id,
                TradingOrderEntity.symbol == symbol.upper(),
                TradingOrderEntity.side_code == side.upper(),
                TradingOrderEntity.order_quantity == quantity,
                price_clause,
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

    def _strategy_or_legacy_daily_loss_breached(
        self,
        *,
        user_broker_account_id: int,
        broker_code: str,
        strategy_id: str | None,
        strategy_deployment_id: int | None,
        limit: Decimal,
    ) -> tuple[bool, dict[str, Any]]:
        """
        Strategy scope가 있으면 strategy-owned PnL만 사용.
        strategy_id 없는 수동 LIVE 주문만 legacy account_daily_loss 유지.
        """

        if limit <= ZERO:
            return False, {"mode": "NO_LIMIT"}
        try:
            from stock_platform.risk_engine.strategy_owned_risk_service import (
                StrategyOwnedRiskService,
                _parse_strategy_id,
            )

            sid = _parse_strategy_id(strategy_id)
            if sid is not None:
                hit, detail = StrategyOwnedRiskService(
                    self._session
                ).strategy_daily_loss_breached(
                    user_broker_account_id=user_broker_account_id,
                    broker_code=broker_code,
                    strategy_id=sid,
                    deployment_id=strategy_deployment_id,
                    limit=limit,
                )
                detail = {**detail, "mode": "STRATEGY_OWNED"}
                return hit, detail

            # legacy: 수동/무전략 주문만 account_daily_loss
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
            if row is None or not hasattr(row, "status_code"):
                return False, {"mode": "LEGACY_ACCOUNT", "row": None}
            status = str(row.status_code).upper()
            current_loss = Decimal(str(row.current_loss_amount or 0))
            hit = status in {"BREACHED", "LIMIT_REACHED", "KILL"} or (
                current_loss >= limit
            )
            return hit, {
                "mode": "LEGACY_ACCOUNT",
                "status_code": row.status_code,
                "current_loss_amount": str(current_loss),
            }
        except Exception as exc:  # noqa: BLE001
            # fail-closed on strategy path errors would block first order —
            # unknown strategy parse already falls through; DB errors → block
            return True, {
                "mode": "ERROR_FAIL_CLOSED",
                "error": type(exc).__name__,
            }

    def _daily_loss_breached(
        self,
        *,
        user_broker_account_id: int,
        limit: Decimal,
    ) -> bool:
        """하위 호환 — strategy 없는 legacy account 기준."""

        hit, _ = self._strategy_or_legacy_daily_loss_breached(
            user_broker_account_id=user_broker_account_id,
            broker_code="",
            strategy_id=None,
            strategy_deployment_id=None,
            limit=limit,
        )
        return hit
