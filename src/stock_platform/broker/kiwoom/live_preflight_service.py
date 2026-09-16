"""K_ONLY — Kiwoom UBA Preflight (조회/진단 전용).

LIVE/ARM/주문/Resume/Recovery/broker network 를 실행하지 않는다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, time, timedelta, timezone
from decimal import Decimal
from typing import Any, Literal
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.orm import Session

KiwoomPreflightMode = Literal["LIVE_ON", "ARM_ON", "ORDER", "SCHEDULER_RUN"]

_OK_RECOVERY = frozenset({"SUCCESS", "READY", "IDLE", ""})
_KST = ZoneInfo("Asia/Seoul")
_DEFAULT_REGULAR_OPEN = time(9, 0)
_DEFAULT_REGULAR_CLOSE = time(15, 30)
_FRESHNESS_SECONDS = 24 * 3600


@dataclass
class KiwoomPreflightSnapshot:
    """로컬 DB/프로세스에서 모은 진단 입력 — broker API 없음."""

    uba_id: int
    user_id: int | None = None
    is_active: bool = True
    deleted: bool = False
    broker_code: str = "KIWOOM"
    connection_status: str = ""
    live_order_enabled: bool = False
    live_armed: bool = False
    arm_expires_at: datetime | None = None
    last_synced_at: datetime | None = None
    masked_account_number: str | None = None
    credential_present: bool = False
    credential_verified: bool = False
    credential_is_mock: bool | None = None
    vault_available: bool = True
    recovery_status: str = ""
    trading_paused: bool = False
    lock_holder: str | None = None
    lock_expires_at: datetime | None = None
    active_high_conflicts: int = 0
    active_conflicts: int = 0
    snapshot_id: int | None = None
    snapshot_status: str | None = None
    snapshot_uba_id: int | None = None
    snapshot_synchronized_at: datetime | None = None
    position_count: int = 0
    unbound_or_cross_uba_positions: int = 0
    uba_risk_present: bool = False
    user_risk_present: bool = False
    risk_account_paused: bool = False
    risk_invalid_reason: str | None = None
    kill_active: bool = False
    scheduler_desired: str = ""
    scheduler_actual: str = ""
    krx_is_trading_day: bool | None = None
    krx_session_type: str | None = None
    krx_reason: str | None = None
    krx_in_regular_session: bool | None = None
    env_global_live: bool = False
    env_kiwoom_live: bool = False
    env_kiwoom_use_mock: bool = False
    strategy_link_count: int = 0
    blocking_orders: dict[str, int] = field(default_factory=dict)
    pending_count: int = 0
    arm_precondition_ok: bool | None = None
    arm_precondition_code: str | None = None
    arm_precondition_message: str | None = None
    now: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class KiwoomLivePreflightService:
    """Kiwoom UBA Pre-LIVE / Pre-ARM / Pre-ORDER. 상태 변경 없음."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def run(
        self,
        *,
        user_broker_account_id: int,
        mode: str = "LIVE_ON",
        owner_user_id: int | None = None,
    ) -> dict[str, Any]:
        from stock_platform.operation.runtime_preflight_service import (
            sanitize_preflight_payload,
        )

        normalized = _normalize_mode(mode)
        snap = self._load_snapshot(
            int(user_broker_account_id),
            owner_user_id=owner_user_id,
            mode=normalized,
        )
        return sanitize_preflight_payload(
            self.evaluate(snap, mode=normalized)
        )

    def evaluate(
        self,
        snap: KiwoomPreflightSnapshot,
        *,
        mode: str = "LIVE_ON",
    ) -> dict[str, Any]:
        from stock_platform.operation.runtime_preflight_service import (
            PREFLIGHT_TTL_SECONDS,
            _item,
        )

        normalized = _normalize_mode(mode)
        checked_at = snap.now if snap.now.tzinfo else snap.now.replace(
            tzinfo=timezone.utc
        )
        expires_at = checked_at + timedelta(seconds=PREFLIGHT_TTL_SECONDS)
        checks: list[dict[str, Any]] = []

        def add(
            code: str,
            name: str,
            status: str,
            message: str,
            *,
            remediation: str | None = None,
            detail: dict[str, Any] | None = None,
        ) -> None:
            checks.append(
                _item(
                    code=code,
                    name=name,
                    status=status,
                    message=message,
                    remediation=remediation,
                    detail=detail or {},
                    checked_at=checked_at,
                )
            )

        broker = str(snap.broker_code or "").upper()
        if snap.deleted or snap.user_id is None:
            add(
                "UBA",
                "UBA",
                "FAIL",
                "UBA not found",
                remediation="올바른 KIWOOM UBA 를 지정하세요.",
            )
            return _pack_result(
                snap, normalized, checks, checked_at, expires_at
            )
        if broker != "KIWOOM":
            add(
                "KIWOOM_BROKER",
                "Broker",
                "FAIL",
                f"broker_code={broker} is not KIWOOM",
                remediation="KIWOOM UBA 만 이 경로를 사용하세요.",
            )
            return _pack_result(
                snap, normalized, checks, checked_at, expires_at
            )

        add(
            "OWNER",
            "Ownership",
            "PASS",
            f"owner_user_id={int(snap.user_id)}",
            detail={"user_id": int(snap.user_id)},
        )
        add(
            "ACCOUNT",
            "Account",
            "PASS" if snap.is_active else "FAIL",
            "UBA active" if snap.is_active else "UBA inactive",
            remediation=None if snap.is_active else "계좌를 활성화하세요.",
            detail={"is_active": snap.is_active, "broker_code": broker},
        )
        add(
            "KIWOOM_BROKER",
            "Broker",
            "PASS",
            "broker_code=KIWOOM",
            detail={"broker_code": broker},
        )

        # Credential
        if not snap.credential_present:
            add(
                "KIWOOM_CREDENTIAL",
                "Credential",
                "FAIL",
                "Credential 없음",
                remediation="Kiwoom credential 을 등록·검증하세요.",
            )
        elif not snap.credential_verified:
            add(
                "KIWOOM_CREDENTIAL",
                "Credential",
                "FAIL",
                "Credential 미검증",
                remediation="Credential 검증을 완료하세요.",
                detail={"verification_status": "UNVERIFIED"},
            )
        else:
            add(
                "KIWOOM_CREDENTIAL",
                "Credential",
                "PASS",
                "Credential VERIFIED",
                detail={"verification_status": "VERIFIED"},
            )

        # Execution REAL — credential is_mock SoT (global mock 제외)
        from stock_platform.broker.kiwoom.execution_env import (
            KIWOOM_MOCK_EXECUTION_BASE,
            KIWOOM_REAL_EXECUTION_BASE,
            kiwoom_execution_real_env_pass,
        )

        mock = snap.credential_is_mock
        exec_host = (
            KIWOOM_REAL_EXECUTION_BASE
            if mock is False
            else (
                KIWOOM_MOCK_EXECUTION_BASE
                if mock is True
                else None
            )
        )
        if mock is True:
            add(
                "KIWOOM_REAL_ENV",
                "REAL execution environment",
                "FAIL",
                "mock credential — REAL execution 불가",
                remediation="REAL credential(is_mock=false)을 사용하세요.",
                detail={
                    "credential_is_mock": True,
                    "execution_host": exec_host,
                },
            )
        elif mock is None:
            add(
                "KIWOOM_REAL_ENV",
                "REAL execution environment",
                "FAIL",
                "credential is_mock 불명 — fail-closed",
                remediation="credential is_mock=false 를 확인하세요.",
                detail={"credential_is_mock": None},
            )
        elif kiwoom_execution_real_env_pass(credential_is_mock=mock):
            add(
                "KIWOOM_REAL_ENV",
                "REAL execution environment",
                "PASS",
                "credential is_mock=false · REAL execution host",
                detail={
                    "credential_is_mock": False,
                    "execution_host": exec_host,
                },
            )
        else:
            add(
                "KIWOOM_REAL_ENV",
                "REAL execution environment",
                "FAIL",
                "execution environment unresolved",
                detail={"credential_is_mock": mock},
            )

        # Market/WS — Option D: ORDER(수동) vs SCHEDULER_RUN(자동) 분리
        market_env = evaluate_kiwoom_market_env(
            mode=normalized,
            credential_present=bool(snap.credential_present),
            credential_verified=bool(snap.credential_verified),
            credential_is_mock=mock,
            market_use_mock=bool(snap.env_kiwoom_use_mock),
        )
        if market_env is not None:
            mkt_status, mkt_msg, mkt_rem, mkt_detail = market_env
            add(
                "KIWOOM_MARKET_ENV",
                "Market/WS environment",
                mkt_status,
                mkt_msg,
                remediation=mkt_rem,
                detail=mkt_detail,
            )

        conn = str(snap.connection_status or "").upper()
        conn_ok = conn in {"CONNECTED", "VERIFIED"}
        add(
            "KIWOOM_CONNECTION",
            "Connection",
            "PASS" if conn_ok else "FAIL",
            f"connection_status={conn or 'UNKNOWN'}",
            remediation=None if conn_ok else "connection_status=CONNECTED",
            detail={"connection_status": conn},
        )

        rec = str(snap.recovery_status or "").upper()
        rec_ok = rec in _OK_RECOVERY
        add(
            "KIWOOM_RECOVERY",
            "Recovery",
            "PASS" if rec_ok else "FAIL",
            f"recovery_status={rec or 'EMPTY'}",
            remediation=(
                None if rec_ok else "Recovery SUCCESS 후 재검사 (자동 Resume 없음)"
            ),
            detail={"recovery_status": rec or None},
        )

        lock_active = _lock_is_active(snap, checked_at)
        add(
            "KIWOOM_RECOVERY_LOCK",
            "Recovery lock",
            "FAIL" if lock_active else "PASS",
            "active recovery lock" if lock_active else "lock 없음",
            remediation=None if not lock_active else "진행 중 Recovery 종료 후 재검사",
            detail={
                "lock_holder": snap.lock_holder,
                "lock_expires_at": (
                    snap.lock_expires_at.isoformat()
                    if snap.lock_expires_at
                    else None
                ),
                "recovery_status": rec or None,
            },
        )

        add(
            "TRADING_PAUSED",
            "Trading paused",
            "FAIL" if snap.trading_paused else "PASS",
            f"trading_paused={bool(snap.trading_paused)}",
            remediation=(
                "운영자 수동 Resume 후 재검사 (Preflight 는 Resume 하지 않음)"
                if snap.trading_paused
                else None
            ),
            detail={"trading_paused": bool(snap.trading_paused)},
        )

        conflict_fail = int(snap.active_high_conflicts or 0) > 0 or int(
            snap.active_conflicts or 0
        ) > 0
        add(
            "CONFLICT",
            "Conflict",
            "FAIL" if conflict_fail else "PASS",
            (
                f"active conflicts={int(snap.active_conflicts or 0)} "
                f"high={int(snap.active_high_conflicts or 0)}"
            ),
            remediation=None if not conflict_fail else "HIGH/open conflict 해소",
            detail={
                "active_conflicts": int(snap.active_conflicts or 0),
                "active_high_conflicts": int(snap.active_high_conflicts or 0),
            },
        )

        snap_ok = (
            snap.snapshot_id is not None
            and str(snap.snapshot_status or "").upper() == "ACTIVE"
            and snap.snapshot_uba_id == snap.uba_id
        )
        add(
            "KIWOOM_ACCOUNT_SNAPSHOT",
            "Account snapshot",
            "PASS" if snap_ok else "FAIL",
            (
                f"ACTIVE snapshot id={snap.snapshot_id} bound={snap.snapshot_uba_id}"
                if snap_ok
                else "ACTIVE+UBA binding 없음"
            ),
            remediation=None if snap_ok else "계좌 스냅샷 ACTIVE 바인딩을 확인하세요.",
            detail={
                "snapshot_id": snap.snapshot_id,
                "snapshot_status": snap.snapshot_status,
                "snapshot_uba_id": snap.snapshot_uba_id,
            },
        )

        pos_fail = int(snap.unbound_or_cross_uba_positions or 0) > 0
        if pos_fail:
            pos_status, pos_msg = "FAIL", "unbound/cross-UBA position 존재"
        elif int(snap.position_count or 0) == 0:
            pos_status, pos_msg = "WARN", "position count=0"
        else:
            pos_status, pos_msg = "PASS", f"positions={int(snap.position_count)}"
        add(
            "KIWOOM_POSITION_INTEGRITY",
            "Position integrity",
            pos_status,
            pos_msg,
            remediation=None if pos_status != "FAIL" else "포지션 UBA 바인딩을 수정하세요.",
            detail={
                "position_count": int(snap.position_count or 0),
                "unbound_or_cross_uba": int(
                    snap.unbound_or_cross_uba_positions or 0
                ),
            },
        )

        if not snap.uba_risk_present:
            risk_status = "FAIL"
            risk_msg = (
                "UBA risk row 없음 (system DEFAULT fallback 은 LIVE 불허)"
            )
            if snap.user_risk_present:
                risk_msg = "user risk 만 존재 — UBA/account risk 필수"
        elif snap.risk_account_paused:
            risk_status, risk_msg = "FAIL", "risk account_paused=true"
        elif snap.risk_invalid_reason:
            risk_status, risk_msg = "FAIL", snap.risk_invalid_reason
        else:
            risk_status, risk_msg = "PASS", "explicit UBA risk row 유효"
        add(
            "KIWOOM_RISK",
            "Risk",
            risk_status,
            risk_msg,
            remediation=(
                None
                if risk_status == "PASS"
                else "UBA 계좌별 risk 설정을 명시적으로 생성하세요."
            ),
            detail={
                "uba_risk_present": snap.uba_risk_present,
                "user_risk_present": snap.user_risk_present,
                "explicit_uba_risk_required": True,
            },
        )

        add(
            "KILL",
            "Kill switch",
            "FAIL" if snap.kill_active else "PASS",
            "Kill Switch ON" if snap.kill_active else "Kill Switch OFF",
            remediation=None if not snap.kill_active else "Kill Switch 해제",
            detail={"kill_switch_active": bool(snap.kill_active)},
        )

        # LIVE / ARM
        if normalized == "LIVE_ON" and snap.live_armed:
            add(
                "LIVE_ARM_STATE",
                "LIVE/ARM",
                "FAIL",
                "ARM already ON — LIVE ON 전 ARM OFF 필요",
                remediation="ARM OFF 후 LIVE Preflight 를 다시 실행하세요.",
                detail={
                    "live_on": snap.live_order_enabled,
                    "arm_on": snap.live_armed,
                },
            )
        elif not snap.live_order_enabled and not snap.live_armed:
            add(
                "LIVE_ARM_STATE",
                "LIVE/ARM",
                "WARN",
                "LIVE OFF · ARM OFF (정상 대기)",
                remediation="별도 승인 후 LIVE ON → ARM ON",
                detail={"live_on": False, "arm_on": False},
            )
        else:
            add(
                "LIVE_ARM_STATE",
                "LIVE/ARM",
                "PASS",
                (
                    f"LIVE={'ON' if snap.live_order_enabled else 'OFF'} · "
                    f"ARM={'ON' if snap.live_armed else 'OFF'}"
                ),
                detail={
                    "live_on": snap.live_order_enabled,
                    "arm_on": snap.live_armed,
                },
            )

        desired = str(snap.scheduler_desired or "").upper()
        actual = str(snap.scheduler_actual or "").upper()
        running = actual in {"RUN", "RUNNING"} or desired in {"RUN", "RUNNING"}
        paused = (not running) or (
            desired in {"PAUSE", "PAUSED", ""}
            and actual in {"PAUSE", "PAUSED", "STOPPED", ""}
        )
        if running and not snap.live_order_enabled:
            add(
                "SCHEDULER_LIVE_INVARIANT",
                "Scheduler↔LIVE",
                "FAIL",
                "Scheduler RUN + 이 UBA LIVE OFF",
                remediation="Scheduler PAUSE 후 LIVE ON → ARM ON → RUN",
                detail={"desired_state": desired, "actual_state": actual},
            )
        if normalized == "ARM_ON" and running:
            add(
                "SCHEDULER",
                "Scheduler",
                "FAIL",
                "PRE-ARM 은 Scheduler PAUSE 필수",
                remediation="Trading Scheduler 를 PAUSE 하세요.",
                detail={"desired_state": desired, "actual_state": actual},
            )
        elif normalized == "ORDER" and running:
            add(
                "SCHEDULER",
                "Scheduler",
                "PASS",
                "Scheduler RUN (automation readiness)",
                detail={"desired_state": desired, "actual_state": actual},
            )
        else:
            add(
                "SCHEDULER",
                "Scheduler",
                "WARN" if paused else "PASS",
                (
                    "Scheduler PAUSE (수동 주문 안전 대기)"
                    if paused
                    else f"Scheduler desired={desired} actual={actual}"
                ),
                detail={"desired_state": desired, "actual_state": actual},
            )

        closed = snap.krx_is_trading_day is False or str(
            snap.krx_session_type or ""
        ).upper() in {"CLOSED", ""}
        if snap.krx_is_trading_day is None:
            mkt_status = "FAIL" if normalized == "ORDER" else "WARN"
            mkt_msg = "KRX calendar 조회 실패 — fail-closed"
        elif normalized == "ORDER":
            regular_ok = (
                bool(snap.krx_is_trading_day)
                and str(snap.krx_session_type or "").upper() == "REGULAR"
                and snap.krx_in_regular_session is True
            )
            mkt_status = "PASS" if regular_ok else "FAIL"
            mkt_msg = (
                "KRX regular session"
                if regular_ok
                else "KRX closed/holiday/non-regular"
            )
        else:
            mkt_status = "WARN" if closed else "PASS"
            mkt_msg = (
                "KRX closed (PRE-LIVE WARN)"
                if closed
                else "KRX trading day"
            )
        add(
            "KIWOOM_MARKET_SESSION",
            "KRX session",
            mkt_status,
            mkt_msg,
            remediation=(
                None
                if mkt_status != "FAIL"
                else "KRX 정규 거래 시간에 재검사하세요."
            ),
            detail={
                "is_trading_day": snap.krx_is_trading_day,
                "session_type": snap.krx_session_type,
                "reason_code": snap.krx_reason,
                "in_regular_session": snap.krx_in_regular_session,
            },
        )

        # Permission — LIVE flags only (global mock는 execution permission 아님)
        env_live_ok = bool(snap.env_global_live) and bool(snap.env_kiwoom_live)
        env_mock = bool(snap.env_kiwoom_use_mock)
        if normalized == "ORDER":
            env_fail = not env_live_ok
            add(
                "KIWOOM_ENV_LIVE",
                "Env LIVE permission",
                "FAIL" if env_fail else "PASS",
                (
                    "GLOBAL/KIWOOM LIVE flags OFF"
                    if env_fail
                    else "GLOBAL+KIWOOM LIVE permission ON"
                ),
                remediation=(
                    None
                    if not env_fail
                    else "GLOBAL_LIVE_ORDER_ENABLED · KIWOOM_LIVE_ORDER_ENABLED"
                ),
                detail={
                    "global_live_order_enabled": snap.env_global_live,
                    "kiwoom_live_order_enabled": snap.env_kiwoom_live,
                    "kiwoom_use_mock": env_mock,
                    "note": "kiwoom_use_mock is market/shared only",
                },
            )
        else:
            add(
                "KIWOOM_ENV_LIVE",
                "Env LIVE permission",
                "WARN" if not env_live_ok else "PASS",
                "LIVE permission flags (PRE-LIVE WARN only)",
                detail={
                    "global_live_order_enabled": snap.env_global_live,
                    "kiwoom_live_order_enabled": snap.env_kiwoom_live,
                    "kiwoom_use_mock": env_mock,
                    "note": "kiwoom_use_mock is market/shared only",
                },
            )

        if normalized == "SCHEDULER_RUN" and int(snap.strategy_link_count or 0) == 0:
            strat_status, strat_msg = "FAIL", "Scheduler RUN 전 Strategy 연결 0건"
        elif int(snap.strategy_link_count or 0) == 0:
            strat_status, strat_msg = "WARN", "Strategy 연결 0건"
        else:
            strat_status = "PASS"
            strat_msg = f"Strategy 연결 {int(snap.strategy_link_count)}건"
        add(
            "STRATEGY",
            "Strategy",
            strat_status,
            strat_msg,
            detail={"link_count": int(snap.strategy_link_count or 0)},
        )

        synced = snap.snapshot_synchronized_at or snap.last_synced_at
        stale = True
        if synced is not None:
            if synced.tzinfo is None:
                synced = synced.replace(tzinfo=timezone.utc)
            stale = (checked_at - synced).total_seconds() > _FRESHNESS_SECONDS
        add(
            "SYNC_FRESHNESS",
            "Snapshot freshness",
            "WARN" if stale else "PASS",
            "동기화 24h 초과/없음" if stale else "스냅샷 최신",
            detail={
                "synchronized_at": synced.isoformat() if synced else None
            },
        )

        if normalized in {"ARM_ON", "ORDER"}:
            if not snap.live_order_enabled:
                add(
                    "ARM_LIVE_REQUIRED",
                    "LIVE required",
                    "FAIL",
                    "LIVE OFF — ARM/ORDER 불가",
                    remediation="LIVE ON 후 재검사",
                )
            elif snap.arm_precondition_ok is False:
                add(
                    "ARM_PRECONDITION",
                    "ARM preconditions",
                    "FAIL",
                    snap.arm_precondition_message
                    or snap.arm_precondition_code
                    or "ARM 사전조건 실패",
                    remediation="ARM 사전조건을 해소하세요.",
                    detail={"code": snap.arm_precondition_code},
                )
            elif normalized == "ARM_ON" and snap.live_armed:
                add(
                    "ARM_PRECONDITION",
                    "ARM preconditions",
                    "WARN",
                    "ARM already ON (idempotent)",
                )
            elif snap.arm_precondition_ok is True or snap.live_order_enabled:
                add(
                    "ARM_PRECONDITION",
                    "ARM preconditions",
                    "PASS",
                    "ARM 사전조건 충족",
                )

        if normalized == "ORDER":
            armed_ok = bool(snap.live_armed)
            expired = False
            if snap.arm_expires_at is not None:
                exp = snap.arm_expires_at
                if exp.tzinfo is None:
                    exp = exp.replace(tzinfo=timezone.utc)
                expired = exp <= checked_at
            if not armed_ok or expired:
                add(
                    "ARM_TOKEN",
                    "ARM token",
                    "FAIL",
                    "ARM OFF 또는 만료",
                    remediation="ARM ON (유효 토큰) 후 재검사",
                    detail={"live_armed": armed_ok, "expired": expired},
                )
            else:
                add(
                    "ARM_TOKEN",
                    "ARM token",
                    "PASS",
                    "ARM ON · token valid (원문 미포함)",
                )

            blocking = snap.blocking_orders or {}
            blocked = any(int(v or 0) > 0 for v in blocking.values())
            add(
                "PENDING_BLOCKING",
                "Pending/blocking orders",
                "FAIL" if blocked else "PASS",
                (
                    f"blocking_orders={blocking}"
                    if blocked
                    else f"pending_local={int(snap.pending_count or 0)}"
                ),
                remediation=None if not blocked else "미확정/미체결 주문을 해소하세요.",
                detail={
                    "blocking_orders": blocking,
                    "pending_count": int(snap.pending_count or 0),
                },
            )

        return _pack_result(snap, normalized, checks, checked_at, expires_at)

    def _load_snapshot(
        self,
        uba_id: int,
        *,
        owner_user_id: int | None,
        mode: str,
    ) -> KiwoomPreflightSnapshot:
        from stock_platform.broker.account_models import (
            BrokerAccountSnapshotEntity,
            BrokerPositionSnapshotEntity,
        )
        from stock_platform.broker.credential_vault_service import (
            BrokerCredentialVaultService,
        )
        from stock_platform.broker.pending_entities import BrokerPendingOrderEntity
        from stock_platform.broker.recovery_account_state import (
            BrokerRecoveryAccountStateEntity,
        )
        from stock_platform.broker.recovery_conflict_constants import (
            ACTIVE_REVIEW_STATUSES,
        )
        from stock_platform.broker.recovery_conflict_entities import (
            BrokerRecoveryConflictEntity,
        )
        from stock_platform.broker.recovery_conflict_service import (
            BrokerRecoveryConflictService,
        )
        from stock_platform.common.settings import get_settings
        from stock_platform.operation.calendar_repository import (
            TradingCalendarRepository,
        )
        from stock_platform.operation.calendar_service import TradingCalendarService
        from stock_platform.risk_engine.kill_switch_service import KillSwitchService
        from stock_platform.risk_engine.user_risk_entities import (
            UserBrokerAccountRiskSetting,
            UserRiskSetting,
        )
        from stock_platform.trading.account_models import UserBrokerAccount
        from stock_platform.trading.live_arm_service import LiveArmError, LiveArmService

        now = datetime.now(timezone.utc)
        uba = self._session.get(UserBrokerAccount, int(uba_id))
        if uba is None or getattr(uba, "deleted_at", None) is not None:
            return KiwoomPreflightSnapshot(
                uba_id=int(uba_id), user_id=None, deleted=True, now=now
            )
        if owner_user_id is not None and int(uba.user_id) != int(owner_user_id):
            return KiwoomPreflightSnapshot(
                uba_id=int(uba_id),
                user_id=None,
                deleted=True,
                now=now,
            )

        settings = get_settings()
        snap = KiwoomPreflightSnapshot(
            uba_id=int(uba_id),
            user_id=int(uba.user_id),
            is_active=bool(uba.is_active),
            broker_code=str(uba.broker_code or "").upper(),
            connection_status=str(uba.connection_status or ""),
            live_order_enabled=bool(uba.live_order_enabled),
            live_armed=bool(getattr(uba, "live_armed", False)),
            arm_expires_at=getattr(uba, "arm_expires_at", None),
            last_synced_at=getattr(uba, "last_synced_at", None),
            masked_account_number=getattr(uba, "masked_account_number", None),
            env_global_live=bool(
                getattr(settings, "global_live_order_enabled", False)
            ),
            env_kiwoom_live=bool(
                getattr(settings, "kiwoom_live_order_enabled", False)
            ),
            env_kiwoom_use_mock=bool(getattr(settings, "kiwoom_use_mock", False)),
            now=now,
        )

        try:
            st = BrokerCredentialVaultService(self._session).status(int(uba_id))
            snap.vault_available = bool(getattr(st, "vault_available", True))
            snap.credential_present = bool(
                getattr(st, "connected", False)
                or getattr(st, "is_active", False)
                or getattr(st, "verification_status", None)
            )
            snap.credential_verified = (
                str(getattr(st, "verification_status", "") or "").upper()
                == "VERIFIED"
            )
            snap.credential_is_mock = getattr(st, "is_mock", None)
        except Exception:  # noqa: BLE001
            snap.credential_present = False
            snap.credential_verified = False
            snap.credential_is_mock = None

        rec = self._session.scalar(
            select(BrokerRecoveryAccountStateEntity).where(
                BrokerRecoveryAccountStateEntity.user_broker_account_id
                == int(uba_id)
            )
        )
        if rec is not None:
            snap.recovery_status = str(rec.recovery_status or "")
            snap.trading_paused = bool(rec.trading_paused)
            snap.lock_holder = rec.lock_holder
            snap.lock_expires_at = rec.lock_expires_at

        try:
            snap.active_conflicts = int(
                BrokerRecoveryConflictService(
                    self._session
                ).count_active_for_uba(int(uba_id))
            )
            snap.active_high_conflicts = int(
                self._session.scalar(
                    select(func.count())
                    .select_from(BrokerRecoveryConflictEntity)
                    .where(
                        BrokerRecoveryConflictEntity.user_broker_account_id
                        == int(uba_id),
                        BrokerRecoveryConflictEntity.review_status.in_(
                            list(ACTIVE_REVIEW_STATUSES)
                        ),
                        BrokerRecoveryConflictEntity.risk_level == "HIGH",
                    )
                )
                or 0
            )
            snap.blocking_orders = BrokerRecoveryConflictService(
                self._session
            ).count_blocking_orders_for_uba(int(uba_id))
        except Exception:  # noqa: BLE001
            snap.active_conflicts = 0
            snap.active_high_conflicts = 0
            snap.blocking_orders = {}

        acct = self._session.scalar(
            select(BrokerAccountSnapshotEntity).where(
                BrokerAccountSnapshotEntity.user_broker_account_id
                == int(uba_id),
                BrokerAccountSnapshotEntity.snapshot_status == "ACTIVE",
            )
        )
        if acct is not None:
            snap.snapshot_id = int(acct.broker_account_snapshot_id)
            snap.snapshot_status = str(acct.snapshot_status or "")
            snap.snapshot_uba_id = (
                int(acct.user_broker_account_id)
                if acct.user_broker_account_id is not None
                else None
            )
            snap.snapshot_synchronized_at = acct.synchronized_at
            acct_no = str(acct.account_number or "")
            snap.position_count = int(
                self._session.scalar(
                    select(func.count())
                    .select_from(BrokerPositionSnapshotEntity)
                    .where(
                        BrokerPositionSnapshotEntity.user_broker_account_id
                        == int(uba_id)
                    )
                )
                or 0
            )
            if acct_no:
                snap.unbound_or_cross_uba_positions = int(
                    self._session.scalar(
                        select(func.count())
                        .select_from(BrokerPositionSnapshotEntity)
                        .where(
                            BrokerPositionSnapshotEntity.broker_code
                            == "KIWOOM",
                            BrokerPositionSnapshotEntity.account_number
                            == acct_no,
                            (
                                BrokerPositionSnapshotEntity.user_broker_account_id.is_(
                                    None
                                )
                                | (
                                    BrokerPositionSnapshotEntity.user_broker_account_id
                                    != int(uba_id)
                                )
                            ),
                        )
                    )
                    or 0
                )
        else:
            snap.position_count = int(
                self._session.scalar(
                    select(func.count())
                    .select_from(BrokerPositionSnapshotEntity)
                    .where(
                        BrokerPositionSnapshotEntity.user_broker_account_id
                        == int(uba_id)
                    )
                )
                or 0
            )

        risk_row = self._session.scalar(
            select(UserBrokerAccountRiskSetting).where(
                UserBrokerAccountRiskSetting.user_broker_account_id
                == int(uba_id)
            )
        )
        snap.uba_risk_present = risk_row is not None
        if risk_row is not None:
            snap.risk_account_paused = bool(
                getattr(risk_row, "account_paused", False)
            )
            snap.risk_invalid_reason = _validate_risk_row(risk_row)
        user_risk = self._session.scalar(
            select(UserRiskSetting).where(
                UserRiskSetting.user_id == int(uba.user_id)
            )
        )
        snap.user_risk_present = user_risk is not None

        try:
            from stock_platform.trading.account_identity import (
                uba_kill_switch_scope,
            )

            ks = KillSwitchService(self._session)
            scopes = [
                KillSwitchService.GLOBAL_SCOPE,
                f"USER:{int(uba.user_id)}",
                uba_kill_switch_scope(int(uba_id)),
            ]
            snap.kill_active = bool(ks.is_active()) or bool(
                ks.is_active_for_scopes(scopes)
            )
        except Exception:  # noqa: BLE001
            snap.kill_active = True  # fail-closed

        try:
            from stock_platform.trading.upbit_scheduler_readiness import (
                collect_scheduler_readiness,
            )

            sch = collect_scheduler_readiness()
            snap.scheduler_desired = str(
                sch.trading_scheduler_desired_state or ""
            )
            snap.scheduler_actual = str(
                sch.trading_scheduler_actual_state or ""
            )
        except Exception:  # noqa: BLE001
            snap.scheduler_desired = ""
            snap.scheduler_actual = ""

        try:
            kst_now = now.astimezone(_KST)
            decision = TradingCalendarService(
                TradingCalendarRepository(self._session)
            ).evaluate(exchange_code="KRX", calendar_date=kst_now.date())
            snap.krx_is_trading_day = bool(decision.is_trading_day) and bool(
                decision.live_allowed
            )
            snap.krx_session_type = decision.session_type
            snap.krx_reason = decision.reason_code
            open_t = decision.regular_open_at or _DEFAULT_REGULAR_OPEN
            close_t = decision.regular_close_at or _DEFAULT_REGULAR_CLOSE
            snap.krx_in_regular_session = bool(
                snap.krx_is_trading_day
                and str(decision.session_type or "").upper() == "REGULAR"
                and open_t <= kst_now.time() <= close_t
            )
        except Exception:  # noqa: BLE001
            snap.krx_is_trading_day = None
            snap.krx_in_regular_session = None

        try:
            from stock_platform.strategy_deployment.definition_entities import (
                AccountStrategyLinkEntity,
            )

            snap.strategy_link_count = int(
                self._session.scalar(
                    select(func.count())
                    .select_from(AccountStrategyLinkEntity)
                    .where(
                        AccountStrategyLinkEntity.user_broker_account_id
                        == int(uba_id)
                    )
                )
                or 0
            )
        except Exception:  # noqa: BLE001
            snap.strategy_link_count = 0

        try:
            snap.pending_count = int(
                self._session.scalar(
                    select(func.count())
                    .select_from(BrokerPendingOrderEntity)
                    .where(
                        BrokerPendingOrderEntity.user_broker_account_id
                        == int(uba_id)
                    )
                )
                or 0
            )
        except Exception:  # noqa: BLE001
            snap.pending_count = 0

        if mode in {"ARM_ON", "ORDER"} and snap.live_order_enabled:
            try:
                LiveArmService(self._session).assert_arm_enable_preconditions(
                    int(uba_id)
                )
                snap.arm_precondition_ok = True
            except LiveArmError as exc:
                snap.arm_precondition_ok = False
                snap.arm_precondition_code = getattr(exc, "code", None)
                snap.arm_precondition_message = str(exc)
            except Exception as exc:  # noqa: BLE001
                snap.arm_precondition_ok = False
                snap.arm_precondition_code = "arm_precondition_lookup_failed"
                snap.arm_precondition_message = exc.__class__.__name__

        return snap


def evaluate_kiwoom_market_env(
    *,
    mode: str,
    credential_present: bool,
    credential_verified: bool,
    credential_is_mock: bool | None,
    market_use_mock: bool,
) -> tuple[str, str, str | None, dict[str, Any]] | None:
    """KIWOOM_MARKET_ENV — 실제 dependency 기준.

    ORDER(수동 LIMIT): UBA credential-scoped REAL execution/inquiry면
    shared market/WS MOCK이어도 PASS.
    SCHEDULER_RUN(자동): shared market MOCK이면 FAIL-CLOSED.
    LIVE_ON/ARM_ON: 기존 PRE-LIVE WARN 정책 유지.
    반환 None이면 체크 생략 (is_mock 불명 + PRE-LIVE).
    """

    from stock_platform.broker.kiwoom.execution_env import (
        KIWOOM_MOCK_EXECUTION_BASE,
        KIWOOM_REAL_EXECUTION_BASE,
    )

    normalized = str(mode or "LIVE_ON").upper()
    exec_host = (
        KIWOOM_REAL_EXECUTION_BASE
        if credential_is_mock is False
        else (
            KIWOOM_MOCK_EXECUTION_BASE
            if credential_is_mock is True
            else None
        )
    )
    real_aligned = (
        bool(credential_present)
        and bool(credential_verified)
        and credential_is_mock is False
    )
    detail: dict[str, Any] = {
        "execution_is_mock": credential_is_mock,
        "market_use_mock": bool(market_use_mock),
        "kiwoom_use_mock": bool(market_use_mock),
        "execution_host": exec_host,
        "mode": normalized,
        "path": (
            "MANUAL"
            if normalized == "ORDER"
            else ("AUTO" if normalized == "SCHEDULER_RUN" else normalized)
        ),
        "shared_ws_mock": bool(market_use_mock),
    }

    if normalized in {"ORDER", "SCHEDULER_RUN"}:
        if not real_aligned:
            if not credential_present:
                msg = "credential missing — MARKET_ENV fail-closed"
                rem = "Kiwoom credential 을 등록·검증하세요."
            elif not credential_verified:
                msg = "credential unverified — MARKET_ENV fail-closed"
                rem = "Credential 검증을 완료하세요."
            elif credential_is_mock is None:
                msg = "credential is_mock 불명 — MARKET_ENV fail-closed"
                rem = "credential is_mock=false 를 확인하세요."
            else:
                msg = "mock credential — REAL manual/auto path 불가"
                rem = "REAL credential(is_mock=false)을 사용하세요."
            return "FAIL", msg, rem, detail
        if not market_use_mock:
            return (
                "PASS",
                "execution REAL · market REAL",
                None,
                detail,
            )
        if normalized == "ORDER":
            return (
                "PASS",
                (
                    "execution REAL · shared market MOCK — "
                    "MANUAL LIMIT uses UBA-scoped execution/inquiry"
                ),
                None,
                {**detail, "manual_limit_shared_market_ok": True},
            )
        return (
            "FAIL",
            (
                "execution REAL · shared market MOCK — "
                "AUTO/Scheduler requires shared REAL market/WS"
            ),
            "AUTO 경로는 shared market/scanner/WS REAL 이 필요합니다.",
            {**detail, "auto_requires_shared_real_market": True},
        )

    # LIVE_ON / ARM_ON — 기존 PRE-LIVE 정책 (is_mock만 사용)
    if credential_is_mock is False and market_use_mock:
        return (
            "WARN",
            "execution REAL · shared market MOCK (PRE-LIVE WARN)",
            "Market/WS REAL 정책은 별도 STEP에서 검토하세요.",
            detail,
        )
    if credential_is_mock is False and not market_use_mock:
        return (
            "PASS",
            "execution REAL · market REAL",
            None,
            detail,
        )
    if credential_is_mock is True:
        return (
            "PASS",
            "MOCK execution · shared market MOCK",
            None,
            detail,
        )
    return None


def _normalize_mode(mode: str) -> str:
    raw = str(mode or "LIVE_ON").upper()
    if raw in {"LIVE_ON", "ARM_ON", "ORDER", "SCHEDULER_RUN"}:
        return raw
    return "LIVE_ON"


def _lock_is_active(snap: KiwoomPreflightSnapshot, now: datetime) -> bool:
    rec = str(snap.recovery_status or "").upper()
    if rec == "RUNNING":
        return True
    expires = snap.lock_expires_at
    if expires is None:
        return bool(snap.lock_holder)
    if expires.tzinfo is None:
        expires = expires.replace(tzinfo=timezone.utc)
    return expires > now


def _validate_risk_row(row: Any) -> str | None:
    if bool(getattr(row, "account_paused", False)):
        return "risk account_paused=true"
    for attr in ("max_order_amount", "daily_max_loss_amount"):
        raw = getattr(row, attr, None)
        if raw is None:
            continue
        try:
            if Decimal(str(raw)) <= 0:
                return f"risk {attr} must be > 0"
        except (TypeError, ValueError, ArithmeticError):
            return f"risk {attr} invalid"
    return None


def _pack_result(
    snap: KiwoomPreflightSnapshot,
    mode: str,
    checks: list[dict[str, Any]],
    checked_at: datetime,
    expires_at: datetime,
) -> dict[str, Any]:
    from stock_platform.operation.runtime_preflight_service import (
        PREFLIGHT_TTL_SECONDS,
    )

    fail_count = sum(1 for c in checks if c.get("status") == "FAIL")
    blocked = fail_count > 0
    if blocked:
        overall = "BLOCKED"
        ready_key = None
    elif mode == "ARM_ON":
        overall = "READY_FOR_ARM"
        ready_key = "NOW"
    elif mode == "ORDER":
        overall = "READY_FOR_ORDER"
        ready_key = "NOW"
    else:
        overall = "READY_FOR_LIVE"
        ready_key = "NOW"

    blockers = [
        {
            "code": c["code"],
            "message": c["message"],
            "status": c["status"],
            "remediation": c.get("remediation"),
        }
        for c in checks
        if c.get("status") == "FAIL"
    ]
    warnings = [
        {
            "code": c["code"],
            "message": c["message"],
            "status": c["status"],
            "remediation": c.get("remediation"),
        }
        for c in checks
        if c.get("status") == "WARN"
    ]
    return {
        "mode": mode,
        "scope": "UBA",
        "user_broker_account_id": snap.uba_id,
        "broker_code": str(snap.broker_code or "").upper() or None,
        "account_kind": "LIVE",
        "execution_mode": "LIVE",
        "overall": overall,
        "overall_status": overall,
        "estimated_ready": ready_key,
        "live_on_allowed": (not blocked) and mode == "LIVE_ON",
        "manual_order_allowed": (not blocked) and mode == "ORDER",
        "arm_on_allowed": (not blocked) and mode == "ARM_ON",
        "freshness": {
            "ttl_seconds": PREFLIGHT_TTL_SECONDS,
            "checked_at": checked_at.isoformat(),
            "expires_at": expires_at.isoformat(),
            "status": "FRESH",
        },
        "checked_at": checked_at.isoformat(),
        "expires_at": expires_at.isoformat(),
        "checks": checks,
        "warnings": warnings,
        "blockers": blockers,
        "summary": {
            "pass": sum(1 for c in checks if c.get("status") == "PASS"),
            "warn": sum(1 for c in checks if c.get("status") == "WARN"),
            "fail": fail_count,
            "not_applicable": sum(
                1 for c in checks if c.get("status") == "NOT_APPLICABLE"
            ),
            "total": len(checks),
        },
    }
