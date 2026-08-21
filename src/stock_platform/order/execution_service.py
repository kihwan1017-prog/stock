from __future__ import annotations

import logging
import re
import traceback
from dataclasses import dataclass
from decimal import Decimal
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
                    reference_price=command.reference_price,
                    require_arm=True,
                    # KIWOOM LIMIT tick 검증 — 주문 유형을 파이프라인에 전달
                    order_type=(
                        command.order_type.value
                        if hasattr(command.order_type, "value")
                        else str(command.order_type or "")
                    ),
                )
                if not safety.allowed:
                    return self._blocked(safety.reason_code)

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
                price=price,
                user_id=command.user_id or command.owner_user_id,
                user_broker_account_id=uba_id,
                order_source=command.order_source,
                # 서버가 보유·pending으로 EXIT 재분류 — 클라이언트 플래그 미신뢰
                is_risk_reducing=command.is_risk_reducing,
                environment=environment,
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
        persist_stage = PERSIST_CREATE_ORDER
        try:
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

        if environment == "LIVE":
            try:
                from stock_platform.order.live_safety_pipeline import (
                    LiveOrderSafetyPipeline,
                )

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
                        "amount": str(
                            (
                                Decimal(str(order.order_quantity))
                                * Decimal(str(order.order_price or 0))
                            ).quantize(Decimal("0.01"))
                        ),
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

    def _resolve_size(
        self,
        command: OrderExecutionCommand,
    ) -> tuple[Decimal, Decimal, dict[str, Any] | None]:
        if command.order_type == OrderType.LIMIT:
            if command.price is None or command.price <= 0:
                raise ValueError("LIMIT order requires price > 0")
            price = command.price
        else:
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
            raise ValueError(
                "quantity or order_amount is required"
            )

        portfolio_value = (
            command.portfolio_value
            or command.order_amount
        )
        available_cash = (
            command.available_cash
            or command.order_amount
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
                current_price=price,
                current_position_count=(
                    command.current_position_count
                ),
                policy=policy,
            )
        )
        if not plan.approved:
            raise ValueError(plan.reason)

        return (
            plan.quantity,
            price,
            {
                "approved": plan.approved,
                "reason": plan.reason,
                "quantity": str(plan.quantity),
                "order_amount": str(plan.order_amount),
                "stop_loss_price": str(plan.stop_loss_price),
                "take_profit_price": str(
                    plan.take_profit_price
                ),
            },
        )

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

    @staticmethod
    def _blocked(
        reason_code: str,
        *,
        message: str | None = None,
    ) -> OrderExecutionResult:
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
