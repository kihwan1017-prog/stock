"""24H Unattended LIVE authorization — operator lease + gated renewal.

Fail-closed: 무제한 TTL/Kill 우회 금지.
자동 renewal은 safety gate 전부 PASS일 때만.
"""

from __future__ import annotations

import hashlib
import secrets
import threading
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.broker.live_transition_entities import (
    LiveTradingTransitionEntity,
)
from stock_platform.broker.live_transition_service import (
    LiveTradingTransitionService,
)
from stock_platform.common.settings import get_settings
from stock_platform.order.live_safety_audit import (
    emit_live_order_telegram,
    emit_live_safety_audit,
)
from stock_platform.trading.account_models import UserBrokerAccount
from stock_platform.trading.live_session_expiry import (
    activation_remaining_seconds,
    aware_utc,
)
from stock_platform.trading.live_unattended_entities import (
    LiveUnattendedAuthorizationEntity,
)
from stock_platform.common.logger import logger
from stock_platform.database.session import get_session_factory

STATUS_ACTIVE = "ACTIVE"
STATUS_EXPIRED = "EXPIRED"
STATUS_REVOKED = "REVOKED"
STATUS_PROTECTIVE = "PROTECTIVE_EXIT_ONLY"

CONFIRM_ENABLE = "ENABLE 24H UNATTENDED"
CONFIRM_DISABLE = "DISABLE 24H UNATTENDED"

# Unattended 전용 승인 모델 — LIVE ON approval_phrase 와 역할 분리
APPROVAL_MODEL_UNATTENDED_LEASE = "UNATTENDED_LEASE_ACK"
SOURCE_ADMIN_UI = "ADMIN_UI"
SOURCE_ADMIN_API = "ADMIN_API"
ALLOWED_ENABLE_SOURCES = frozenset({SOURCE_ADMIN_UI, SOURCE_ADMIN_API})
_OK_RECOVERY_STRICT = frozenset({"SUCCESS", "READY"})
_HIGH_CONFLICT_LEVELS = frozenset({"HIGH", "CRITICAL"})

ACTOR_HORIZON_AUTO_RENEW = "SYSTEM_UNATTENDED_AUTO_RENEW"
HORIZON_RENEW_SUCCESS_TELEGRAM_INTERVAL_SECONDS = 86400
HORIZON_RENEW_FAILURE_TELEGRAM_COOLDOWN_SECONDS = 3600

_READINESS_BLOCKERS_FOR_HORIZON_RENEW = frozenset(
    {
        "RUNTIME_BLOCKED",
        "STRATEGY_RUNTIME_NOT_RUNNING",
        "MARKET_FEED_UNHEALTHY",
        "AUTO_EXIT_QUOTE_STALE",
        "CONFLICT_ACTIVE",
        "LIVE_OUTBOX_WORKER_DISABLED",
        "LIVE_OUTBOX_WORKER_NOT_RUNNING",
        "LIVE_EXECUTION_RUNNER_NOT_RUNNING",
        "ENTRY_EVALUATOR_STALE",
        "RISK_POLICY_MISSING",
        "LIVE_NOT_APPROVED",
        "ACTIVATION_INACTIVE",
        "LIVE_OFF",
        "ARM_OFF_OR_EXPIRED",
    }
)

_HORIZON_RENEW_LOCKS: dict[int, threading.Lock] = {}
_HORIZON_RENEW_GUARD = threading.Lock()


class LiveUnattendedError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _hash_phrase(phrase: str) -> str:
    return hashlib.sha256(phrase.encode("utf-8")).hexdigest()


def _horizon_renew_lock(uba_id: int) -> threading.Lock:
    with _HORIZON_RENEW_GUARD:
        lock = _HORIZON_RENEW_LOCKS.get(int(uba_id))
        if lock is None:
            lock = threading.Lock()
            _HORIZON_RENEW_LOCKS[int(uba_id)] = lock
        return lock


class LiveUnattendedAuthorizationService:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get_active(
        self, user_broker_account_id: int
    ) -> LiveUnattendedAuthorizationEntity | None:
        return self._session.scalar(
            select(LiveUnattendedAuthorizationEntity)
            .where(
                LiveUnattendedAuthorizationEntity.user_broker_account_id
                == int(user_broker_account_id),
                LiveUnattendedAuthorizationEntity.enabled.is_(True),
                LiveUnattendedAuthorizationEntity.status_code.in_(
                    (STATUS_ACTIVE, STATUS_PROTECTIVE)
                ),
            )
            .order_by(
                LiveUnattendedAuthorizationEntity.live_unattended_authorization_id.desc()
            )
            .limit(1)
        )

    def status_dict(self, user_broker_account_id: int) -> dict[str, Any]:
        uba = self._session.get(
            UserBrokerAccount, int(user_broker_account_id)
        )
        broker = (
            str(uba.broker_code or "").upper() if uba is not None else None
        )
        phrase_meta = self._required_phrase_meta(broker)
        row = self.get_active(int(user_broker_account_id))
        now = _now()
        if row is None:
            return {
                "unattended_enabled": False,
                "entry_lease_active": False,
                "needs_reauthorize": True,
                "status_code": "OFF",
                "broker_code": broker,
                "authorized_until": None,
                "remaining_seconds": 0,
                "entry_authorized": False,
                "protective_exit_authorized": False,
                "last_renewed_at": None,
                "last_renewal_actor": None,
                **phrase_meta,
            }
        until = aware_utc(row.authorized_until)
        remaining = (
            max(0, int((until - now).total_seconds())) if until else 0
        )
        status_u = str(row.status_code or "").upper()
        entry_lease_active = (
            bool(row.enabled)
            and status_u == STATUS_ACTIVE
            and bool(row.entry_authorized)
            and remaining > 0
        )
        needs_reauthorize = not entry_lease_active
        return {
            # UI/게이트: PROTECTIVE·만료는 '무인 ENTRY 세션 ON'이 아님
            "unattended_enabled": entry_lease_active,
            "entry_lease_active": entry_lease_active,
            "needs_reauthorize": needs_reauthorize,
            "status_code": row.status_code,
            "broker_code": broker or str(row.broker_code or "").upper(),
            "authorization_id": int(row.live_unattended_authorization_id),
            "authorized_until": until.isoformat() if until else None,
            "remaining_seconds": remaining,
            "entry_authorized": bool(row.entry_authorized),
            "protective_exit_authorized": bool(
                row.protective_exit_authorized
            ),
            "renewal_interval_seconds": int(row.renewal_interval_seconds),
            "renewal_margin_seconds": int(row.renewal_margin_seconds),
            "arm_lease_ttl_seconds": int(row.arm_lease_ttl_seconds),
            "last_renewed_at": (
                aware_utc(row.last_renewed_at).isoformat()
                if row.last_renewed_at
                else None
            ),
            "last_renewal_actor": row.last_renewal_actor,
            "last_renewal_detail": dict(row.last_renewal_detail or {}),
            "auto_renew_enabled": bool(getattr(row, "auto_renew_enabled", False)),
            "horizon_renew_margin_seconds": self._horizon_renew_margin_seconds(
                row
            ),
            "next_horizon_renew_check_at": self._next_horizon_renew_check_at(
                row, until=until, now=now
            ),
            "last_horizon_auto_renew": self._last_horizon_auto_renew_summary(
                row
            ),
            "approved_by": row.approved_by,
            "approved_at": (
                aware_utc(row.approved_at).isoformat()
                if row.approved_at
                else None
            ),
            **phrase_meta,
        }

    @staticmethod
    def _required_phrase_meta(broker_code: str | None) -> dict[str, Any]:
        """UI/API SoT — Unattended lease ACK vs LIVE ON phrase 역할 분리."""

        return {
            "approval_model": APPROVAL_MODEL_UNATTENDED_LEASE,
            "required_confirmation_text": CONFIRM_ENABLE,
            "required_confirmation_text_disable": CONFIRM_DISABLE,
            "requires_live_approval_phrase": False,
            "required_approval_phrase": None,
            "approval_phrase_note": (
                "24H Unattended Enable no longer accepts LIVE approval_phrase. "
                "It authorizes limited unattended operation on an already "
                "approved LIVE session. LIVE ON still requires its own "
                "broker approval phrase on LIVE transition APIs. "
                f"Unattended confirmation_text must be '{CONFIRM_ENABLE}'. "
                f"broker={broker_code or 'UNKNOWN'}"
            ),
        }

    def enable(
        self,
        user_broker_account_id: int,
        *,
        actor: str,
        confirmation_text: str,
        reason: str,
        source: str = SOURCE_ADMIN_API,
        horizon_hours: int | None = None,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        """이미 승인된 LIVE 세션에 대한 제한된 unattended lease 승인.

        LIVE ON approval_phrase 검증은 이 API에서 수행하지 않는다
        (LIVE transition 경로에서만 유지).
        """

        text_u = (confirmation_text or "").strip().upper()
        if not secrets.compare_digest(text_u, CONFIRM_ENABLE):
            raise LiveUnattendedError(
                "CONFIRMATION_REQUIRED",
                f"confirmation_text must be exactly '{CONFIRM_ENABLE}'",
            )
        source_u = str(source or "").strip().upper()
        if source_u not in ALLOWED_ENABLE_SOURCES:
            raise LiveUnattendedError(
                "INVALID_SOURCE",
                f"source must be one of {sorted(ALLOWED_ENABLE_SOURCES)}",
            )

        uba = self._session.get(
            UserBrokerAccount, int(user_broker_account_id)
        )
        if uba is None:
            raise LiveUnattendedError("UBA_NOT_FOUND", "UBA not found")
        broker = str(uba.broker_code or "").upper()
        if broker != "UPBIT":
            raise LiveUnattendedError(
                "BROKER_NOT_SUPPORTED",
                "24H unattended is UPBIT-only in this release",
            )

        settings = get_settings()
        default_h = int(
            getattr(settings, "live_unattended_default_horizon_hours", 24)
        )
        max_h = int(
            getattr(settings, "live_unattended_max_horizon_hours", 168)
        )
        hours = int(horizon_hours if horizon_hours is not None else default_h)
        if hours < 1 or hours > max_h:
            raise LiveUnattendedError(
                "INVALID_HORIZON",
                f"horizon_hours must be 1..{max_h}",
            )

        gates = self.evaluate_enable_gates(int(user_broker_account_id))
        if not gates["ok"]:
            raise LiveUnattendedError(
                "SAFETY_GATES_FAILED",
                f"Cannot enable unattended: {gates['blockers']}",
            )

        existing = self.get_active(int(user_broker_account_id))
        if existing is not None:
            raise LiveUnattendedError(
                "ALREADY_ENABLED",
                "Active unattended authorization already exists",
            )

        act = LiveTradingTransitionService(self._session).peek_active(
            broker_code=broker,
            user_broker_account_id=int(user_broker_account_id),
        )
        now = _now()
        act_expires = (
            aware_utc(act.expires_at).isoformat()
            if act is not None and act.expires_at is not None
            else None
        )
        row = LiveUnattendedAuthorizationEntity(
            user_broker_account_id=int(user_broker_account_id),
            broker_code=broker,
            status_code=STATUS_ACTIVE,
            enabled=True,
            entry_authorized=True,
            protective_exit_authorized=True,
            auto_renew_enabled=False,
            authorized_until=now + timedelta(hours=hours),
            renewal_interval_seconds=int(
                getattr(settings, "live_unattended_renewal_interval_seconds", 3600)
            ),
            renewal_margin_seconds=int(
                getattr(settings, "live_unattended_renewal_margin_seconds", 600)
            ),
            arm_lease_ttl_seconds=int(
                getattr(settings, "live_unattended_arm_lease_ttl_seconds", 3600)
            ),
            activation_renew_hours=int(
                getattr(settings, "live_unattended_activation_renew_hours", 8)
            ),
            max_authorization_horizon_hours=max_h,
            approved_by=actor[:100],
            approved_at=now,
            approval_reason=(reason or "")[:2000],
            # Unattended lease ACK 해시 (LIVE phrase 아님)
            approval_phrase_hash=_hash_phrase(
                f"{APPROVAL_MODEL_UNATTENDED_LEASE}:{CONFIRM_ENABLE}"
            ),
            source_activation_id=(
                int(act.live_trading_transition_id) if act is not None else None
            ),
            last_renewal_detail={
                "correlation_id": (correlation_id or "")[:128],
                "source": source_u,
                "approval_model": APPROVAL_MODEL_UNATTENDED_LEASE,
                "gates": gates,
            },
        )
        self._session.add(row)
        self._session.flush()
        emit_live_safety_audit(
            self._session,
            event_type="UNATTENDED_AUTHORIZATION_ENABLED",
            actor=actor,
            run_id=None,
            user_id=int(uba.user_id),
            account_id=int(user_broker_account_id),
            strategy_id=None,
            detail={
                "actor": actor,
                "user_broker_account_id": int(user_broker_account_id),
                "broker": broker,
                "enabled_at": now.isoformat(),
                "authorization_horizon_hours": hours,
                "authorized_until": row.authorized_until.isoformat(),
                "live_state": gates.get("live"),
                "arm_state": gates.get("arm"),
                "activation_id": gates.get("activation_id"),
                "activation_expires_at": act_expires,
                "reason": (reason or "")[:500],
                "source": source_u,
                "approval_model": APPROVAL_MODEL_UNATTENDED_LEASE,
                "authorization_id": int(row.live_unattended_authorization_id),
                "execution_env": gates.get("execution_env"),
            },
            commit=False,
        )
        emit_live_order_telegram(
            event_type="UNATTENDED_AUTHORIZATION_ENABLED",
            title="24H Unattended ON",
            message=f"UBA {user_broker_account_id} unattended until {row.authorized_until.isoformat()}",
            detail={"authorization_id": row.live_unattended_authorization_id},
        )
        self._session.commit()
        self._session.refresh(row)
        return self.status_dict(int(user_broker_account_id))

    def reauthorize(
        self,
        user_broker_account_id: int,
        *,
        actor: str,
        confirmation_text: str,
        reason: str,
        source: str = SOURCE_ADMIN_API,
        horizon_hours: int | None = None,
        correlation_id: str | None = None,
    ) -> dict[str, Any]:
        """만료/PROTECTIVE 이후 24H lease 재승인 + LIVE/ARM/Activation 복구.

        enable()과 달리 LIVE/ARM이 꺼진 fail-closed 상태에서도
        restore-grade safety gate만 PASS하면 새 lease를 만들고
        restore_from_active_lease로 세션을 복구한다.
        """

        text_u = (confirmation_text or "").strip().upper()
        if not secrets.compare_digest(text_u, CONFIRM_ENABLE):
            raise LiveUnattendedError(
                "CONFIRMATION_REQUIRED",
                f"confirmation_text must be exactly '{CONFIRM_ENABLE}'",
            )
        source_u = str(source or "").strip().upper()
        if source_u not in ALLOWED_ENABLE_SOURCES:
            raise LiveUnattendedError(
                "INVALID_SOURCE",
                f"source must be one of {sorted(ALLOWED_ENABLE_SOURCES)}",
            )

        uba = self._session.get(
            UserBrokerAccount, int(user_broker_account_id)
        )
        if uba is None:
            raise LiveUnattendedError("UBA_NOT_FOUND", "UBA not found")
        broker = str(uba.broker_code or "").upper()
        if broker != "UPBIT":
            raise LiveUnattendedError(
                "BROKER_NOT_SUPPORTED",
                "24H unattended is UPBIT-only in this release",
            )

        settings = get_settings()
        default_h = int(
            getattr(settings, "live_unattended_default_horizon_hours", 24)
        )
        max_h = int(
            getattr(settings, "live_unattended_max_horizon_hours", 168)
        )
        hours = int(horizon_hours if horizon_hours is not None else default_h)
        if hours < 1 or hours > max_h:
            raise LiveUnattendedError(
                "INVALID_HORIZON",
                f"horizon_hours must be 1..{max_h}",
            )

        # LIVE/ARM/Activation 꺼짐은 허용 — Kill/Credential/Recovery 등만 강제
        gates = self.evaluate_restore_gates(int(user_broker_account_id))
        if not gates["ok"]:
            raise LiveUnattendedError(
                "SAFETY_GATES_FAILED",
                f"Cannot reauthorize unattended: {gates['blockers']}",
            )

        existing = self.get_active(int(user_broker_account_id))
        now = _now()
        previous_authorization_id = None
        source_activation_id = None
        preserve_auto_renew = False
        if existing is not None:
            preserve_auto_renew = bool(
                getattr(existing, "auto_renew_enabled", False)
            )
            previous_authorization_id = int(
                existing.live_unattended_authorization_id
            )
            if existing.source_activation_id is not None:
                source_activation_id = int(existing.source_activation_id)
            status_u = str(existing.status_code or "").upper()
            until = aware_utc(existing.authorized_until)
            still_active = (
                status_u == STATUS_ACTIVE
                and bool(existing.entry_authorized)
                and until is not None
                and until > now
            )
            if still_active and bool(uba.live_order_enabled) and bool(
                uba.live_armed
            ):
                raise LiveUnattendedError(
                    "ALREADY_ENABLED",
                    "Active unattended authorization already exists",
                )
            # PROTECTIVE/만료·세션 OFF: 기존 lease supersede (fail-closed 재실행 없음)
            existing.enabled = False
            existing.entry_authorized = False
            existing.status_code = STATUS_EXPIRED
            existing.revoked_at = now
            existing.revoked_by = actor[:100]
            existing.revoke_reason = "SUPERSEDED_BY_REAUTHORIZE"[:200]
            existing.updated_at = now
            self._session.flush()

        act = LiveTradingTransitionService(self._session).peek_active(
            broker_code=broker,
            user_broker_account_id=int(user_broker_account_id),
        )
        if act is not None:
            source_activation_id = int(act.live_trading_transition_id)
        elif source_activation_id is None:
            raise LiveUnattendedError(
                "NO_SOURCE_ACTIVATION",
                "No activation available for unattended reauthorize restore",
            )

        row = LiveUnattendedAuthorizationEntity(
            user_broker_account_id=int(user_broker_account_id),
            broker_code=broker,
            status_code=STATUS_ACTIVE,
            enabled=True,
            entry_authorized=True,
            protective_exit_authorized=True,
            auto_renew_enabled=preserve_auto_renew,
            authorized_until=now + timedelta(hours=hours),
            renewal_interval_seconds=int(
                getattr(
                    settings, "live_unattended_renewal_interval_seconds", 3600
                )
            ),
            renewal_margin_seconds=int(
                getattr(
                    settings, "live_unattended_renewal_margin_seconds", 600
                )
            ),
            arm_lease_ttl_seconds=int(
                getattr(
                    settings, "live_unattended_arm_lease_ttl_seconds", 3600
                )
            ),
            activation_renew_hours=int(
                getattr(
                    settings, "live_unattended_activation_renew_hours", 8
                )
            ),
            max_authorization_horizon_hours=max_h,
            approved_by=actor[:100],
            approved_at=now,
            approval_reason=(reason or "")[:2000],
            approval_phrase_hash=_hash_phrase(
                f"{APPROVAL_MODEL_UNATTENDED_LEASE}:{CONFIRM_ENABLE}"
            ),
            source_activation_id=source_activation_id,
            last_renewal_detail={
                "correlation_id": (correlation_id or "")[:128],
                "source": source_u,
                "approval_model": APPROVAL_MODEL_UNATTENDED_LEASE,
                "mode": "REAUTHORIZE",
                "previous_authorization_id": previous_authorization_id,
                "gates": gates,
            },
        )
        self._session.add(row)
        self._session.flush()
        emit_live_safety_audit(
            self._session,
            event_type="UNATTENDED_AUTHORIZATION_REAUTHORIZED",
            actor=actor,
            run_id=None,
            user_id=int(uba.user_id),
            account_id=int(user_broker_account_id),
            strategy_id=None,
            detail={
                "actor": actor,
                "user_broker_account_id": int(user_broker_account_id),
                "broker": broker,
                "authorization_horizon_hours": hours,
                "authorized_until": row.authorized_until.isoformat(),
                "authorization_id": int(row.live_unattended_authorization_id),
                "previous_authorization_id": previous_authorization_id,
                "source_activation_id": source_activation_id,
                "reason": (reason or "")[:500],
                "source": source_u,
                "mode": "REAUTHORIZE",
            },
            commit=False,
        )
        emit_live_order_telegram(
            event_type="UNATTENDED_AUTHORIZATION_REAUTHORIZED",
            title="24H Unattended REAUTH",
            message=(
                f"UBA {user_broker_account_id} reauthorized until "
                f"{row.authorized_until.isoformat()}"
            ),
            detail={
                "authorization_id": int(row.live_unattended_authorization_id)
            },
        )
        self._session.commit()
        self._session.refresh(row)

        # LIVE/ARM/Activation + UPBIT stack 복구
        restore = self.restore_from_active_lease(
            int(user_broker_account_id),
            actor=f"{actor}_REAUTHORIZE_RESTORE",
            restore_stack=True,
        )
        self._session.commit()
        status = self.status_dict(int(user_broker_account_id))
        status["reauthorized"] = True
        status["restore"] = restore
        return status

    def disable(
        self,
        user_broker_account_id: int,
        *,
        actor: str,
        confirmation_text: str,
        reason: str,
        fail_closed: bool = True,
    ) -> dict[str, Any]:
        text_u = (confirmation_text or "").strip().upper()
        if CONFIRM_DISABLE not in text_u:
            raise LiveUnattendedError(
                "CONFIRMATION_REQUIRED",
                f"confirmation_text must include '{CONFIRM_DISABLE}'",
            )
        row = self.get_active(int(user_broker_account_id))
        if row is None:
            return self.status_dict(int(user_broker_account_id))
        now = _now()
        row.enabled = False
        row.status_code = STATUS_REVOKED
        row.entry_authorized = False
        row.revoked_at = now
        row.revoked_by = actor[:100]
        row.revoke_reason = (reason or "OPERATOR_DISABLE")[:200]
        row.updated_at = now
        self._session.flush()
        emit_live_safety_audit(
            self._session,
            event_type="UNATTENDED_AUTHORIZATION_REVOKED",
            actor=actor,
            run_id=None,
            user_id=None,
            account_id=int(user_broker_account_id),
            strategy_id=None,
            detail={
                "authorization_id": int(row.live_unattended_authorization_id),
                "reason": row.revoke_reason,
                "fail_closed": fail_closed,
            },
            commit=False,
        )
        if fail_closed:
            self._fail_closed_on_expiry(
                int(user_broker_account_id),
                actor=actor,
                reason="UNATTENDED_REVOKED",
                keep_protective_exit=True,
            )
        self._session.commit()
        return self.status_dict(int(user_broker_account_id))

    def evaluate_enable_gates(
        self, user_broker_account_id: int
    ) -> dict[str, Any]:
        """Unattended enable 최소 안전 조건 — 하나라도 실패 시 FAIL CLOSED.

        Runtime RUNNING은 비필수(이후 운영 스택 START에서 기동).
        LIVE ON approval_phrase는 여기서 재검증하지 않는다.
        """

        blockers: list[str] = []
        checks: dict[str, Any] = {}
        uba = self._session.get(
            UserBrokerAccount, int(user_broker_account_id)
        )
        if uba is None:
            return {
                "ok": False,
                "blockers": ["UBA_NOT_FOUND"],
                "checks": {},
                "live": "OFF",
                "arm": "OFF",
                "activation_id": None,
                "execution_env": None,
            }

        broker = str(uba.broker_code or "").upper()
        checks["broker"] = broker
        if broker != "UPBIT":
            blockers.append("BROKER_NOT_UPBIT")

        if not bool(uba.is_active):
            blockers.append("UBA_INACTIVE")

        # LIVE ON
        live_on = bool(uba.live_order_enabled)
        checks["live"] = "ON" if live_on else "OFF"
        if not live_on:
            blockers.append("LIVE_OFF")

        # ARM ON (만료 포함)
        now = _now()
        arm_exp = aware_utc(getattr(uba, "arm_expires_at", None))
        arm_on = bool(uba.live_armed) and (
            arm_exp is None or arm_exp > now
        )
        checks["arm"] = "ON" if arm_on else "OFF"
        if not arm_on:
            blockers.append("ARM_OFF")

        # UPBIT REAL (mock LIVE conflict 금지)
        execution_env = "UNKNOWN"
        try:
            from stock_platform.broker.live_config_gate import (
                evaluate_live_flag_consistency,
            )

            flag = evaluate_live_flag_consistency(
                broker_code=broker,
                session=self._session,
                user_broker_account_id=int(user_broker_account_id),
            )
            checks["live_config"] = {
                "allowed": flag.allowed,
                "code": flag.code,
                "status": flag.status,
            }
            if not flag.allowed:
                blockers.append(str(flag.code or "LIVE_CONFIG_BLOCKED"))
                if flag.code == "UPBIT_MOCK_LIVE_CONFLICT":
                    execution_env = "MOCK"
                else:
                    execution_env = "BLOCKED"
            else:
                execution_env = "REAL"
        except Exception:  # noqa: BLE001
            blockers.append("LIVE_CONFIG_CHECK_FAILED")
        checks["execution_env"] = execution_env
        if execution_env == "MOCK":
            blockers.append("UBA_NOT_REAL")

        # Connection CONNECTED
        def _gate_error(code: str, message: str) -> Exception:
            return LiveUnattendedError(str(code).upper(), message)

        try:
            from stock_platform.trading.runtime_control_gates import (
                assert_uba_connection_ready,
            )

            assert_uba_connection_ready(uba, raise_error=_gate_error)
            checks["connection"] = "CONNECTED"
        except LiveUnattendedError as exc:
            blockers.append(exc.code.upper())
            checks["connection"] = "FAIL"
        except Exception as exc:  # noqa: BLE001
            blockers.append(str(getattr(exc, "code", "CONNECTION_CHECK_FAILED")).upper())
            checks["connection"] = "FAIL"

        # Credential VERIFIED
        try:
            from stock_platform.broker.credential_vault_service import (
                BrokerCredentialVaultService,
            )

            cred = BrokerCredentialVaultService(self._session).status(
                int(user_broker_account_id),
                broker_code=broker,
            )
            ver = str(cred.verification_status or "").upper()
            checks["credential"] = ver or "MISSING"
            if ver != "VERIFIED":
                blockers.append("CREDENTIAL_NOT_VERIFIED")
        except Exception:  # noqa: BLE001
            blockers.append("CREDENTIAL_CHECK_FAILED")
            checks["credential"] = "FAIL"

        # Recovery SUCCESS + trading_paused
        try:
            from stock_platform.trading.runtime_control_gates import (
                assert_recovery_ready,
            )

            recovery = assert_recovery_ready(
                self._session,
                int(user_broker_account_id),
                raise_error=_gate_error,
            )
            recovery_status = str(
                recovery.get("recovery_status") or ""
            ).upper()
            checks["recovery"] = recovery_status or "EMPTY"
            checks["trading_paused_recovery"] = bool(
                recovery.get("trading_paused")
            )
            if recovery_status not in _OK_RECOVERY_STRICT:
                blockers.append("RECOVERY_NOT_SUCCESS")
            if bool(recovery.get("trading_paused")):
                blockers.append("TRADING_PAUSED")
        except LiveUnattendedError as exc:
            blockers.append(exc.code.upper())
        except Exception:  # noqa: BLE001
            blockers.append("RECOVERY_CHECK_FAILED")

        if bool(getattr(uba, "trading_paused", False)):
            blockers.append("TRADING_PAUSED")
            checks["trading_paused_uba"] = True
        else:
            checks["trading_paused_uba"] = False

        # Active HIGH/CRITICAL Conflict = 0
        try:
            from stock_platform.broker.recovery_conflict_constants import (
                ACTIVE_REVIEW_STATUSES,
            )
            from stock_platform.broker.recovery_conflict_entities import (
                BrokerRecoveryConflictEntity,
            )
            from sqlalchemy import func, select

            high_count = int(
                self._session.scalar(
                    select(func.count())
                    .select_from(BrokerRecoveryConflictEntity)
                    .where(
                        BrokerRecoveryConflictEntity.user_broker_account_id
                        == int(user_broker_account_id),
                        BrokerRecoveryConflictEntity.review_status.in_(
                            list(ACTIVE_REVIEW_STATUSES)
                        ),
                        BrokerRecoveryConflictEntity.risk_level.in_(
                            list(_HIGH_CONFLICT_LEVELS)
                        ),
                    )
                )
                or 0
            )
            checks["high_critical_conflict_count"] = high_count
            if high_count > 0:
                blockers.append(f"CONFLICT_HIGH_{high_count}")
        except Exception:  # noqa: BLE001
            blockers.append("CONFLICT_CHECK_FAILED")

        # Kill Switch OFF
        try:
            from stock_platform.risk_engine.kill_switch_service import (
                KillSwitchService,
            )

            if KillSwitchService(self._session).is_active():
                blockers.append("KILL_SWITCH_ACTIVE")
                checks["kill_switch"] = "ON"
            else:
                checks["kill_switch"] = "OFF"
        except Exception:  # noqa: BLE001
            blockers.append("KILL_SWITCH_CHECK_FAILED")
            checks["kill_switch"] = "UNKNOWN"

        # Activation ACTIVE
        act = LiveTradingTransitionService(self._session).peek_active(
            broker_code=broker,
            user_broker_account_id=int(user_broker_account_id),
        )
        if act is None:
            blockers.append("ACTIVATION_INACTIVE")
            checks["activation"] = "INACTIVE"
        else:
            checks["activation"] = "ACTIVE"
            checks["activation_id"] = int(act.live_trading_transition_id)
            exp = aware_utc(act.expires_at)
            checks["activation_expires_at"] = (
                exp.isoformat() if exp is not None else None
            )

        # Risk PASS + account safety
        try:
            from stock_platform.trading.runtime_control_gates import (
                assert_risk_account_not_paused,
            )

            risk = assert_risk_account_not_paused(
                self._session,
                uba,
                raise_error=_gate_error,
            )
            checks["risk"] = "PASS"
            checks["account_safety"] = "PASS"
            checks["risk_detail"] = {
                k: risk.get(k)
                for k in ("account_paused", "arm_ttl_seconds")
                if isinstance(risk, dict)
            }
        except LiveUnattendedError as exc:
            blockers.append(exc.code.upper())
            checks["risk"] = "FAIL"
            checks["account_safety"] = "FAIL"
        except Exception:  # noqa: BLE001
            blockers.append("RISK_CHECK_FAILED")
            checks["risk"] = "FAIL"
            checks["account_safety"] = "FAIL"

        # 중복 blocker 제거 (순서 유지)
        seen: set[str] = set()
        uniq: list[str] = []
        for code in blockers:
            if code in seen:
                continue
            seen.add(code)
            uniq.append(code)

        return {
            "ok": len(uniq) == 0,
            "blockers": uniq,
            "checks": checks,
            "live": checks.get("live", "OFF"),
            "arm": checks.get("arm", "OFF"),
            "activation_id": checks.get("activation_id"),
            "activation_expires_at": checks.get("activation_expires_at"),
            "execution_env": execution_env,
        }

    def evaluate_renewal_gates(
        self, user_broker_account_id: int
    ) -> dict[str, Any]:
        """ARM/Activation 자동 renewal 허용 조건."""

        return self.evaluate_enable_gates(int(user_broker_account_id))

    @staticmethod
    def _horizon_renew_margin_seconds(
        row: LiveUnattendedAuthorizationEntity | None,
    ) -> int:
        settings = get_settings()
        default_margin = int(
            getattr(
                settings, "live_unattended_horizon_renew_margin_seconds", 3600
            )
        )
        if row is None:
            return default_margin
        # lease row margin은 ARM용(600s) — horizon은 settings 우선
        return default_margin

    @staticmethod
    def _horizon_min_extension_seconds() -> int:
        settings = get_settings()
        return int(
            getattr(
                settings, "live_unattended_horizon_min_extension_seconds", 3600
            )
        )

    @staticmethod
    def _horizon_renew_interval_seconds() -> int:
        settings = get_settings()
        return int(
            getattr(
                settings, "live_unattended_horizon_renew_interval_seconds", 3600
            )
        )

    def _next_horizon_renew_check_at(
        self,
        row: LiveUnattendedAuthorizationEntity,
        *,
        until: datetime | None,
        now: datetime,
    ) -> str | None:
        if until is None or not bool(getattr(row, "auto_renew_enabled", False)):
            return None
        margin = self._horizon_renew_margin_seconds(row)
        remaining = max(0, int((until - now).total_seconds()))
        if remaining <= margin:
            return now.isoformat()
        check_at = until - timedelta(seconds=margin)
        return check_at.isoformat()

    @staticmethod
    def _last_horizon_auto_renew_summary(
        row: LiveUnattendedAuthorizationEntity,
    ) -> dict[str, Any]:
        detail = dict(row.last_renewal_detail or {})
        hz = detail.get("horizon_auto_renew")
        if not isinstance(hz, dict):
            return {"status": "NONE"}
        return {
            "status": hz.get("result") or "UNKNOWN",
            "renewed_at": hz.get("renewed_at"),
            "old_authorized_until": hz.get("old_authorized_until"),
            "new_authorized_until": hz.get("new_authorized_until"),
            "reason": hz.get("reason"),
            "blockers": hz.get("blockers"),
        }

    def set_auto_renew_enabled(
        self,
        user_broker_account_id: int,
        *,
        enabled: bool,
        actor: str,
    ) -> dict[str, Any]:
        """운영자 명시 opt-in — ACTIVE lease에만 적용."""

        row = self.get_active(int(user_broker_account_id))
        if row is None:
            raise LiveUnattendedError(
                "NO_ACTIVE_LEASE",
                "Active 24H unattended lease required to toggle auto-renew",
            )
        if row.status_code != STATUS_ACTIVE:
            raise LiveUnattendedError(
                "LEASE_NOT_ACTIVE",
                "Auto-renew can only be set on ACTIVE entry lease",
            )
        row.auto_renew_enabled = bool(enabled)
        row.updated_at = _now()
        detail = dict(row.last_renewal_detail or {})
        detail["auto_renew_toggle"] = {
            "enabled": bool(enabled),
            "actor": actor[:100],
            "at": _now().isoformat(),
        }
        row.last_renewal_detail = detail
        self._session.flush()
        emit_live_safety_audit(
            self._session,
            event_type="UNATTENDED_AUTO_RENEW_TOGGLED",
            actor=actor,
            run_id=None,
            user_id=None,
            account_id=int(user_broker_account_id),
            strategy_id=None,
            detail={"enabled": bool(enabled)},
            commit=False,
        )
        self._session.commit()
        return self.status_dict(int(user_broker_account_id))

    def evaluate_horizon_auto_renew_gates(
        self, user_broker_account_id: int
    ) -> dict[str, Any]:
        """24H horizon 자동 연장 precheck — enable + readiness + open-order."""

        base = self.evaluate_enable_gates(int(user_broker_account_id))
        blockers = list(base.get("blockers") or [])
        checks: dict[str, Any] = dict(base.get("checks") or {})

        if not base.get("ok"):
            return {"ok": False, "blockers": blockers, "checks": checks}

        try:
            from stock_platform.order.live_open_order_exposure import (
                evaluate_live_open_order_exposure,
            )
            from stock_platform.trading.account_models import UserBrokerAccount

            uba = self._session.get(
                UserBrokerAccount, int(user_broker_account_id)
            )
            broker = str(uba.broker_code or "UPBIT").upper() if uba else "UPBIT"
            exposure = evaluate_live_open_order_exposure(
                self._session,
                uba_id=int(user_broker_account_id),
                broker_code=broker,
                environment="LIVE",
            )
            checks["open_order_exposure"] = exposure.as_detail()
            if int(exposure.unknown_open_count) > 0:
                blockers.append("UNKNOWN_OPEN_ORDER")
        except Exception:  # noqa: BLE001
            blockers.append("OPEN_ORDER_EXPOSURE_CHECK_FAILED")

        try:
            from stock_platform.trading.autotrading_master_gate import (
                _evaluate_auto_exit_quote_freshness,
                evaluate_uba_autotrading_ready,
            )

            exit_q = _evaluate_auto_exit_quote_freshness(
                self._session,
                user_broker_account_id=int(user_broker_account_id),
            )
            checks["auto_exit_quote"] = exit_q
            if exit_q.get("applicable") and not exit_q.get("ok", True):
                blockers.append("AUTO_EXIT_QUOTE_STALE")

            ready = evaluate_uba_autotrading_ready(
                self._session, user_broker_account_id=int(user_broker_account_id)
            )
            checks["readiness_status"] = ready.get("status")
            for code in ready.get("blockers") or []:
                if str(code) in _READINESS_BLOCKERS_FOR_HORIZON_RENEW:
                    blockers.append(f"READINESS_{code}")
        except Exception:  # noqa: BLE001
            blockers.append("READINESS_CHECK_FAILED")

        seen: set[str] = set()
        uniq: list[str] = []
        for code in blockers:
            if code in seen:
                continue
            seen.add(code)
            uniq.append(code)
        return {"ok": len(uniq) == 0, "blockers": uniq, "checks": checks}

    def dry_horizon_auto_renew_evaluation(
        self, user_broker_account_id: int
    ) -> dict[str, Any]:
        """READ-ONLY — would_renew / projected expiry (시간 조작 없음)."""

        row = self.get_active(int(user_broker_account_id))
        now = _now()
        if row is None:
            return {
                "ok": False,
                "reason": "NO_ACTIVE_LEASE",
                "would_renew": False,
            }
        until = aware_utc(row.authorized_until)
        remaining = (
            max(0, int((until - now).total_seconds())) if until else 0
        )
        margin = self._horizon_renew_margin_seconds(row)
        settings = get_settings()
        default_h = int(
            getattr(settings, "live_unattended_default_horizon_hours", 24)
        )
        projected_until = (
            (now + timedelta(hours=default_h)).isoformat() if until else None
        )
        gates = self.evaluate_horizon_auto_renew_gates(int(user_broker_account_id))
        in_margin = remaining > 0 and remaining <= margin
        meaningful = False
        if until is not None:
            new_until = now + timedelta(hours=default_h)
            meaningful = new_until > until + timedelta(
                seconds=self._horizon_min_extension_seconds()
            )
        would_renew = (
            bool(getattr(row, "auto_renew_enabled", False))
            and in_margin
            and gates.get("ok")
            and meaningful
            and row.status_code == STATUS_ACTIVE
        )
        return {
            "authorization_id": int(row.live_unattended_authorization_id),
            "auto_renew_enabled": bool(getattr(row, "auto_renew_enabled", False)),
            "authorized_until": until.isoformat() if until else None,
            "remaining_seconds": remaining,
            "renew_margin_seconds": margin,
            "in_renew_margin": in_margin,
            "precheck": gates,
            "would_renew": would_renew,
            "projected_authorized_until": projected_until,
            "meaningful_extension": meaningful,
        }

    def _try_horizon_auto_renew(
        self,
        row: LiveUnattendedAuthorizationEntity,
        uba: UserBrokerAccount,
        *,
        actor: str,
    ) -> dict[str, Any]:
        """24H horizon 연장 — stack restart 없음, idempotent."""

        if not bool(getattr(row, "auto_renew_enabled", False)):
            return {"horizon_renewed": False, "reason": "AUTO_RENEW_OFF"}

        now = _now()
        until = aware_utc(row.authorized_until)
        if until is None or until <= now:
            return {"horizon_renewed": False, "reason": "HORIZON_EXPIRED"}

        margin = self._horizon_renew_margin_seconds(row)
        remaining = int((until - now).total_seconds())
        if remaining > margin:
            return {
                "horizon_renewed": False,
                "reason": "NOT_IN_RENEW_MARGIN",
                "remaining_seconds": remaining,
                "margin_seconds": margin,
            }

        detail_prev = dict(row.last_renewal_detail or {})
        hz_prev = detail_prev.get("horizon_auto_renew")
        if isinstance(hz_prev, dict) and hz_prev.get("renewed_at"):
            try:
                last_at = datetime.fromisoformat(
                    str(hz_prev["renewed_at"]).replace("Z", "+00:00")
                )
                if last_at.tzinfo is None:
                    last_at = last_at.replace(tzinfo=timezone.utc)
                interval = self._horizon_renew_interval_seconds()
                if (now - last_at.astimezone(timezone.utc)).total_seconds() < interval:
                    return {
                        "horizon_renewed": False,
                        "reason": "RENEW_INTERVAL_NOT_ELAPSED",
                    }
            except Exception:  # noqa: BLE001
                pass

        settings = get_settings()
        default_h = int(
            getattr(settings, "live_unattended_default_horizon_hours", 24)
        )
        new_until = now + timedelta(hours=default_h)
        min_ext = self._horizon_min_extension_seconds()
        if new_until <= until + timedelta(seconds=min_ext):
            return {
                "horizon_renewed": False,
                "reason": "NO_MEANINGFUL_EXTENSION",
                "extension_seconds": int(
                    (new_until - until).total_seconds()
                ),
            }

        gates = self.evaluate_horizon_auto_renew_gates(
            int(row.user_broker_account_id)
        )
        if not gates.get("ok"):
            self._maybe_emit_horizon_renew_failure_telegram(
                row,
                blockers=list(gates.get("blockers") or []),
                until=until,
            )
            hz_fail = {
                "result": "BLOCKED",
                "attempted_at": now.isoformat(),
                "blockers": list(gates.get("blockers") or []),
                "old_authorized_until": until.isoformat(),
            }
            detail_prev["horizon_auto_renew"] = hz_fail
            row.last_renewal_detail = detail_prev
            row.updated_at = now
            self._session.flush()
            return {
                "horizon_renewed": False,
                "reason": "SAFETY_GATES_FAILED",
                "blockers": gates.get("blockers"),
            }

        lock = _horizon_renew_lock(int(row.user_broker_account_id))
        if not lock.acquire(blocking=False):
            return {"horizon_renewed": False, "reason": "RENEW_IN_FLIGHT"}

        try:
            old_until = until
            row.authorized_until = new_until
            row.last_renewed_at = now
            row.last_renewal_actor = actor[:100]
            hz_ok = {
                "result": "SUCCESS",
                "renewed_at": now.isoformat(),
                "actor": actor,
                "previous_authorization_id": int(
                    row.live_unattended_authorization_id
                ),
                "old_authorized_until": old_until.isoformat(),
                "new_authorized_until": new_until.isoformat(),
                "extension_hours": default_h,
                "precheck": gates,
            }
            detail_prev["horizon_auto_renew"] = hz_ok
            row.last_renewal_detail = detail_prev
            row.updated_at = now
            self._session.flush()
            emit_live_safety_audit(
                self._session,
                event_type="UNATTENDED_HORIZON_AUTO_RENEWED",
                actor=actor,
                run_id=None,
                user_id=int(uba.user_id),
                account_id=int(row.user_broker_account_id),
                strategy_id=None,
                detail=hz_ok,
                commit=False,
            )
            self._maybe_emit_horizon_renew_success_telegram(
                row, old_until=old_until, new_until=new_until
            )
            return {
                "horizon_renewed": True,
                "old_authorized_until": old_until.isoformat(),
                "new_authorized_until": new_until.isoformat(),
                "detail": hz_ok,
            }
        finally:
            lock.release()

    def _maybe_emit_horizon_renew_success_telegram(
        self,
        row: LiveUnattendedAuthorizationEntity,
        *,
        old_until: datetime,
        new_until: datetime,
    ) -> None:
        detail = dict(row.last_renewal_detail or {})
        hz = detail.get("horizon_auto_renew")
        if not isinstance(hz, dict):
            hz = {}
        now = _now()
        last_tg = hz.get("last_success_telegram_at")
        if last_tg:
            try:
                dt = datetime.fromisoformat(str(last_tg).replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                if (
                    now - dt.astimezone(timezone.utc)
                ).total_seconds() < HORIZON_RENEW_SUCCESS_TELEGRAM_INTERVAL_SECONDS:
                    return
            except Exception:  # noqa: BLE001
                pass
        hz["last_success_telegram_at"] = now.isoformat()
        detail["horizon_auto_renew"] = hz
        row.last_renewal_detail = detail
        emit_live_order_telegram(
            event_type="UNATTENDED_HORIZON_AUTO_RENEWED",
            title="24H 무인운영 자동 연장",
            message=(
                f"계좌: {row.broker_code}\n"
                f"기존 만료: {old_until.astimezone(timezone.utc).strftime('%H:%M')}\n"
                f"새 만료: {new_until.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M')}\n"
                "자동매매 상태: 정상"
            ),
            detail={
                "authorization_id": row.live_unattended_authorization_id,
                "old_authorized_until": old_until.isoformat(),
                "new_authorized_until": new_until.isoformat(),
            },
        )

    def _maybe_emit_horizon_renew_failure_telegram(
        self,
        row: LiveUnattendedAuthorizationEntity,
        *,
        blockers: list[str],
        until: datetime,
    ) -> None:
        detail = dict(row.last_renewal_detail or {})
        hz = detail.get("horizon_auto_renew")
        if not isinstance(hz, dict):
            hz = {}
        now = _now()
        last_tg = hz.get("last_failure_telegram_at")
        if last_tg:
            try:
                dt = datetime.fromisoformat(str(last_tg).replace("Z", "+00:00"))
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                if (
                    now - dt.astimezone(timezone.utc)
                ).total_seconds() < HORIZON_RENEW_FAILURE_TELEGRAM_COOLDOWN_SECONDS:
                    return
            except Exception:  # noqa: BLE001
                pass
        hz["last_failure_telegram_at"] = now.isoformat()
        detail["horizon_auto_renew"] = hz
        row.last_renewal_detail = detail
        emit_live_order_telegram(
            event_type="UNATTENDED_HORIZON_AUTO_RENEW_FAILED",
            title="24H 무인운영 자동 연장 실패",
            message=(
                f"계좌: {row.broker_code}\n"
                f"사유: {', '.join(blockers[:5])}\n"
                f"현재 만료: {until.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M')}\n"
                "만료 전 운영자 확인 필요"
            ),
            detail={
                "authorization_id": row.live_unattended_authorization_id,
                "blockers": blockers,
            },
        )

    def evaluate_restore_gates(
        self, user_broker_account_id: int
    ) -> dict[str, Any]:
        """startup fail-closed 이후 lease 복구용 gate.

        LIVE/ARM/Activation은 복구 대상이므로 blocker에서 제외한다.
        Kill/Recovery/Conflict 등 안전 게이트는 그대로 적용한다.
        """

        gates = self.evaluate_enable_gates(int(user_broker_account_id))
        ignored = {
            "LIVE_OFF",
            "ARM_OFF",
            "ARM_EXPIRED",
            "ACTIVATION_INACTIVE",
            "RUNTIME_NOT_RUNNING",
            "OUTBOX_WORKER_NOT_RUNNING",
        }
        blockers = [b for b in gates["blockers"] if b not in ignored]
        return {
            **gates,
            "ok": len(blockers) == 0,
            "blockers": blockers,
        }

    def restore_from_active_lease(
        self,
        user_broker_account_id: int,
        *,
        actor: str = "SYSTEM_UNATTENDED_RESTORE",
        restore_stack: bool = True,
    ) -> dict[str, Any]:
        """ACTIVE unattended lease가 있으면 startup 강제 OFF 이후 LIVE/ARM/Activation 복구.

        운영자가 승인한 24H lease 범위 안에서만 동작한다.
        임의 TTL 연장이 아니라 lease horizon 내 세션 재기동이다.

        restore_stack=True 이고 running event loop가 있으면 UPBIT Runtime/Worker
        복구를 비동기로 스케줄한다 (동기 호출부/startup 전용 경로는 False 가능).
        """

        row = self.get_active(int(user_broker_account_id))
        if row is None:
            return {"restored": False, "reason": "NO_ACTIVE_LEASE"}

        now = _now()
        until = aware_utc(row.authorized_until)
        if until is None or until <= now:
            self._expire_authorization(
                row, actor=actor, reason="HORIZON_EXPIRED"
            )
            return {"restored": False, "reason": "HORIZON_EXPIRED"}

        if row.status_code == STATUS_PROTECTIVE:
            return {"restored": False, "reason": "PROTECTIVE_ONLY"}

        uba = self._session.get(
            UserBrokerAccount, int(user_broker_account_id)
        )
        if uba is None:
            return {"restored": False, "reason": "UBA_NOT_FOUND"}

        gates = self.evaluate_restore_gates(int(user_broker_account_id))
        if not gates["ok"]:
            return {
                "restored": False,
                "reason": "SAFETY_GATES_FAILED",
                "blockers": gates["blockers"],
            }

        detail: dict[str, Any] = {
            "authorization_id": int(row.live_unattended_authorization_id),
            "horizon_until": until.isoformat(),
        }

        # 1) Activation 확보 (만료/부재/ARM TTL보다 짧으면 successor)
        act = LiveTradingTransitionService(self._session).peek_active(
            broker_code=str(uba.broker_code or "").upper(),
            user_broker_account_id=int(user_broker_account_id),
        )
        act_remaining = activation_remaining_seconds(act, now=now)
        arm_ttl_cap = int(row.arm_lease_ttl_seconds)
        need_activation_successor = (
            act is None
            or act_remaining <= 0
            or act_remaining < arm_ttl_cap
        )
        if need_activation_successor:
            previous = act
            if previous is None and row.source_activation_id is not None:
                previous = self._session.get(
                    LiveTradingTransitionEntity,
                    int(row.source_activation_id),
                )
            if previous is None:
                return {
                    "restored": False,
                    "reason": "NO_SOURCE_ACTIVATION",
                }
            renew_hours = min(
                int(row.activation_renew_hours),
                max(1, int((until - now).total_seconds() // 3600)),
            )
            act = self._create_successor_activation(
                uba=uba,
                previous=previous,
                actor=actor,
                ttl_hours=renew_hours,
            )
            row.source_activation_id = int(act.live_trading_transition_id)
            detail["activation_restored"] = True
            detail["successor_activation_id"] = int(
                act.live_trading_transition_id
            )
        else:
            detail["activation_id"] = int(act.live_trading_transition_id)
            detail["activation_remaining"] = act_remaining

        # 2) LIVE ON (lease가 이미 승인한 세션 복구)
        from stock_platform.trading.live_order_approval_service import (
            LiveOrderApprovalService,
        )

        live_result = LiveOrderApprovalService(self._session).set_live_enabled(
            int(user_broker_account_id),
            enabled=True,
            actor=actor,
            reason="UNATTENDED_LEASE_RESTORE_AFTER_STARTUP",
            correlation_id=(
                f"unatt-restore-{row.live_unattended_authorization_id}"
            ),
            enforce_enable_gates=True,
            allow_auto_protective_open_orders=True,
        )
        detail["live_restored"] = True
        detail["live_already_enabled"] = bool(
            live_result.get("already_enabled")
        )

        # 3) ARM ON (lease TTL, activation remaining으로 clamp)
        from stock_platform.trading.live_arm_service import LiveArmService

        arm_ttl = min(
            int(row.arm_lease_ttl_seconds),
            max(60, int((until - now).total_seconds())),
        )
        arm_result = LiveArmService(self._session).arm(
            int(user_broker_account_id),
            actor=actor,
            ttl_seconds=arm_ttl,
            reason="UNATTENDED_LEASE_RESTORE_AFTER_STARTUP",
            correlation_id=(
                f"unatt-restore-{row.live_unattended_authorization_id}"
            ),
            enforce_gates=True,
            force_renew=True,
            allow_auto_protective_open_orders=True,
        )
        detail["arm_restored"] = True
        detail["arm_ttl_seconds"] = arm_ttl
        detail["arm_expires_at"] = arm_result.get("arm_expires_at")

        row.last_renewed_at = now
        row.last_renewal_actor = actor[:100]
        row.last_renewal_detail = {
            "restore": True,
            **detail,
        }
        row.updated_at = now
        self._session.flush()
        emit_live_safety_audit(
            self._session,
            event_type="UNATTENDED_AUTHORIZATION_RESTORED",
            actor=actor,
            run_id=None,
            user_id=int(uba.user_id),
            account_id=int(user_broker_account_id),
            strategy_id=None,
            detail=detail,
            commit=False,
        )

        # UPBIT: Runtime/Worker는 startup_forced_idle로 남을 수 있음 → stack 스케줄
        if restore_stack and str(uba.broker_code or "").upper() == "UPBIT":
            detail["stack_restore_schedule"] = (
                self._schedule_upbit_stack_restore(
                    int(user_broker_account_id),
                    actor=f"{actor}_STACK",
                )
            )
        else:
            detail["stack_restore_schedule"] = {
                "scheduled": False,
                "reason": "SKIPPED",
            }

        return {"restored": True, "detail": detail}

    def _schedule_upbit_stack_restore(
        self,
        user_broker_account_id: int,
        *,
        actor: str,
    ) -> dict[str, Any]:
        """running loop가 있으면 create_task, 없으면 백그라운드 스레드로 복구."""

        import asyncio
        import threading

        uba_id = int(user_broker_account_id)

        async def _run() -> None:
            sf = get_session_factory()
            session = sf()
            try:
                from stock_platform.trading.upbit_unattended_stack_restore import (
                    restore_upbit_trading_stack,
                )

                result = await restore_upbit_trading_stack(
                    session,
                    user_broker_account_id=uba_id,
                    actor=actor,
                )
                session.commit()
                logger.info(
                    "unattended_stack_restore_task_done",
                    uba_id=uba_id,
                    restored=result.get("restored"),
                    reason=result.get("reason"),
                )
            except Exception:  # noqa: BLE001
                session.rollback()
                logger.exception(
                    "unattended_stack_restore_task_failed",
                    uba_id=uba_id,
                )
            finally:
                session.close()

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # sync FastAPI 핸들러 등 — 전용 스레드에서 stack 복구
            def _thread_main() -> None:
                asyncio.run(_run())

            threading.Thread(
                target=_thread_main,
                name=f"unattended-stack-{uba_id}",
                daemon=True,
            ).start()
            return {
                "scheduled": True,
                "uba_id": uba_id,
                "mode": "BACKGROUND_THREAD",
            }

        loop.create_task(_run(), name=f"unattended-stack-{uba_id}")
        return {"scheduled": True, "uba_id": uba_id, "mode": "EVENT_LOOP_TASK"}

    def renew_due_for_uba(
        self,
        user_broker_account_id: int,
        *,
        actor: str = "SYSTEM_UNATTENDED_RENEWAL",
    ) -> dict[str, Any]:
        """ARM/Activation 만료 임박 시 gated renewal. idempotent."""

        row = self.get_active(int(user_broker_account_id))
        if row is None:
            return {"renewed": False, "reason": "NO_ACTIVE_LEASE"}

        now = _now()
        until = aware_utc(row.authorized_until)
        if until is None or until <= now:
            self._expire_authorization(
                row, actor=actor, reason="HORIZON_EXPIRED"
            )
            return {"renewed": False, "reason": "HORIZON_EXPIRED"}

        if row.status_code == STATUS_PROTECTIVE:
            return {"renewed": False, "reason": "PROTECTIVE_ONLY"}

        uba = self._session.get(
            UserBrokerAccount, int(user_broker_account_id)
        )
        if uba is None:
            return {"renewed": False, "reason": "UBA_NOT_FOUND"}

        horizon_result = self._try_horizon_auto_renew(
            row, uba, actor=ACTOR_HORIZON_AUTO_RENEW
        )
        horizon_renewed = bool(horizon_result.get("horizon_renewed"))
        if horizon_renewed:
            until = aware_utc(row.authorized_until)

        # LIVE/ARM이 꺼져 있으면 renew 대신 lease restore (startup fail-closed 복구)
        if not bool(uba.live_order_enabled) or not bool(uba.live_armed):
            restored = self.restore_from_active_lease(
                int(user_broker_account_id),
                actor=actor.replace("RENEWAL", "RESTORE")
                if "RENEWAL" in actor
                else f"{actor}_RESTORE",
            )
            return {
                "renewed": bool(restored.get("restored")),
                "reason": "RESTORED_FROM_LEASE"
                if restored.get("restored")
                else restored.get("reason"),
                "restore": restored,
            }

        gates = self.evaluate_renewal_gates(int(user_broker_account_id))
        # LIVE/ARM 관련 false-positive 제거 후 재평가
        blockers = [
            b
            for b in gates["blockers"]
            if b
            not in {
                "LIVE_OFF",
                "ARM_OFF",
                "ARM_EXPIRED",
                "RUNTIME_NOT_RUNNING",
                "OUTBOX_WORKER_NOT_RUNNING",
            }
        ]
        if blockers:
            return {
                "renewed": False,
                "reason": "SAFETY_GATES_FAILED",
                "blockers": blockers,
            }

        margin = int(row.renewal_margin_seconds)
        act = LiveTradingTransitionService(self._session).peek_active(
            broker_code=str(uba.broker_code or "").upper(),
            user_broker_account_id=int(user_broker_account_id),
        )
        act_remaining = activation_remaining_seconds(act, now=now)
        arm_exp = aware_utc(getattr(uba, "arm_expires_at", None))
        arm_remaining = (
            max(0, int((arm_exp - now).total_seconds())) if arm_exp else 0
        )

        detail: dict[str, Any] = {
            "activation_remaining": act_remaining,
            "arm_remaining": arm_remaining,
        }
        did = False

        # Activation successor (만료 임박, horizon 내)
        if act is not None and act_remaining <= margin:
            renew_hours = min(
                int(row.activation_renew_hours),
                max(1, int((until - now).total_seconds() // 3600)),
            )
            successor = self._create_successor_activation(
                uba=uba,
                previous=act,
                actor=actor,
                ttl_hours=renew_hours,
            )
            detail["activation_renewed"] = True
            detail["successor_activation_id"] = int(
                successor.live_trading_transition_id
            )
            row.source_activation_id = int(
                successor.live_trading_transition_id
            )
            did = True

        # ARM renew (만료 임박) — lease ceiling 대비 의미 있는 연장만
        if arm_remaining <= margin:
            from stock_platform.trading.live_arm_service import (
                MIN_MEANINGFUL_ARM_EXTENSION_SECONDS,
                LiveArmService,
            )

            lease_remaining = max(60, int((until - now).total_seconds()))
            arm_ttl = min(int(row.arm_lease_ttl_seconds), lease_remaining)
            intended_expires = now + timedelta(seconds=arm_ttl)
            if intended_expires > until:
                intended_expires = until
            extension_seconds = (
                (intended_expires - arm_exp).total_seconds()
                if arm_exp is not None
                else float(arm_ttl)
            )
            if extension_seconds < float(MIN_MEANINGFUL_ARM_EXTENSION_SECONDS):
                detail["arm_renew_skipped"] = "NO_MEANINGFUL_EXTENSION"
                detail["arm_extension_seconds"] = extension_seconds
                detail["intended_arm_expires_at"] = (
                    intended_expires.isoformat()
                )
            else:
                try:
                    arm_result = LiveArmService(self._session).arm(
                        int(user_broker_account_id),
                        actor=actor,
                        ttl_seconds=arm_ttl,
                        reason="UNATTENDED_ARM_RENEWAL",
                        correlation_id=(
                            f"unatt-{row.live_unattended_authorization_id}"
                        ),
                        enforce_gates=True,
                        force_renew=True,
                        allow_auto_protective_open_orders=True,
                    )
                except Exception as exc:  # noqa: BLE001
                    detail["arm_renew_skipped"] = type(exc).__name__
                    detail["arm_renew_error"] = str(exc)[:200]
                    arm_result = {"arm_changed": False}
                if arm_result.get("arm_changed"):
                    detail["arm_renewed"] = True
                    detail["arm_ttl_seconds"] = arm_ttl
                    detail["arm_expires_at"] = arm_result.get(
                        "arm_expires_at"
                    )
                    did = True
                elif "arm_renew_skipped" not in detail:
                    detail["arm_renew_skipped"] = arm_result.get(
                        "skipped_reason", "ARM_UNCHANGED"
                    )
                    detail["arm_extension_seconds"] = arm_result.get(
                        "extension_seconds"
                    )

        if not did and not horizon_renewed:
            return {
                "renewed": False,
                "reason": "NOT_DUE",
                "detail": detail,
                "horizon": horizon_result,
            }

        row.last_renewed_at = now
        row.last_renewal_actor = actor[:100]
        detail["horizon_auto_renew"] = horizon_result
        row.last_renewal_detail = detail
        row.updated_at = now
        self._session.flush()
        emit_live_safety_audit(
            self._session,
            event_type="UNATTENDED_AUTHORIZATION_RENEWED",
            actor=actor,
            run_id=None,
            user_id=int(uba.user_id),
            account_id=int(user_broker_account_id),
            strategy_id=None,
            detail=detail,
            commit=False,
        )
        return {
            "renewed": True,
            "detail": detail,
            "horizon_renewed": horizon_renewed,
        }

    def scan_renew_and_expire(
        self, *, actor: str = "SYSTEM_UNATTENDED"
    ) -> dict[str, Any]:
        """주기 job: horizon 만료 처리 + due renewal."""

        now = _now()
        rows = list(
            self._session.scalars(
                select(LiveUnattendedAuthorizationEntity).where(
                    LiveUnattendedAuthorizationEntity.enabled.is_(True),
                    LiveUnattendedAuthorizationEntity.status_code.in_(
                        (STATUS_ACTIVE, STATUS_PROTECTIVE)
                    ),
                )
            )
        )
        expired = 0
        renewed = 0
        skipped = 0
        errors: list[dict[str, Any]] = []
        for row in rows:
            until = aware_utc(row.authorized_until)
            if until is None or until <= now:
                self._expire_authorization(
                    row, actor=actor, reason="HORIZON_EXPIRED"
                )
                expired += 1
                continue
            try:
                result = self.renew_due_for_uba(
                    int(row.user_broker_account_id), actor=actor
                )
            except Exception as exc:  # noqa: BLE001
                # 한 UBA 실패가 전체 스캔/expire를 막지 않음
                errors.append(
                    {
                        "uba_id": int(row.user_broker_account_id),
                        "error": type(exc).__name__,
                        "message": str(exc)[:200],
                    }
                )
                skipped += 1
                continue
            if result.get("renewed"):
                renewed += 1
            else:
                skipped += 1
        return {
            "expired": expired,
            "renewed": renewed,
            "skipped": skipped,
            "scanned": len(rows),
            "errors": errors,
        }

    def is_entry_authorized(self, user_broker_account_id: int) -> bool:
        row = self.get_active(int(user_broker_account_id))
        if row is None:
            return True  # unattended 미사용 = 기존 ARM/Activation 규칙만
        if not bool(row.enabled):
            return False
        until = aware_utc(row.authorized_until)
        if until is None or until <= _now():
            return False
        return bool(row.entry_authorized) and row.status_code == STATUS_ACTIVE

    def _create_successor_activation(
        self,
        *,
        uba: UserBrokerAccount,
        previous: LiveTradingTransitionEntity,
        actor: str,
        ttl_hours: int,
    ) -> LiveTradingTransitionEntity:
        """기존 Activation 만료 전 canonical successor. expires_at만 UPDATE 금지."""

        svc = LiveTradingTransitionService(self._session)
        plan = svc.validate(
            max_order_amount=previous.max_order_amount,
            max_daily_loss=previous.max_daily_loss,
            paper_validation_approved=True,
            scope="ACCOUNT",
            broker_code=str(uba.broker_code or "").upper(),
            user_broker_account_id=int(uba.user_broker_account_id),
        )
        if not plan.ready:
            raise LiveUnattendedError(
                "ACTIVATION_VALIDATE_FAILED",
                "successor validate failed",
            )
        created = svc.request_transition(
            requested_by=actor[:100],
            max_order_amount=previous.max_order_amount,
            max_daily_loss=previous.max_daily_loss,
            paper_validation_approved=True,
            scope="ACCOUNT",
            broker_code=str(uba.broker_code or "").upper(),
            user_broker_account_id=int(uba.user_broker_account_id),
        )
        # 내부 승인 — unattended lease가 phrase 대체 (운영자 최초 enable 시 승인됨)
        return self._approve_successor_internal(
            transition_id=int(created.live_trading_transition_id),
            actor=actor,
            ttl_hours=ttl_hours,
            previous_id=int(previous.live_trading_transition_id),
        )

    def _approve_successor_internal(
        self,
        *,
        transition_id: int,
        actor: str,
        ttl_hours: int,
        previous_id: int,
    ) -> LiveTradingTransitionEntity:
        entity = self._session.get(
            LiveTradingTransitionEntity, int(transition_id)
        )
        if entity is None:
            raise LiveUnattendedError(
                "TRANSITION_NOT_FOUND", "successor not found"
            )
        settings = get_settings()
        from stock_platform.common.settings import LIVE_ACTIVATION_TTL_HOURS_MAX

        hours = max(1, min(int(ttl_hours), LIVE_ACTIVATION_TTL_HOURS_MAX))
        now = _now()
        entity.approved_by = actor[:100]
        entity.approved_at = now
        entity.expires_at = now + timedelta(hours=hours)
        entity.enabled = True
        entity.disabled_at = None
        payload = dict(entity.validation_payload or {})
        payload["unattended_successor"] = True
        payload["previous_activation_id"] = previous_id
        entity.validation_payload = payload
        # 이전 ACTIVE 비활성화 (history 보존)
        prev = self._session.get(LiveTradingTransitionEntity, int(previous_id))
        if prev is not None and bool(prev.enabled):
            prev.enabled = False
            prev.disabled_at = now
            prev.disable_reason = "SUPERSEDED_BY_UNATTENDED_RENEWAL"
        self._session.flush()
        emit_live_safety_audit(
            self._session,
            event_type="UNATTENDED_ACTIVATION_SUCCESSOR",
            actor=actor,
            run_id=None,
            user_id=None,
            account_id=entity.user_broker_account_id,
            strategy_id=None,
            detail={
                "transition_id": int(entity.live_trading_transition_id),
                "previous_activation_id": previous_id,
                "expires_at": entity.expires_at.isoformat(),
            },
            commit=False,
        )
        return entity

    def _expire_authorization(
        self,
        row: LiveUnattendedAuthorizationEntity,
        *,
        actor: str,
        reason: str,
    ) -> None:
        uba_id = int(row.user_broker_account_id)
        self._fail_closed_on_expiry(
            uba_id,
            actor=actor,
            reason=reason,
            keep_protective_exit=True,
        )
        now = _now()
        # 포지션 있으면 protective, 없으면 완전 만료
        has_pos = self._has_open_position(uba_id)
        row.entry_authorized = False
        if has_pos:
            row.status_code = STATUS_PROTECTIVE
            row.protective_exit_authorized = True
        else:
            row.enabled = False
            row.status_code = STATUS_EXPIRED
            row.protective_exit_authorized = False
            row.revoked_at = now
            row.revoked_by = actor[:100]
            row.revoke_reason = reason[:200]
        row.updated_at = now
        self._session.flush()
        emit_live_safety_audit(
            self._session,
            event_type="UNATTENDED_AUTHORIZATION_EXPIRED",
            actor=actor,
            run_id=None,
            user_id=None,
            account_id=uba_id,
            strategy_id=None,
            detail={
                "authorization_id": int(row.live_unattended_authorization_id),
                "reason": reason,
                "protective": has_pos,
            },
            commit=False,
        )

    def _fail_closed_on_expiry(
        self,
        user_broker_account_id: int,
        *,
        actor: str,
        reason: str,
        keep_protective_exit: bool,
    ) -> None:
        """ENTRY 차단. 보유 포지션 있으면 Exit Monitor 유지 + ARM 유지 가능."""

        has_pos = self._has_open_position(int(user_broker_account_id))
        # Runtime STOP (ENTRY)
        try:
            from stock_platform.trading.upbit_24x7_control import (
                stop_upbit_strategy_runtime,
            )
            from stock_platform.strategy_deployment.definition_entities import (
                AccountStrategyLinkEntity,
            )

            link = self._session.scalar(
                select(AccountStrategyLinkEntity)
                .where(
                    AccountStrategyLinkEntity.user_broker_account_id
                    == int(user_broker_account_id),
                    AccountStrategyLinkEntity.is_active.is_(True),
                )
                .limit(1)
            )
            if link is not None:
                import asyncio

                coro = stop_upbit_strategy_runtime(
                    self._session,
                    user_broker_account_id=int(user_broker_account_id),
                    strategy_id=int(link.strategy_id),
                    confirmation_text="STOP RUNTIME",
                )
                try:
                    loop = asyncio.get_running_loop()
                    loop.create_task(coro)
                except RuntimeError:
                    asyncio.run(coro)
        except Exception:  # noqa: BLE001
            pass

        if keep_protective_exit and has_pos:
            # ENTRY만 차단 — LIVE/ARM 유지로 protective EXIT 가능
            emit_live_safety_audit(
                self._session,
                event_type="UNATTENDED_ENTRY_BLOCKED",
                actor=actor,
                run_id=None,
                user_id=None,
                account_id=int(user_broker_account_id),
                strategy_id=None,
                detail={"reason": reason, "protective_exit": True},
                commit=False,
            )
            return

        from stock_platform.trading.live_arm_service import LiveArmService

        try:
            LiveArmService(self._session).disarm(
                int(user_broker_account_id),
                actor=actor,
                reason=reason,
                turn_live_off=True,
            )
        except Exception:  # noqa: BLE001
            uba = self._session.get(
                UserBrokerAccount, int(user_broker_account_id)
            )
            if uba is not None:
                uba.live_armed = False
                uba.live_order_enabled = False
                uba.arm_expires_at = None

    def _has_open_position(self, user_broker_account_id: int) -> bool:
        try:
            from decimal import Decimal

            from stock_platform.broker.account_repository import (
                BrokerAccountSnapshotRepository,
            )

            _acct, positions = BrokerAccountSnapshotRepository(
                self._session
            ).get_active_by_uba(int(user_broker_account_id))
            for p in positions or []:
                qty = Decimal(str(getattr(p, "quantity", 0) or 0))
                if qty != 0:
                    return True
        except Exception:  # noqa: BLE001
            return False
        return False
