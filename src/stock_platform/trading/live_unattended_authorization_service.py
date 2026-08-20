"""24H Unattended LIVE authorization — operator lease + gated renewal.

Fail-closed: 무제한 TTL/Kill 우회 금지.
자동 renewal은 safety gate 전부 PASS일 때만.
"""

from __future__ import annotations

import hashlib
import secrets
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


class LiveUnattendedError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _hash_phrase(phrase: str) -> str:
    return hashlib.sha256(phrase.encode("utf-8")).hexdigest()


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
        return {
            "unattended_enabled": bool(row.enabled),
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
        """자동 renewal 허용 조건. 하나라도 실패하면 ok=False."""

        return self.evaluate_enable_gates(int(user_broker_account_id))

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

        # LIVE/ARM 필수 (renewal 경로)
        if not bool(uba.live_order_enabled):
            return {"renewed": False, "reason": "LIVE_OFF", "blockers": ["LIVE_OFF"]}
        if not bool(uba.live_armed):
            return {"renewed": False, "reason": "ARM_OFF", "blockers": ["ARM_OFF"]}

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

        # ARM renew (만료 임박)
        if arm_remaining <= margin:
            from stock_platform.trading.live_arm_service import LiveArmService

            arm_ttl = min(
                int(row.arm_lease_ttl_seconds),
                max(60, int((until - now).total_seconds())),
            )
            LiveArmService(self._session).arm(
                int(user_broker_account_id),
                actor=actor,
                ttl_seconds=arm_ttl,
                reason="UNATTENDED_ARM_RENEWAL",
                correlation_id=f"unatt-{row.live_unattended_authorization_id}",
                enforce_gates=True,
                force_renew=True,
            )
            detail["arm_renewed"] = True
            detail["arm_ttl_seconds"] = arm_ttl
            did = True

        if not did:
            return {"renewed": False, "reason": "NOT_DUE", "detail": detail}

        row.last_renewed_at = now
        row.last_renewal_actor = actor[:100]
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
        return {"renewed": True, "detail": detail}

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
        for row in rows:
            until = aware_utc(row.authorized_until)
            if until is None or until <= now:
                self._expire_authorization(
                    row, actor=actor, reason="HORIZON_EXPIRED"
                )
                expired += 1
                continue
            result = self.renew_due_for_uba(
                int(row.user_broker_account_id), actor=actor
            )
            if result.get("renewed"):
                renewed += 1
            else:
                skipped += 1
        return {
            "expired": expired,
            "renewed": renewed,
            "skipped": skipped,
            "scanned": len(rows),
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
