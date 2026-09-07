from __future__ import annotations

import logging
import re
import traceback
from dataclasses import dataclass
from decimal import Decimal

ZERO = Decimal("0")
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from stock_platform.common.settings import get_settings
from stock_platform.order.id_generator import ClientOrderIdGenerator
from stock_platform.order.models import (
    CreateOrderCommand,
    OrderSide,
    OrderStatus,
    OrderTimeInForce,
    OrderType,
)
from stock_platform.order.outbox_models import OutboxEventType
from stock_platform.order.outbox_repository import OrderOutboxRepository
from stock_platform.order.repository import TradingOrderRepository
from stock_platform.order.service import TradingOrderService
from stock_platform.risk.engine import RiskManagementEngine
from stock_platform.risk.models import (
    PositionSizingMode,
    PositionSizingRequest,
    RiskPolicy,
)
from stock_platform.risk_engine.kill_switch_guard import (
    KillSwitchUnavailableError,
    PersistentKillSwitchGuard,
)
from stock_platform.risk_engine.order_guard import (
    DatabaseBackedRiskOrderGuard,
)

logger = logging.getLogger(__name__)

# persist 구간 stage — 예외 시 failed_stage 로 반환
PERSIST_CREATE_ORDER = "PERSIST_CREATE_ORDER"
PERSIST_FLUSH_ORDER = "PERSIST_FLUSH_ORDER"
PERSIST_STATUS_PENDING = "PERSIST_STATUS_PENDING"
PERSIST_ENQUEUE_OUTBOX = "PERSIST_ENQUEUE_OUTBOX"
PERSIST_COMMIT = "PERSIST_COMMIT"

# 기술 실패 reason_code (비즈니스 _blocked 코드와 분리)
REASON_ORDER_PERSIST_FAILED = "ORDER_PERSIST_FAILED"
REASON_ORDER_OUTBOX_ENQUEUE_FAILED = "ORDER_OUTBOX_ENQUEUE_FAILED"
REASON_ORDER_COMMIT_FAILED = "ORDER_COMMIT_FAILED"

_STAGE_REASON_CODE: dict[str, str] = {
    PERSIST_CREATE_ORDER: REASON_ORDER_PERSIST_FAILED,
    PERSIST_FLUSH_ORDER: REASON_ORDER_PERSIST_FAILED,
    PERSIST_STATUS_PENDING: REASON_ORDER_PERSIST_FAILED,
    PERSIST_ENQUEUE_OUTBOX: REASON_ORDER_OUTBOX_ENQUEUE_FAILED,
    PERSIST_COMMIT: REASON_ORDER_COMMIT_FAILED,
}

_SECRET_KV_RE = re.compile(
    r"(?i)\b("
    r"arm_token|app_key|appkey|secret_key|access_token|refresh_token|"
    r"account_number|authorization|bearer|password|api_secret|api_key|"
    r"oauth_token|token"
    r")\b\s*[:=]\s*\S+"
)
_LONG_SECRET_RE = re.compile(r"(?i)\b(?:sk-|Bearer\s+)[A-Za-z0-9_\-.]{8,}")


@dataclass(frozen=True, slots=True)
class OrderExecutionCommand:
    """단일 주문 진입점 입력."""

    # Paper: paper_account.account_id / LIVE: None (UBA 만 사용)
    account_id: int | None
    broker_code: str
    exchange_code: str
    symbol: str
    side: OrderSide
    order_type: OrderType
    price: Decimal | None
    quantity: Decimal | None = None
    order_amount: Decimal | None = None
    time_in_force: OrderTimeInForce = OrderTimeInForce.DAY
    strategy_code: str | None = None
    strategy_deployment_id: int | None = None
    strategy_id: int | None = None
    portfolio_id: int | None = None
    position_id: int | None = None
    client_order_id: str | None = None
    idempotency_key: str | None = None
    account_number: str | None = None
    portfolio_value: Decimal | None = None
    available_cash: Decimal | None = None
    current_position_count: int = 0
    skip_risk_checks: bool = False
    metadata_payload: dict[str, Any] | None = None
    actor: str = "ORDER_EXECUTION"
    # PAPER(기본) | LIVE — LIVE는 이중 게이트 + transition 필요
    environment: str = "PAPER"
    # LIVE 키움·업비트 UserBrokerAccount 격리
    user_broker_account_id: int | None = None
    # 마스킹된 외부 계좌 식별자 (Outbox/Adapter 전달용)
    external_account_ref: str | None = None
    owner_user_id: int | None = None
    # STEP8-2 — 리스크 해석용
    order_source: str = "MANUAL"
    is_risk_reducing: bool = False
    user_id: int | None = None
    # STEP 8-8 — ARM 토큰·기준가
    arm_token: str | None = None
    reference_price: Decimal | None = None


@dataclass(frozen=True, slots=True)
class OrderExecutionResult:
    allowed: bool
    reason_code: str
    order_id: int | None
    outbox_id: int | None
    status_code: str | None
    client_order_id: str | None
    quantity: Decimal | None
    price: Decimal | None
    position_plan: dict[str, Any] | None = None
    # persist 기술 실패 전용 — 비즈니스 _blocked 는 비움
    failed_stage: str | None = None
    exception_class: str | None = None
    sanitized_message: str | None = None


def sanitize_persist_error_message(exc: BaseException) -> str:
    """예외 메시지에서 시크릿·계좌 원문을 제거하고 길이를 제한한다."""

    raw = str(exc or "")
    text = _SECRET_KV_RE.sub(r"\1=<redacted>", raw)
    text = _LONG_SECRET_RE.sub("[SECRET]", text)
    text = " ".join(text.split())
    return text[:200]


def persist_error_application_frame(exc: BaseException) -> str | None:
    """stack 전체가 아니라 stock_platform 최초 frame만."""

    tb = exc.__traceback__
    if tb is None:
        return None
    for frame in traceback.extract_tb(tb):
        path = frame.filename.replace("\\", "/")
        if "/stock_platform/" in path or path.endswith("execution_service.py"):
            name = path.rsplit("/", 1)[-1]
            return f"{name}:{frame.name}:{frame.lineno}"
    return None


def persist_reason_code_for_stage(stage: str) -> str:
    return _STAGE_REASON_CODE.get(stage, REASON_ORDER_PERSIST_FAILED)


class OrderExecutionService:
    """
    Signal → Position Sizing → Risk → Safety/KillSwitch
    → Idempotency/Outbox → Order State 단일 진입점.

    Broker 직접 호출은 하지 않으며 Outbox Worker만 송신한다.
    """

    def __init__(self, session: Session) -> None:
        self._session = session
        self._order_service = TradingOrderService(session)
        self._order_repository = TradingOrderRepository(session)
        self._outbox_repository = OrderOutboxRepository(session)
        self._sizing_engine = RiskManagementEngine()
        # V2 submit reservation — broker 미전송 실패 시 release
        self._pending_submit_release: dict[str, Any] | None = None

    def _release_pending_submit(self) -> None:
        detail = self._pending_submit_release
        self._pending_submit_release = None
        if not detail or not detail.get("submit_reserved"):
            return
        try:
            from stock_platform.risk_engine.strategy_daily_order_usage_service import (
                StrategyDailyOrderUsageService,
            )
            from stock_platform.order.order_limit_policy_v2 import (
                trading_date_kst,
            )
            from datetime import date as date_cls

            day_raw = detail.get("submit_reserve_trading_date")
            day = (
                date_cls.fromisoformat(str(day_raw))
                if day_raw
                else trading_date_kst()
            )
            StrategyDailyOrderUsageService(self._session).release_submit(
                user_broker_account_id=int(
                    detail.get("user_broker_account_id")
                    or detail.get("uba_id")
                    or 0
                ),
                broker_code=str(detail.get("broker_code") or ""),
                strategy_id=int(detail["submit_reserve_strategy_id"]),
                deployment_id=int(
                    detail.get("submit_reserve_deployment_id") or 0
                ),
                trading_date=day,
            )
        except Exception:  # noqa: BLE001
            pass

    def _blocked(
        self,
        reason_code: str,
        *,
        message: str | None = None,
    ) -> OrderExecutionResult:
        self._release_pending_submit()
        return OrderExecutionResult(
            allowed=False,
            reason_code=reason_code,
            order_id=None,
            outbox_id=None,
            status_code=None,
            client_order_id=None,
            quantity=None,
            price=None,
            position_plan=(
                {"message": message}
                if message
                else None
            ),
        )

    def submit(
        self,
        command: OrderExecutionCommand,
    ) -> OrderExecutionResult:
        from stock_platform.risk_engine.exit_risk import (
            exit_sell_transaction_fence,
        )

        side_u = (
            command.side.value
            if hasattr(command.side, "value")
            else str(command.side or "")
        )
        with exit_sell_transaction_fence(
            self._session,
            user_broker_account_id=command.user_broker_account_id,
            paper_account_id=command.account_id,
            symbol=command.symbol,
            side=side_u,
        ):
            return self._submit_inner(command)

    def _submit_inner(
        self,
        command: OrderExecutionCommand,
    ) -> OrderExecutionResult:
        environment = (command.environment or "PAPER").upper()
        # LIVE+UBA: 환경변수 단일 계좌를 사용자 계좌처럼 쓰지 않음
        account_number = command.account_number
        if not account_number and command.user_broker_account_id:
            account_number = (
                command.external_account_ref
                or f"UBA:{command.user_broker_account_id}"
            )
        if not account_number and environment != "LIVE":
            account_number = (
                get_settings().kiwoom_account_number.strip()
            )
        if environment == "LIVE" and command.user_broker_account_id is None:
            return self._blocked("UBA_REQUIRED")
        if environment == "LIVE":
            from stock_platform.trading.upbit_24x7_control import (
                live_outbox_queue_block_reason,
            )

            worker_block = live_outbox_queue_block_reason()
            if worker_block:
                return self._blocked(worker_block)
        try:
            paper_account_id, uba_id = self._resolve_account_ownership(
                account_id=command.account_id,
                user_broker_account_id=command.user_broker_account_id,
            )
        except ValueError as exc:
            return self._blocked(str(exc) or "ACCOUNT_OWNERSHIP_INVALID")
        if not account_number and not command.skip_risk_checks:
            if environment == "LIVE":
                account_number = (
                    command.external_account_ref
                    or f"UBA:{command.user_broker_account_id}"
                )
            else:
                return self._blocked(
                    "RISK_ACCOUNT_NUMBER_MISSING"
                )

        try:
            quantity, price, plan_payload = self._resolve_size(
                command
            )
        except ValueError as exc:
            return self._blocked(
                "POSITION_SIZING_REJECTED",
                message=str(exc),
            )

        # skip_risk_checks여도 persist 전 outstanding SELL + UPBIT 최소노셔널 강제
        from stock_platform.order.pre_persist_exit_gate import (
            evaluate_pre_persist_exit_gate,
        )

        order_type_text = (
            command.order_type.value
            if hasattr(command.order_type, "value")
            else str(command.order_type or "")
        )
        # UPBIT MARKET BUY: order_price / price = 총 KRW (ticker 아님)
        market_krw_amount = None
        side_text = str(
            command.side.value
            if hasattr(command.side, "value")
            else command.side
            or ""
        ).upper()
        broker_u = str(command.broker_code or "").upper()
        if (
            broker_u == "UPBIT"
            and str(order_type_text or "").upper() == "MARKET"
            and side_text == "BUY"
        ):
            if command.order_amount is not None:
                market_krw_amount = Decimal(str(command.order_amount))
            elif price is not None:
                market_krw_amount = Decimal(str(price))

        pre_persist_block = evaluate_pre_persist_exit_gate(
            self._session,
            side=command.side.value
            if hasattr(command.side, "value")
            else str(command.side or ""),
            symbol=command.symbol,
            exchange_code=command.exchange_code,
            quantity=quantity,
            price=price,
            order_type=order_type_text,
            broker_code=str(command.broker_code or ""),
            environment=environment,
            user_broker_account_id=uba_id,
            paper_account_id=paper_account_id,
            market_krw_amount=market_krw_amount,
        )
        if pre_persist_block:
            return self._blocked(pre_persist_block)

        if not command.skip_risk_checks:
            if environment == "LIVE":
                from stock_platform.operation.live_health_gate import (
                    LiveHealthBlockedError,
                    assert_live_orders_allowed,
                )
                from stock_platform.order.live_safety_pipeline import (
                    LiveOrderSafetyPipeline,
                )

                if command.user_broker_account_id is None:
                    return self._blocked("UBA_REQUIRED")

                # MARKET SELL: resolve_size가 broker price=None을 반환한다.
                # plan/command reference만 추정 노셔널용으로 파이프라인에 전달.
                plan_reference_price = None
                if isinstance(plan_payload, dict) and plan_payload.get(
                    "reference_price"
                ) not in (None, ""):
                    try:
                        plan_reference_price = Decimal(
                            str(plan_payload["reference_price"])
                        )
                    except Exception:  # noqa: BLE001
                        plan_reference_price = None
                safety_reference_price = None
                if not (
                    str(command.broker_code or "").upper() == "UPBIT"
                    and str(order_type_text or "").upper() == "MARKET"
                    and side_text == "BUY"
                ):
                    safety_reference_price = (
                        command.reference_price or plan_reference_price
                    )

                # STEP 8-7 — Adapter 직전과 동일한 LIVE 안전 파이프라인
                safety = LiveOrderSafetyPipeline(self._session).evaluate(
                    user_id=command.user_id or command.owner_user_id,
                    user_broker_account_id=int(
                        command.user_broker_account_id
                    ),
                    broker_code=str(command.broker_code),
                    exchange_code=command.exchange_code,
                    symbol=command.symbol,
                    side=command.side.value,
                    quantity=quantity,
                    price=price,
                    strategy_id=(
                        str(command.strategy_id)
                        if command.strategy_id is not None
                        else (
                            command.strategy_code
                            or (
                                str(command.strategy_deployment_id)
                                if command.strategy_deployment_id
                                else None
                            )
                        )
                    ),
                    strategy_deployment_id=command.strategy_deployment_id,
                    run_id=(
                        (command.metadata_payload or {}).get("run_id")
                        if isinstance(command.metadata_payload, dict)
                        else None
                    ),
                    actor=command.actor,
                    operator=command.actor,
                    environment=environment,
                    is_risk_reducing=command.is_risk_reducing,
                    arm_token=command.arm_token,
                    # MARKET BUY: unit ticker 슬리피지 기준 금지 (KRW notional)
                    reference_price=safety_reference_price,
                    require_arm=True,
                    # KIWOOM LIMIT tick 검증 — 주문 유형을 파이프라인에 전달
                    order_type=(
                        command.order_type.value
                        if hasattr(command.order_type, "value")
                        else str(command.order_type or "")
                    ),
                    order_amount=command.order_amount,
                    order_source=str(command.order_source or "MANUAL"),
                )
                if not safety.allowed:
                    # EXIT deterministic reject — intent에 지문 기록(재제출 폭주 방지)
                    try:
                        if (
                            side_text == "SELL"
                            and str(safety.reason_code or "")
                            == "ORDER_QTY_EXCEEDED"
                            and command.user_broker_account_id is not None
                        ):
                            from stock_platform.operation.upbit_exit_intent.hooks import (
                                note_deterministic_qty_reject,
                            )

                            note_deterministic_qty_reject(
                                user_broker_account_id=int(
                                    command.user_broker_account_id
                                ),
                                symbol=str(command.symbol),
                                reason_code=str(safety.reason_code),
                                detail=getattr(safety, "detail", None) or {},
                            )
                    except Exception:  # noqa: BLE001
                        pass
                    return self._blocked(safety.reason_code)
                # verified EXIT clamp — 파이프라인이 줄인 수량을 실제 주문에 반영
                safety_detail = getattr(safety, "detail", None) or {}
                if safety_detail.get("effective_quantity") not in (None, ""):
                    try:
                        clamped_qty = Decimal(
                            str(safety_detail["effective_quantity"])
                        )
                        if clamped_qty > ZERO:
                            quantity = clamped_qty
                    except Exception:  # noqa: BLE001
                        pass
                # V2 reservation 추적 — 이후 실패 시 release
                if safety_detail.get("submit_reserved"):
                    self._pending_submit_release = {
                        **dict(safety_detail),
                        "user_broker_account_id": int(
                            command.user_broker_account_id
                        ),
                        "broker_code": str(command.broker_code),
                    }
                # UBA1380 P1 — FUTURE BUY risk snapshot (이미 있으면 유지)
                if side_text == "BUY":
                    try:
                        from stock_platform.operation.autotrading_truth_bundle import (
                            build_risk_decision_snapshot,
                            maybe_stamp_risk_decision_snapshot,
                        )

                        snap = build_risk_decision_snapshot(
                            allowed=True,
                            result=str(
                                getattr(safety, "reason_code", None)
                                or "LIVE_SAFETY_PASS"
                            ),
                            reason_codes=[
                                str(
                                    getattr(safety, "reason_code", None)
                                    or "LIVE_SAFETY_PASS"
                                )
                            ],
                            limits={
                                k: safety_detail.get(k)
                                for k in (
                                    "daily_entry_limit",
                                    "daily_order_limit",
                                    "max_order_amount",
                                    "max_order_quantity",
                                )
                                if k in safety_detail
                            },
                            usage={
                                k: safety_detail.get(k)
                                for k in (
                                    "daily_entry_used",
                                    "daily_order_count",
                                    "daily_submit_count",
                                )
                                if k in safety_detail
                            },
                            extra={
                                "pipeline": "LiveOrderSafetyPipeline",
                                "order_source": safety_detail.get(
                                    "order_source"
                                ),
                            },
                        )
                        stamped = maybe_stamp_risk_decision_snapshot(
                            dict(command.metadata_payload or {}),
                            snap,
                            side="BUY",
                        )
                        # frozen dataclass — 필드 재할당 대신 dict in-place
                        if command.metadata_payload is None:
                            object.__setattr__(
                                command, "metadata_payload", stamped
                            )
                        else:
                            command.metadata_payload.clear()
                            command.metadata_payload.update(stamped)
                    except Exception:  # noqa: BLE001
                        pass

                try:
                    assert_live_orders_allowed(self._session)
                except LiveHealthBlockedError:
                    return self._blocked("SYSTEM_HEALTH_CRITICAL")

            try:
                PersistentKillSwitchGuard(
                    self._session
                ).require_order_allowed(
                    side=command.side.value,
                    allow_sell=True,
                    exchange_code=command.exchange_code,
                    user_broker_account_id=uba_id,
                    paper_account_id=paper_account_id,
                )
            except KillSwitchUnavailableError:
                return self._blocked(
                    "KILL_SWITCH_UNAVAILABLE"
                )
            except PermissionError:
                return self._blocked(
                    "GLOBAL_KILL_SWITCH_ACTIVE"
                )

            # Account Pause(Recovery Lock) — Paper/UBA 신규·일반 주문 차단
            try:
                from stock_platform.broker.recovery_lock import (
                    RecoveryAccountLockService,
                )

                lock = RecoveryAccountLockService(self._session)
                paused = False
                if environment != "LIVE":
                    paused = (
                        lock.is_trading_paused(
                            paper_account_id=int(command.account_id),
                            broker_code=str(command.broker_code),
                        )
                        is True
                    )
                elif command.user_broker_account_id is not None:
                    paused = (
                        lock.is_trading_paused(
                            user_broker_account_id=int(
                                command.user_broker_account_id
                            ),
                            broker_code=str(command.broker_code),
                        )
                        is True
                    )
                if paused:
                    return self._blocked("ACCOUNT_PAUSED")
            except Exception:  # noqa: BLE001
                if command.side.value.upper() != "SELL":
                    return self._blocked("ACCOUNT_PAUSE_CHECK_FAILED")

            # STEP 8-5-2 — LIVE UBA는 Risk 전에 Vault Credential 검사
            if (
                environment == "LIVE"
                and command.user_broker_account_id is not None
                and str(command.broker_code).upper()
                in {"KIWOOM", "UPBIT"}
            ):
                from stock_platform.broker.credential_vault_service import (
                    BrokerCredentialVaultError,
                    BrokerCredentialVaultService,
                )

                try:
                    BrokerCredentialVaultService(
                        self._session
                    ).assert_live_order_allowed(
                        int(command.user_broker_account_id),
                        broker_code=str(command.broker_code),
                    )
                except BrokerCredentialVaultError as exc:
                    return self._blocked(
                        exc.code.upper(),
                        message=exc.message,
                    )

            risk_quote = None
            risk_unit_price = None
            is_upbit_market = (
                str(command.broker_code or "").upper() == "UPBIT"
                and str(order_type_text or "").upper() == "MARKET"
            )
            if is_upbit_market and side_text == "BUY":
                # MARKET BUY: risk notional = KRW quote; unit ticker는 reference
                risk_quote = (
                    Decimal(str(command.order_amount))
                    if command.order_amount is not None
                    else (
                        Decimal(str(price))
                        if price is not None
                        else None
                    )
                )
                risk_unit_price = self._upbit_market_risk_unit_price(
                    command=command,
                    plan_payload=plan_payload,
                )
            elif is_upbit_market and side_text == "SELL":
                # MARKET SELL: broker price=None 정상.
                # risk/notional만 유효 unit price 필요 — 0/None 위장 금지.
                risk_unit_price = self._upbit_market_risk_unit_price(
                    command=command,
                    plan_payload=plan_payload,
                )
                if risk_unit_price is None or risk_unit_price <= ZERO:
                    return self._blocked("MARKET_SELL_RISK_PRICE_UNAVAILABLE")
            risk_result = DatabaseBackedRiskOrderGuard(
                self._session,
                broker_code=command.broker_code,
            ).check(
                account_number=account_number,
                account_id=paper_account_id,
                exchange_code=command.exchange_code,
                symbol=command.symbol,
                side=command.side.value,
                quantity=quantity,
                # MARKET SELL broker price=None → 0 위장 금지; unit은 reference_unit_price
                price=(
                    price
                    if price is not None
                    else (
                        risk_unit_price
                        if risk_unit_price is not None
                        else Decimal("0")
                    )
                ),
                user_id=command.user_id or command.owner_user_id,
                user_broker_account_id=uba_id,
                order_source=command.order_source,
                # 서버가 보유·pending으로 EXIT 재분류 — 클라이언트 플래그 미신뢰
                is_risk_reducing=command.is_risk_reducing,
                environment=environment,
                strategy_id=command.strategy_id,
                strategy_deployment_id=command.strategy_deployment_id,
                quote_amount=risk_quote,
                reference_unit_price=risk_unit_price,
            )
            if not risk_result.allowed:
                from stock_platform.trading.failure_code_normalize import (
                    classify_risk_blocked_reason,
                )

                code, _details, summary = classify_risk_blocked_reason(
                    risk_result.blocked_reason
                )
                return self._blocked(
                    code,
                    message=summary,
                )

        client_order_id = (
            command.client_order_id
            or ClientOrderIdGenerator.generate()
        )
        idempotency_key = (
            command.idempotency_key
            or f"SUBMIT:{client_order_id}"
        )

        existing_outbox = (
            self._outbox_repository.get_by_idempotency_key(
                idempotency_key
            )
        )
        if existing_outbox is not None:
            existing_order = self._order_repository.get(
                existing_outbox.order_id
            )
            return OrderExecutionResult(
                allowed=True,
                reason_code="IDEMPOTENT_REPLAY",
                order_id=existing_outbox.order_id,
                outbox_id=existing_outbox.outbox_id,
                status_code=(
                    existing_order.status_code
                    if existing_order
                    else None
                ),
                client_order_id=(
                    existing_order.client_order_id
                    if existing_order
                    else client_order_id
                ),
                quantity=(
                    existing_order.order_quantity
                    if existing_order
                    else quantity
                ),
                price=(
                    existing_order.order_price
                    if existing_order
                    else price
                ),
                position_plan=plan_payload,
            )

        metadata = dict(command.metadata_payload or {})
        metadata.setdefault("pipeline", "ORDER_EXECUTION_V1")
        if plan_payload:
            metadata["position_plan"] = plan_payload

        # LIVE Dry-Run — Risk 통과 후 submit 직전 Payload 검증, Broker 전송 없음
        from stock_platform.order.live_dry_run import (
            is_live_dry_run_mode,
            mark_dry_run_metadata,
            validate_pre_submit_payload,
        )
        from stock_platform.order.live_shadow import (
            is_live_shadow_mode,
            mark_shadow_metadata,
        )

        dry_run_live = environment == "LIVE" and (
            is_live_dry_run_mode()
            or bool(metadata.get("dry_run"))
            or str(metadata.get("dry_run_mode") or "").upper()
            == "LIVE_DRY_RUN"
        )
        if dry_run_live:
            metadata = mark_dry_run_metadata(metadata)
            pre_submit_payload = {
                "client_order_id": client_order_id,
                "account_id": paper_account_id,
                "broker_code": command.broker_code,
                "exchange_code": command.exchange_code,
                "symbol": command.symbol,
                "side": command.side.value
                if hasattr(command.side, "value")
                else str(command.side),
                "order_type": command.order_type.value
                if hasattr(command.order_type, "value")
                else str(command.order_type),
                "quantity": str(quantity),
                "price": None if price is None else str(price),
                "user_broker_account_id": uba_id,
                "user_id": command.user_id,
                "environment": "LIVE",
                "runtime_scope": metadata.get("runtime_scope")
                or metadata.get("scope_key"),
                "strategy_code": command.strategy_code,
            }
            pre_errors = validate_pre_submit_payload(pre_submit_payload)
            metadata["pre_submit_payload"] = pre_submit_payload
            metadata["pre_submit_ok"] = len(pre_errors) == 0
            metadata["pre_submit_errors"] = pre_errors
            order = self._order_service.create(
                CreateOrderCommand(
                    account_id=paper_account_id,
                    user_broker_account_id=uba_id,
                    broker_code=command.broker_code,
                    exchange_code=command.exchange_code,
                    symbol=command.symbol,
                    side=command.side,
                    order_type=command.order_type,
                    quantity=quantity,
                    price=price,
                    time_in_force=command.time_in_force,
                    strategy_code=command.strategy_code,
                    strategy_deployment_id=(
                        command.strategy_deployment_id
                    ),
                    portfolio_id=command.portfolio_id,
                    position_id=command.position_id,
                    client_order_id=client_order_id,
                    metadata_payload=metadata,
                ),
                actor=command.actor,
                commit=False,
            )
            order.broker_order_id = None
            order.reject_code = "DRY_RUN_BLOCKED"
            order.reject_message = (
                "LIVE dry-run — pre-submit validated; broker submit blocked"
            )
            self._session.commit()
            self._session.refresh(order)
            try:
                from stock_platform.order.outbox_fencing import (
                    record_outbox_audit,
                )

                record_outbox_audit(
                    self._session,
                    event_type="LIVE_DRY_RUN_BLOCKED",
                    detail={
                        "order_id": order.order_id,
                        "broker_code": order.broker_code,
                        "symbol": order.symbol,
                        "side": order.side_code,
                        "quantity": str(order.order_quantity),
                        "price": (
                            None
                            if order.order_price is None
                            else str(order.order_price)
                        ),
                        "user_broker_account_id": (
                            order.user_broker_account_id
                        ),
                        "client_order_id": order.client_order_id,
                        "status_code": order.status_code,
                        "pre_submit_ok": len(pre_errors) == 0,
                        "pre_submit_errors": pre_errors,
                        "runtime_scope": pre_submit_payload.get(
                            "runtime_scope"
                        ),
                    },
                    actor=command.actor,
                )
                self._session.commit()
            except Exception:  # noqa: BLE001
                pass
            return OrderExecutionResult(
                allowed=True,
                reason_code="DRY_RUN_BLOCKED",
                order_id=order.order_id,
                outbox_id=None,
                status_code=order.status_code,
                client_order_id=order.client_order_id,
                quantity=order.order_quantity,
                price=order.order_price,
                position_plan=plan_payload,
            )

        # LIVE Shadow — Intent만 기록, Outbox/Broker 전송 없음
        shadow_live = environment == "LIVE" and (
            is_live_shadow_mode()
            or bool(metadata.get("shadow"))
            or str(metadata.get("shadow_mode") or "").upper()
            == "LIVE_SHADOW"
        )
        if shadow_live:
            metadata = mark_shadow_metadata(metadata)
            order = self._order_service.create(
                CreateOrderCommand(
                    account_id=paper_account_id,
                    user_broker_account_id=uba_id,
                    broker_code=command.broker_code,
                    exchange_code=command.exchange_code,
                    symbol=command.symbol,
                    side=command.side,
                    order_type=command.order_type,
                    quantity=quantity,
                    price=price,
                    time_in_force=command.time_in_force,
                    strategy_code=command.strategy_code,
                    strategy_deployment_id=(
                        command.strategy_deployment_id
                    ),
                    portfolio_id=command.portfolio_id,
                    position_id=command.position_id,
                    client_order_id=client_order_id,
                    metadata_payload=metadata,
                ),
                actor=command.actor,
                commit=False,
            )
            # Shadow Intent: 상태 전이 없이 CREATED 유지 (실주문 경로와 분리)
            order.broker_order_id = None
            order.reject_code = "LIVE_SHADOW_MODE"
            order.reject_message = (
                "LIVE shadow intent — broker submit not performed"
            )
            self._session.commit()
            self._session.refresh(order)
            try:
                from stock_platform.order.outbox_fencing import (
                    record_outbox_audit,
                )

                record_outbox_audit(
                    self._session,
                    event_type="LIVE_SHADOW_INTENT",
                    detail={
                        "order_id": order.order_id,
                        "broker_code": order.broker_code,
                        "symbol": order.symbol,
                        "side": order.side_code,
                        "quantity": str(order.order_quantity),
                        "price": (
                            None
                            if order.order_price is None
                            else str(order.order_price)
                        ),
                        "user_broker_account_id": (
                            order.user_broker_account_id
                        ),
                        "client_order_id": order.client_order_id,
                        "status_code": order.status_code,
                    },
                    actor=command.actor,
                )
                self._session.commit()
            except Exception:  # noqa: BLE001
                pass
            return OrderExecutionResult(
                allowed=True,
                reason_code="LIVE_SHADOW_INTENT",
                order_id=order.order_id,
                outbox_id=None,
                status_code=order.status_code,
                client_order_id=order.client_order_id,
                quantity=order.order_quantity,
                price=order.order_price,
                position_plan=plan_payload,
            )

        # 주문+Outbox를 한 트랜잭션에 묶어 orphan CREATED 방지
        # UPBIT AUTO BUY: UBA+KST-day lock 구간에서 final daily admission 후 persist
        from stock_platform.operation.upbit_full_market.portfolio_daily_entry_admission import (
            REASON_PORTFOLIO_DAILY_ENTRY_LIMIT,
            portfolio_daily_entry_buy_fence,
        )

        persist_stage = PERSIST_CREATE_ORDER
        _daily_fence = portfolio_daily_entry_buy_fence(
            self._session,
            side=side_text,
            broker_code=str(command.broker_code or ""),
            environment=environment,
            order_source=str(command.order_source or "MANUAL"),
            user_broker_account_id=uba_id,
            is_risk_reducing=bool(command.is_risk_reducing),
        )
        _admit_daily_entry = _daily_fence.__enter__()
        try:
            from stock_platform.operation.upbit_entry_execution_trace.order_hooks import (
                trace_admission_attempt,
                trace_admission_result,
            )

            trace_admission_attempt(
                self._session,
                metadata=metadata,
                uba_id=int(uba_id or 0),
                symbol=str(command.symbol or ""),
            )
            _admission = _admit_daily_entry(
                symbol=str(command.symbol or "") or None,
                candidate_id=(
                    (command.metadata_payload or {}).get(
                        "candidate_selection_id"
                    )
                    if isinstance(command.metadata_payload, dict)
                    else None
                ),
            )
            if not _admission.get("allowed"):
                trace_admission_result(
                    self._session,
                    metadata=metadata,
                    uba_id=int(uba_id or 0),
                    symbol=str(command.symbol or ""),
                    allowed=False,
                    reason_code=str(
                        _admission.get("reason")
                        or REASON_PORTFOLIO_DAILY_ENTRY_LIMIT
                    ),
                )
                return self._blocked(
                    str(
                        _admission.get("reason")
                        or REASON_PORTFOLIO_DAILY_ENTRY_LIMIT
                    ),
                    message=(
                        f"daily entry {_admission.get('count_before')}"
                        f"/{_admission.get('limit')} (KST)"
                    ),
                )
            # WAITING restore-epoch / Exit / Feed — persist 직전 hard gate
            try:
                from stock_platform.operation.upbit_full_market.waiting_revalidation_gate import (
                    evaluate_waiting_buy_revalidation_gate,
                )

                _wg = evaluate_waiting_buy_revalidation_gate(
                    self._session,
                    user_broker_account_id=int(uba_id or 0),
                    symbol=str(command.symbol or ""),
                    order_source=str(command.order_source or "MANUAL"),
                    broker_code=str(command.broker_code or ""),
                    side=side_text,
                    is_risk_reducing=bool(command.is_risk_reducing),
                )
                if not _wg.get("allowed"):
                    return self._blocked(
                        str(_wg.get("reason") or "WAITING_REVALIDATION_REQUIRED"),
                        message="waiting revalidation gate blocked BUY",
                    )
            except Exception:  # noqa: BLE001
                return self._blocked(
                    "WAITING_REVALIDATION_REQUIRED",
                    message="waiting revalidation gate error",
                )
            trace_admission_result(
                self._session,
                metadata=metadata,
                uba_id=int(uba_id or 0),
                symbol=str(command.symbol or ""),
                allowed=True,
            )
            persist_stage = PERSIST_CREATE_ORDER
            try:
                order = self._order_service.create(
                    CreateOrderCommand(
                        account_id=paper_account_id,
                        user_broker_account_id=uba_id,
                        broker_code=command.broker_code,
                        exchange_code=command.exchange_code,
                        symbol=command.symbol,
                        side=command.side,
                        order_type=command.order_type,
                        quantity=quantity,
                        price=price,
                        time_in_force=command.time_in_force,
                        strategy_code=command.strategy_code,
                        strategy_deployment_id=(
                            command.strategy_deployment_id
                        ),
                        portfolio_id=command.portfolio_id,
                        position_id=command.position_id,
                        client_order_id=client_order_id,
                        metadata_payload=metadata,
                    ),
                    actor=command.actor,
                    commit=False,
                )
            except ValueError:
                persist_stage = PERSIST_CREATE_ORDER
                raise
            except IntegrityError:
                # create() 내부 flush 실패
                persist_stage = PERSIST_FLUSH_ORDER
                raise

            persist_stage = PERSIST_FLUSH_ORDER
            self._session.flush()

            # 자동매매 signal provenance — 기존 컬럼 재사용
            signal_fp = (
                metadata.get("source_signal_fingerprint")
                or metadata.get("fingerprint")
                or metadata.get("signal_id")
            )
            if signal_fp:
                order.source_signal_fingerprint = str(signal_fp)[:64]
            signal_id_meta = metadata.get("signal_id")
            if signal_id_meta and getattr(order, "source_signal_id", None) is None:
                order.source_signal_id = str(signal_id_meta)[:100]
            strategy_id_meta = metadata.get("strategy_id")
            if strategy_id_meta is not None and getattr(
                order, "strategy_id", None
            ) is None:
                try:
                    order.strategy_id = int(strategy_id_meta)
                except (TypeError, ValueError):
                    pass

            persist_stage = PERSIST_STATUS_PENDING
            order = self._order_repository.change_status(
                entity=order,
                new_status=OrderStatus.PENDING,
                actor=command.actor,
                reason_code="PIPELINE_QUEUED",
                message="Queued via OrderExecutionService",
                commit=False,
            )

            persist_stage = PERSIST_ENQUEUE_OUTBOX
            quote_krw = None
            ref_px = None
            if isinstance(plan_payload, dict):
                quote_krw = plan_payload.get("quote_amount_krw")
                ref_px = plan_payload.get("reference_price")
            if (
                quote_krw is None
                and str(order.broker_code or "").upper() == "UPBIT"
                and str(order.order_type_code or "").upper() == "MARKET"
                and str(order.side_code or "").upper() == "BUY"
                and order.order_price is not None
            ):
                quote_krw = str(order.order_price)
            if ref_px is None and command.reference_price is not None:
                ref_px = str(command.reference_price)
            outbox = self._outbox_repository.enqueue(
                order_id=order.order_id,
                event_type=OutboxEventType.SUBMIT_ORDER,
                idempotency_key=idempotency_key,
                payload_json={
                    # Upbit identifier claim 등 Outbox dispatch에 필요
                    "order_id": order.order_id,
                    "client_order_id": order.client_order_id,
                    "account_id": order.account_id,
                    "user_broker_account_id": (
                        order.user_broker_account_id
                    ),
                    "broker_code": order.broker_code,
                    "environment": environment,
                    "account_type": environment,
                    "external_account_ref": (
                        command.external_account_ref
                    ),
                    "owner_user_id": command.owner_user_id,
                    "arm_token_present": bool(command.arm_token),
                    # STEP 8-5-2 — 사용자 LIVE는 UBA Vault (env 공용 대체 금지)
                    "uses_system_shared_credential": False,
                    "credential_ref": (
                        f"USER_BROKER_ACCOUNT:{order.user_broker_account_id}"
                        if (
                            order.user_broker_account_id is not None
                            and environment == "LIVE"
                        )
                        else None
                    ),
                    "exchange_code": order.exchange_code,
                    "symbol": order.symbol,
                    "side": order.side_code,
                    "order_type": order.order_type_code,
                    "quantity": str(order.order_quantity),
                    "price": (
                        None
                        if order.order_price is None
                        else str(order.order_price)
                    ),
                    # MARKET BUY: price=KRW notional; ticker는 reference_price
                    "quote_amount_krw": quote_krw,
                    "reference_price": ref_px,
                    "time_in_force": order.time_in_force_code,
                },
            )
            persist_stage = PERSIST_COMMIT
            self._session.commit()
            try:
                self._session.refresh(order)
            except Exception:  # noqa: BLE001
                pass
        except Exception as exc:  # noqa: BLE001 — persist 기술 실패는 반환으로 남긴다
            return self._persist_failure(
                stage=persist_stage,
                exc=exc,
                command=command,
                client_order_id=client_order_id,
            )
        finally:
            _daily_fence.__exit__(None, None, None)

        if environment == "LIVE":
            try:
                from stock_platform.order.live_safety_pipeline import (
                    LiveOrderSafetyPipeline,
                )

                # UPBIT MARKET BUY: amount = KRW notional (qty*price 금지)
                if (
                    str(order.broker_code or "").upper() == "UPBIT"
                    and str(order.order_type_code or "").upper()
                    == "MARKET"
                    and str(order.side_code or "").upper() == "BUY"
                    and order.order_price is not None
                ):
                    submitted_amount = Decimal(
                        str(order.order_price)
                    ).quantize(Decimal("0.01"))
                else:
                    submitted_amount = (
                        Decimal(str(order.order_quantity))
                        * Decimal(str(order.order_price or 0))
                    ).quantize(Decimal("0.01"))
                LiveOrderSafetyPipeline(self._session).notify_submitted(
                    decision_detail={
                        "broker_code": order.broker_code,
                        "exchange_code": order.exchange_code,
                        "symbol": order.symbol,
                        "side": order.side_code,
                        "quantity": str(order.order_quantity),
                        "price": (
                            None
                            if order.order_price is None
                            else str(order.order_price)
                        ),
                        "amount": str(submitted_amount),
                        "strategy_id": order.strategy_code,
                        "operator": command.actor,
                    },
                    order_id=order.order_id,
                    client_order_id=order.client_order_id,
                    run_id=(
                        (command.metadata_payload or {}).get("run_id")
                        if isinstance(command.metadata_payload, dict)
                        else None
                    ),
                    actor=command.actor,
                    user_id=command.user_id or command.owner_user_id,
                    account_id=command.user_broker_account_id,
                    strategy_id=order.strategy_code,
                    symbol=order.symbol,
                )
                self._session.commit()
            except Exception:  # noqa: BLE001
                pass

        # LIVE smoke 주문이면 exit monitor submission isolation 자동 acquire (TTL)
        if environment == "LIVE" and uba_id is not None:
            try:
                from stock_platform.position.smoke_exit_isolation import (
                    maybe_acquire_from_order_metadata,
                )

                lease = maybe_acquire_from_order_metadata(
                    user_broker_account_id=int(uba_id),
                    symbol=str(order.symbol),
                    metadata=metadata,
                    environment="LIVE",
                )
                if lease is not None:
                    metadata["smoke_exit_isolation_lease_id"] = lease.lease_id
                    metadata["smoke_exit_isolation_expires_at"] = (
                        lease.expires_at.isoformat()
                    )
                    try:
                        order.metadata_payload = dict(metadata)
                        from sqlalchemy.orm.attributes import flag_modified

                        flag_modified(order, "metadata_payload")
                        self._session.flush()
                    except Exception:  # noqa: BLE001
                        pass
            except Exception:  # noqa: BLE001 — isolation 실패가 주문을 롤백하지 않음
                pass

        # broker submit 경로 진입(Outbox QUEUED) — reservation 유지
        self._pending_submit_release = None
        return OrderExecutionResult(
            allowed=True,
            reason_code="QUEUED",
            order_id=order.order_id,
            outbox_id=outbox.outbox_id,
            status_code=order.status_code,
            client_order_id=order.client_order_id,
            quantity=order.order_quantity,
            price=order.order_price,
            position_plan=plan_payload,
        )

    def enqueue_existing(
        self,
        *,
        order_id: int,
        actor: str = "ORDER_DISPATCHER",
        idempotency_key: str | None = None,
        environment: str = "PAPER",
    ) -> OrderExecutionResult:
        """기존 CREATED 주문을 Outbox에 넣고 PENDING으로 전이한다."""
        order = self._order_repository.get(order_id)
        if order is None:
            raise LookupError("Order not found")

        status = OrderStatus(order.status_code)
        if status == OrderStatus.CREATED:
            order = self._order_repository.change_status(
                entity=order,
                new_status=OrderStatus.PENDING,
                actor=actor,
                reason_code="DISPATCH_REQUESTED",
                commit=False,
            )
        elif status != OrderStatus.PENDING:
            raise ValueError(
                f"Order status not dispatchable: {status.value}"
            )

        key = (
            idempotency_key
            or f"SUBMIT:{order.client_order_id}"
        )
        outbox = self._outbox_repository.enqueue(
            order_id=order.order_id,
            event_type=OutboxEventType.SUBMIT_ORDER,
            idempotency_key=key,
            payload_json={
                "order_id": order.order_id,
                "client_order_id": order.client_order_id,
                "account_id": order.account_id,
                "user_broker_account_id": order.user_broker_account_id,
                "broker_code": order.broker_code,
                "environment": (environment or "PAPER").upper(),
                "exchange_code": order.exchange_code,
                "symbol": order.symbol,
                "side": order.side_code,
                "order_type": order.order_type_code,
                "quantity": str(order.order_quantity),
                "price": (
                    None
                    if order.order_price is None
                    else str(order.order_price)
                ),
                "time_in_force": order.time_in_force_code,
            },
        )
        self._session.commit()
        self._session.refresh(order)
        return OrderExecutionResult(
            allowed=True,
            reason_code="QUEUED",
            order_id=order.order_id,
            outbox_id=outbox.outbox_id,
            status_code=order.status_code,
            client_order_id=order.client_order_id,
            quantity=order.order_quantity,
            price=order.order_price,
        )

    @staticmethod
    def _upbit_market_risk_unit_price(
        *,
        command: OrderExecutionCommand,
        plan_payload: dict[str, Any] | None,
    ) -> Decimal | None:
        """UPBIT MARKET용 risk unit ticker.

        Broker order price와 분리: MARKET SELL은 broker price=None이 정상.
        plan/command의 기존 reference만 재사용 (신규 가격 소스 금지).
        """

        candidates: list[object] = []
        if isinstance(plan_payload, dict):
            candidates.append(plan_payload.get("reference_price"))
        candidates.append(command.reference_price)
        # MARKET SELL: resolve_size가 broker price=None을 반환해도 command.price는
        # 호출자가 넣은 reference ticker일 수 있음
        candidates.append(command.price)
        for raw in candidates:
            if raw in (None, ""):
                continue
            try:
                value = Decimal(str(raw))
            except Exception:  # noqa: BLE001
                continue
            if value > ZERO:
                return value
        return None

    def _resolve_size(
        self,
        command: OrderExecutionCommand,
    ) -> tuple[Decimal, Decimal | None, dict[str, Any] | None]:
        """수량·브로커 price 해석.

        LIMIT: price = unit price
        UPBIT MARKET BUY: price = quote_amount_krw (총 KRW). ticker는 reference 만.
        MARKET SELL: price = None, quantity = volume
        그 외 MARKET(KIWOOM 등): 기존 unit reference price + qty/amount
        """

        side_u = (
            command.side.value
            if hasattr(command.side, "value")
            else str(command.side or "")
        ).upper()
        type_u = (
            command.order_type.value
            if hasattr(command.order_type, "value")
            else str(command.order_type or "")
        ).upper()
        broker_u = str(command.broker_code or "").upper()

        if type_u == "LIMIT":
            if command.price is None or command.price <= 0:
                raise ValueError("LIMIT order requires price > 0")
            price = command.price
            if command.quantity is not None:
                if command.quantity <= 0:
                    raise ValueError("quantity must be greater than zero")
                return command.quantity, price, None
            if command.order_amount is None or command.order_amount <= 0:
                raise ValueError("quantity or order_amount is required")
            # LIMIT + amount → qty from unit price
            plan_payload = self._fixed_amount_plan(
                command, current_price=price
            )
            return (
                plan_payload["qty"],
                price,
                plan_payload["meta"],
            )

        # MARKET — UPBIT BUY만 KRW notional semantics
        if broker_u == "UPBIT" and side_u == "BUY":
            from stock_platform.broker.upbit.rules import (
                UPBIT_MIN_NOTIONAL_KRW,
                round_upbit_krw_notional,
                volume_from_krw_buy_amount,
            )

            reference = command.reference_price or command.price
            krw = command.order_amount
            if krw is None or krw <= 0:
                if (
                    command.quantity is not None
                    and command.quantity > 0
                    and reference is not None
                    and reference > 0
                ):
                    krw = (
                        Decimal(str(command.quantity))
                        * Decimal(str(reference))
                    )
                else:
                    raise ValueError(
                        "MARKET BUY requires order_amount (KRW notional)"
                    )
            krw = round_upbit_krw_notional(Decimal(str(krw)))
            if krw < UPBIT_MIN_NOTIONAL_KRW:
                raise ValueError(
                    f"Upbit minimum order amount is "
                    f"{UPBIT_MIN_NOTIONAL_KRW} KRW (got {krw})"
                )
            if command.quantity is not None and command.quantity > 0:
                qty = command.quantity
            else:
                if reference is None or reference <= 0:
                    raise ValueError(
                        "MARKET BUY requires reference_price "
                        "(or price) for quantity sizing"
                    )
                qty = volume_from_krw_buy_amount(
                    amount=krw, price=Decimal(str(reference))
                )
            meta = {
                "quote_amount_krw": str(krw),
                "reference_price": (
                    None if reference is None else str(reference)
                ),
                "broker_price_semantics": "UPBIT_MARKET_BUY_KRW_NOTIONAL",
            }
            # TradingOrder.order_price / Outbox price = KRW notional
            return qty, krw, meta

        if broker_u == "UPBIT" and side_u == "SELL":
            reference = command.reference_price or command.price
            if command.quantity is None or command.quantity <= 0:
                raise ValueError("MARKET SELL requires quantity > 0")
            return (
                command.quantity,
                None,
                {
                    "reference_price": (
                        None if reference is None else str(reference)
                    ),
                    "broker_price_semantics": "UPBIT_MARKET_SELL_VOLUME_ONLY",
                },
            )

        # KIWOOM 등 — 기존 unit reference + qty/amount
        if command.price is None or command.price <= 0:
            raise ValueError(
                "MARKET order requires reference price for sizing"
            )
        price = command.price
        if command.quantity is not None:
            if command.quantity <= 0:
                raise ValueError("quantity must be greater than zero")
            return command.quantity, price, None
        if command.order_amount is None or command.order_amount <= 0:
            raise ValueError("quantity or order_amount is required")
        plan_payload = self._fixed_amount_plan(
            command, current_price=price
        )
        return (
            plan_payload["qty"],
            price,
            plan_payload["meta"],
        )

    def _fixed_amount_plan(
        self,
        command: OrderExecutionCommand,
        *,
        current_price: Decimal,
    ) -> dict[str, Any]:
        portfolio_value = (
            command.portfolio_value or command.order_amount
        )
        available_cash = (
            command.available_cash or command.order_amount
        )
        policy = RiskPolicy(
            position_sizing_mode=PositionSizingMode.FIXED_AMOUNT,
            risk_per_trade_ratio=Decimal("0.01"),
            stop_loss_ratio=Decimal("0.05"),
            take_profit_ratio=Decimal("0.10"),
            maximum_position_ratio=Decimal("1"),
            maximum_positions=100,
            minimum_order_amount=Decimal("1"),
            fixed_amount=command.order_amount,
        )
        plan = self._sizing_engine.create_position_plan(
            PositionSizingRequest(
                portfolio_value=portfolio_value,
                available_cash=available_cash,
                current_price=current_price,
                current_position_count=(
                    command.current_position_count
                ),
                policy=policy,
            )
        )
        if not plan.approved:
            raise ValueError(plan.reason)
        return {
            "qty": plan.quantity,
            "meta": {
                "approved": plan.approved,
                "reason": plan.reason,
                "quantity": str(plan.quantity),
                "order_amount": str(plan.order_amount),
                "stop_loss_price": str(plan.stop_loss_price),
                "take_profit_price": str(plan.take_profit_price),
            },
        }

    @staticmethod
    def _resolve_account_ownership(
        *,
        account_id: int | None,
        user_broker_account_id: int | None,
    ) -> tuple[int | None, int | None]:
        """Paper XOR LIVE 계좌 소유권.

        LIVE/UBA: paper account_id=None, user_broker_account_id 필수.
        Paper: account_id 필수, user_broker_account_id=None.
        호출자가 UBA id 를 account_id 에 넣어도 LIVE 경로에서는 무시한다.
        """

        if user_broker_account_id is not None:
            if int(user_broker_account_id) <= 0:
                raise ValueError("UBA_REQUIRED")
            return None, int(user_broker_account_id)
        if account_id is None or int(account_id) <= 0:
            raise ValueError("PAPER_ACCOUNT_REQUIRED")
        return int(account_id), None

    def _persist_failure(
        self,
        *,
        stage: str,
        exc: BaseException,
        command: OrderExecutionCommand,
        client_order_id: str | None,
    ) -> OrderExecutionResult:
        """persist 예외 → rollback + 관측 가능한 technical block. 삼키지 않음."""

        reason_code = persist_reason_code_for_stage(stage)
        exception_class = type(exc).__name__
        sanitized = sanitize_persist_error_message(exc)
        frame = persist_error_application_frame(exc)

        try:
            self._session.rollback()
        except Exception:  # noqa: BLE001
            pass

        logger.error(
            "order_persist_failed reason_code=%s failed_stage=%s "
            "exception_class=%s frame=%s client_order_id=%s "
            "broker=%s symbol=%s uba_id=%s message=%s",
            reason_code,
            stage,
            exception_class,
            frame,
            client_order_id,
            command.broker_code,
            command.symbol,
            command.user_broker_account_id,
            sanitized,
        )

        try:
            from stock_platform.order.outbox_fencing import (
                record_outbox_audit,
            )

            record_outbox_audit(
                self._session,
                event_type=reason_code,
                detail={
                    "reason_code": reason_code,
                    "failed_stage": stage,
                    "exception_class": exception_class,
                    "sanitized_message": sanitized,
                    "application_frame": frame,
                    "client_order_id": client_order_id,
                    "broker_code": command.broker_code,
                    "exchange_code": command.exchange_code,
                    "symbol": command.symbol,
                    "user_broker_account_id": (
                        command.user_broker_account_id
                    ),
                    "arm_token_present": bool(command.arm_token),
                },
                actor=command.actor or "ORDER_EXECUTION",
            )
            self._session.commit()
        except Exception:  # noqa: BLE001
            try:
                self._session.rollback()
            except Exception:  # noqa: BLE001
                pass

        return OrderExecutionResult(
            allowed=False,
            reason_code=reason_code,
            order_id=None,
            outbox_id=None,
            status_code=None,
            client_order_id=client_order_id,
            quantity=None,
            price=None,
            failed_stage=stage,
            exception_class=exception_class,
            sanitized_message=sanitized,
            position_plan={
                "failed_stage": stage,
                "exception_class": exception_class,
                "sanitized_message": sanitized,
                "application_frame": frame,
            },
        )
