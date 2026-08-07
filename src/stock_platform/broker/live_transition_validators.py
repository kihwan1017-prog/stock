"""Broker-aware Live Trading Transition validators.

공통 lifecycle(validate→request→approve)은 Service가 유지하고,
환경/계좌 검사는 broker별 Validator로 분리한다.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Protocol

from sqlalchemy.orm import Session

from stock_platform.broker.live_transition_models import (
    LiveTransitionCheckCode,
    LiveTransitionCheckResult,
    LiveTransitionCheckStatus,
    LiveTransitionPlan,
)
from stock_platform.common.settings import get_settings


APPROVAL_PHRASE_BY_BROKER: dict[str, str] = {
    "KIWOOM": "ENABLE KIWOOM LIVE TRADING",
    "UPBIT": "ENABLE UPBIT LIVE TRADING",
}

SUPPORTED_TRANSITION_BROKERS = frozenset(APPROVAL_PHRASE_BY_BROKER)


def approval_phrase_for_broker(broker_code: str) -> str:
    code = str(broker_code or "").strip().upper()
    phrase = APPROVAL_PHRASE_BY_BROKER.get(code)
    if not phrase:
        raise PermissionError(f"Unsupported broker for approval: {code}")
    return phrase


def _bool_check(
    checks: list[LiveTransitionCheckResult],
    code: LiveTransitionCheckCode,
    passed: bool,
    message: str,
    *,
    detail: dict[str, Any] | None = None,
) -> None:
    checks.append(
        LiveTransitionCheckResult(
            code=code,
            status=(
                LiveTransitionCheckStatus.PASS
                if passed
                else LiveTransitionCheckStatus.FAIL
            ),
            message=message,
            detail=dict(detail or {}),
        )
    )


def _common_limit_checks(
    checks: list[LiveTransitionCheckResult],
    *,
    max_order_amount: Decimal,
    max_daily_loss: Decimal,
    paper_validation_approved: bool,
) -> None:
    _bool_check(
        checks,
        LiveTransitionCheckCode.PAPER_VALIDATION_APPROVED,
        paper_validation_approved,
        "Paper validation explicitly approved",
    )
    order_limit_ok = (
        max_order_amount > 0 and max_order_amount <= Decimal("100000")
    )
    checks.append(
        LiveTransitionCheckResult(
            code=LiveTransitionCheckCode.MAX_ORDER_LIMIT_VALID,
            status=(
                LiveTransitionCheckStatus.PASS
                if order_limit_ok
                else LiveTransitionCheckStatus.FAIL
            ),
            message=(
                "Initial live order limit must be between 1 and 100,000 KRW"
            ),
            detail={"max_order_amount": str(max_order_amount)},
        )
    )
    daily_loss_ok = (
        max_daily_loss > 0 and max_daily_loss <= Decimal("300000")
    )
    checks.append(
        LiveTransitionCheckResult(
            code=LiveTransitionCheckCode.DAILY_LOSS_LIMIT_VALID,
            status=(
                LiveTransitionCheckStatus.PASS
                if daily_loss_ok
                else LiveTransitionCheckStatus.FAIL
            ),
            message=(
                "Initial live daily loss limit must be "
                "between 1 and 300,000 KRW"
            ),
            detail={"max_daily_loss": str(max_daily_loss)},
        )
    )
    checks.append(
        LiveTransitionCheckResult(
            code=LiveTransitionCheckCode.MANUAL_APPROVAL_REQUIRED,
            status=LiveTransitionCheckStatus.WARNING,
            message=(
                "Validation alone never enables live trading. "
                "A separate approval phrase is required."
            ),
            detail={},
        )
    )


def _finalize_plan(
    checks: list[LiveTransitionCheckResult],
    *,
    max_order_amount: Decimal,
    max_daily_loss: Decimal,
    broker_code: str,
    scope: str,
    user_broker_account_id: int | None,
) -> LiveTransitionPlan:
    ready = all(
        item.status != LiveTransitionCheckStatus.FAIL for item in checks
    )
    return LiveTransitionPlan(
        ready=ready,
        generated_at=datetime.now(timezone.utc),
        max_order_amount=max_order_amount,
        max_daily_loss=max_daily_loss,
        checks=checks,
        broker_code=str(broker_code).upper(),
        scope=str(scope).upper(),
        user_broker_account_id=user_broker_account_id,
    )


class LiveTradingTransitionValidator(Protocol):
    def validate(
        self,
        *,
        max_order_amount: Decimal,
        max_daily_loss: Decimal,
        paper_validation_approved: bool,
        scope: str,
        user_broker_account_id: int | None,
    ) -> LiveTransitionPlan: ...


class KiwoomLiveTransitionValidator:
    """기존 KIWOOM BROKER/ACCOUNT 검증 — 회귀 유지."""

    def __init__(self, session: Session | None = None) -> None:
        self._session = session

    def validate(
        self,
        *,
        max_order_amount: Decimal,
        max_daily_loss: Decimal,
        paper_validation_approved: bool,
        scope: str = "BROKER",
        user_broker_account_id: int | None = None,
    ) -> LiveTransitionPlan:
        settings = get_settings()
        checks: list[LiveTransitionCheckResult] = []
        scope_u = str(scope or "BROKER").strip().upper()

        _bool_check(
            checks,
            LiveTransitionCheckCode.GLOBAL_LIVE_ORDER_ENABLED,
            settings.global_live_order_enabled is True,
            "GLOBAL_LIVE_ORDER_ENABLED=true",
        )
        _bool_check(
            checks,
            LiveTransitionCheckCode.MOCK_MODE_DISABLED,
            settings.kiwoom_use_mock is False,
            "KIWOOM_USE_MOCK=false",
        )
        _bool_check(
            checks,
            LiveTransitionCheckCode.LIVE_ORDER_ENABLED,
            settings.kiwoom_live_order_enabled is True,
            "KIWOOM_LIVE_ORDER_ENABLED=true",
        )
        _bool_check(
            checks,
            LiveTransitionCheckCode.ACCOUNT_NUMBER_PRESENT,
            bool(settings.kiwoom_account_number.strip()),
            "KIWOOM_ACCOUNT_NUMBER configured",
        )
        _bool_check(
            checks,
            LiveTransitionCheckCode.APP_CREDENTIALS_PRESENT,
            bool(settings.kiwoom_app_key.strip())
            and bool(settings.kiwoom_secret_key.strip()),
            "Kiwoom application credentials configured",
        )
        _bool_check(
            checks,
            LiveTransitionCheckCode.WEBSOCKET_CONFIGURED,
            bool(settings.kiwoom_order_ws_subscribe_json.strip()),
            "Kiwoom order WebSocket subscription configured",
        )
        _bool_check(
            checks,
            LiveTransitionCheckCode.RECOVERY_TRADING_DISABLED,
            settings.kiwoom_recovery_start_trading is False,
            (
                "Automatic strategy/order start remains disabled "
                "during initial live validation"
            ),
        )
        if scope_u == "ACCOUNT":
            _bool_check(
                checks,
                LiveTransitionCheckCode.SCOPE_ACCOUNT_REQUIRED,
                user_broker_account_id is not None
                and int(user_broker_account_id) > 0,
                "ACCOUNT scope requires user_broker_account_id",
            )
        _common_limit_checks(
            checks,
            max_order_amount=max_order_amount,
            max_daily_loss=max_daily_loss,
            paper_validation_approved=paper_validation_approved,
        )
        return _finalize_plan(
            checks,
            max_order_amount=max_order_amount,
            max_daily_loss=max_daily_loss,
            broker_code="KIWOOM",
            scope=scope_u,
            user_broker_account_id=user_broker_account_id,
        )


class UpbitLiveTransitionValidator:
    """UPBIT ACCOUNT scope — KIWOOM 설정과 완전 독립."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def validate(
        self,
        *,
        max_order_amount: Decimal,
        max_daily_loss: Decimal,
        paper_validation_approved: bool,
        scope: str = "ACCOUNT",
        user_broker_account_id: int | None = None,
    ) -> LiveTransitionPlan:
        settings = get_settings()
        checks: list[LiveTransitionCheckResult] = []
        scope_u = str(scope or "ACCOUNT").strip().upper()

        # UPBIT Activation은 ACCOUNT 강제
        account_scope_ok = scope_u == "ACCOUNT" and (
            user_broker_account_id is not None
            and int(user_broker_account_id) > 0
        )
        _bool_check(
            checks,
            LiveTransitionCheckCode.SCOPE_ACCOUNT_REQUIRED,
            account_scope_ok,
            "UPBIT activation requires scope=ACCOUNT and UBA id",
        )

        _bool_check(
            checks,
            LiveTransitionCheckCode.GLOBAL_LIVE_ORDER_ENABLED,
            settings.global_live_order_enabled is True,
            "GLOBAL_LIVE_ORDER_ENABLED=true",
        )
        _bool_check(
            checks,
            LiveTransitionCheckCode.LIVE_ORDER_ENABLED,
            settings.upbit_live_order_enabled is True,
            "UPBIT_LIVE_ORDER_ENABLED=true",
        )
        _bool_check(
            checks,
            LiveTransitionCheckCode.MOCK_MODE_DISABLED,
            settings.upbit_use_mock is False,
            "UPBIT_USE_MOCK=false",
        )

        uba = None
        uba_id = (
            int(user_broker_account_id)
            if user_broker_account_id is not None
            else None
        )
        if uba_id is not None:
            from stock_platform.trading.account_models import (
                UserBrokerAccount,
            )

            uba = self._session.get(UserBrokerAccount, uba_id)

        _bool_check(
            checks,
            LiveTransitionCheckCode.UBA_EXISTS,
            uba is not None,
            "UBA exists",
            detail={"user_broker_account_id": uba_id},
        )
        broker_ok = bool(
            uba is not None
            and str(getattr(uba, "broker_code", "") or "").upper() == "UPBIT"
        )
        _bool_check(
            checks,
            LiveTransitionCheckCode.UBA_BROKER_MATCH,
            broker_ok,
            "UBA broker_code=UPBIT",
        )
        active_ok = bool(
            uba is not None
            and bool(getattr(uba, "is_active", False))
            and getattr(uba, "deleted_at", None) is None
        )
        _bool_check(
            checks,
            LiveTransitionCheckCode.UBA_ACTIVE,
            active_ok,
            "UBA is_active and not deleted",
        )
        conn = (
            str(getattr(uba, "connection_status", "") or "").upper()
            if uba is not None
            else ""
        )
        _bool_check(
            checks,
            LiveTransitionCheckCode.CONNECTION_CONNECTED,
            conn == "CONNECTED",
            "connection_status=CONNECTED",
            detail={"connection_status": conn or None},
        )

        # Credential
        cred_present = False
        cred_verified = False
        if uba_id is not None:
            try:
                from stock_platform.broker.credential_vault_service import (
                    BrokerCredentialVaultService,
                )

                st = BrokerCredentialVaultService(self._session).status(
                    int(uba_id)
                )
                ver = str(
                    getattr(st, "verification_status", None) or ""
                ).upper()
                cred_verified = ver == "VERIFIED"
                cred_present = bool(getattr(st, "is_active", False)) or bool(
                    getattr(st, "connected", False)
                ) or bool(ver)
            except Exception:  # noqa: BLE001
                cred_present = False
                cred_verified = False
        _bool_check(
            checks,
            LiveTransitionCheckCode.CREDENTIAL_PRESENT,
            cred_present,
            "Active credential present",
        )
        _bool_check(
            checks,
            LiveTransitionCheckCode.CREDENTIAL_VERIFIED,
            cred_verified,
            "Credential verification_status=VERIFIED",
        )

        # Recovery / trading_paused — 공통 gate 재사용
        trading_paused = False
        recovery_status = ""
        recovery_ok = False
        if uba_id is not None:
            try:
                from stock_platform.trading.runtime_control_gates import (
                    assert_recovery_ready,
                )

                class _GateErr(Exception):
                    def __init__(self, code: str, message: str):
                        self.code = code
                        self.message = message
                        super().__init__(message)

                try:
                    info = assert_recovery_ready(
                        self._session,
                        int(uba_id),
                        raise_error=lambda c, m: _GateErr(c, m),
                    )
                    trading_paused = bool(info.get("trading_paused"))
                    recovery_status = str(
                        info.get("recovery_status") or ""
                    ).upper()
                    recovery_ok = not trading_paused
                except _GateErr as exc:
                    trading_paused = exc.code == "trading_paused"
                    recovery_status = exc.message
                    recovery_ok = False
            except Exception:  # noqa: BLE001
                trading_paused = True
                recovery_status = "LOOKUP_FAILED"
                recovery_ok = False
        _bool_check(
            checks,
            LiveTransitionCheckCode.TRADING_NOT_PAUSED,
            (uba_id is not None) and (not trading_paused),
            "trading_paused=false",
            detail={"trading_paused": trading_paused},
        )
        _bool_check(
            checks,
            LiveTransitionCheckCode.RECOVERY_STATUS_OK,
            recovery_ok,
            "recovery_status normal",
            detail={"recovery_status": recovery_status or None},
        )

        # Conflicts
        conflicts = 0
        if uba_id is not None:
            try:
                from stock_platform.broker.recovery_conflict_service import (
                    BrokerRecoveryConflictService,
                )

                conflicts = int(
                    BrokerRecoveryConflictService(
                        self._session
                    ).count_active_for_uba(int(uba_id))
                )
            except Exception:  # noqa: BLE001
                conflicts = -1
        _bool_check(
            checks,
            LiveTransitionCheckCode.NO_ACTIVE_CONFLICTS,
            conflicts == 0,
            "active recovery conflicts=0",
            detail={"active_conflicts": conflicts},
        )

        # Kill switch
        ks_off = False
        if uba is not None:
            try:
                from stock_platform.risk_engine.kill_switch_service import (
                    KillSwitchService,
                )
                from stock_platform.trading.account_identity import (
                    uba_kill_switch_scope,
                )

                ks = KillSwitchService(self._session)
                scopes = [
                    KillSwitchService.GLOBAL_SCOPE,
                    uba_kill_switch_scope(int(uba.user_broker_account_id)),
                    f"USER:{int(uba.user_id)}",
                ]
                ks_off = not bool(ks.is_active_for_scopes(scopes))
            except Exception:  # noqa: BLE001
                ks_off = False
        _bool_check(
            checks,
            LiveTransitionCheckCode.KILL_SWITCH_OFF,
            ks_off,
            "Kill Switch OFF (GLOBAL/USER/UBA)",
        )

        # account_paused — 공통 gate 재사용
        account_paused = True
        if uba is not None:
            try:
                from stock_platform.trading.runtime_control_gates import (
                    assert_risk_account_not_paused,
                )

                class _RiskErr(Exception):
                    pass

                try:
                    assert_risk_account_not_paused(
                        self._session,
                        uba,
                        raise_error=lambda _c, m: _RiskErr(m),
                    )
                    account_paused = False
                except _RiskErr:
                    account_paused = True
            except Exception:  # noqa: BLE001
                account_paused = True
        _bool_check(
            checks,
            LiveTransitionCheckCode.ACCOUNT_NOT_PAUSED,
            not account_paused,
            "account_paused=false",
        )

        # db_open
        db_open = -1
        if uba_id is not None:
            try:
                from stock_platform.broker.recovery_conflict_service import (
                    BrokerRecoveryConflictService,
                )

                blocking = BrokerRecoveryConflictService(
                    self._session
                ).count_blocking_orders_for_uba(int(uba_id))
                db_open = int(blocking.get("db_open") or 0)
            except Exception:  # noqa: BLE001
                db_open = -1
        _bool_check(
            checks,
            LiveTransitionCheckCode.NO_DB_OPEN_ORDERS,
            db_open == 0,
            "db_open_orders=0",
            detail={"db_open": db_open},
        )

        # Activation 시점: LIVE/ARM OFF·Scheduler PAUSE는 허용(경고만)
        # — LIVE ON 게이트와 분리 (기존 lifecycle 유지)
        checks.append(
            LiveTransitionCheckResult(
                code=LiveTransitionCheckCode.ACTIVATION_LIFECYCLE_NOTE,
                status=LiveTransitionCheckStatus.WARNING,
                message=(
                    "Activation does not enable LIVE/ARM; "
                    "Scheduler should remain PAUSE until explicit enable"
                ),
                detail={},
            )
        )

        _common_limit_checks(
            checks,
            max_order_amount=max_order_amount,
            max_daily_loss=max_daily_loss,
            paper_validation_approved=paper_validation_approved,
        )
        return _finalize_plan(
            checks,
            max_order_amount=max_order_amount,
            max_daily_loss=max_daily_loss,
            broker_code="UPBIT",
            scope=scope_u,
            user_broker_account_id=uba_id,
        )


def resolve_broker_for_transition(
    session: Session,
    *,
    scope: str,
    broker_code: str | None,
    user_broker_account_id: int | None,
) -> tuple[str, str, int | None]:
    """UBA가 있으면 DB broker를 신뢰. 클라이언트 broker만 믿지 않음."""

    scope_u = str(scope or "BROKER").strip().upper() or "BROKER"
    client_broker = str(broker_code or "").strip().upper() or None
    uba_id = (
        int(user_broker_account_id)
        if user_broker_account_id is not None
        else None
    )

    if scope_u == "ACCOUNT":
        if uba_id is None or uba_id <= 0:
            raise PermissionError(
                "ACCOUNT scope requires user_broker_account_id"
            )
        from stock_platform.trading.account_models import UserBrokerAccount

        uba = session.get(UserBrokerAccount, uba_id)
        if uba is None:
            raise PermissionError(f"UBA not found: {uba_id}")
        db_broker = str(uba.broker_code or "").strip().upper()
        if db_broker not in SUPPORTED_TRANSITION_BROKERS:
            raise PermissionError(
                f"Unsupported UBA broker for transition: {db_broker}"
            )
        if client_broker and client_broker != db_broker:
            raise PermissionError(
                f"broker_code mismatch: client={client_broker} uba={db_broker}"
            )
        return db_broker, scope_u, uba_id

    # BROKER scope — 기본 KIWOOM (레거시)
    resolved = client_broker or "KIWOOM"
    if resolved not in SUPPORTED_TRANSITION_BROKERS:
        raise PermissionError(f"Unsupported broker: {resolved}")
    if resolved == "UPBIT":
        # UPBIT는 ACCOUNT만 허용
        raise PermissionError(
            "UPBIT live transition requires scope=ACCOUNT and UBA id"
        )
    return resolved, scope_u, uba_id


def build_validator(
    session: Session,
    broker_code: str,
) -> LiveTradingTransitionValidator:
    code = str(broker_code or "").strip().upper()
    if code == "KIWOOM":
        return KiwoomLiveTransitionValidator(session)
    if code == "UPBIT":
        return UpbitLiveTransitionValidator(session)
    raise PermissionError(f"Unsupported broker validator: {code}")
