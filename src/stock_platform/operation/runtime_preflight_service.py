"""STEP 9-7 — Runtime Pre-flight Check (LIVE ON 전 자동 점검, 조회 전용).

안전 규칙:
- DB 상태 변경 금지
- 실주문/취소/정정 금지
- Broker는 조회 전용만
- Credential 원문·Access/Secret Key·ARM token 응답 금지
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Literal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from stock_platform.common.settings import get_settings
from stock_platform.operation.db_pool_monitor import measure_db_latency_ms
from stock_platform.operation.health_service import check_database

PreflightMode = Literal["LIVE_ON", "SCHEDULER_RUN"]
CheckStatus = str  # PASS | WARN | FAIL | NOT_APPLICABLE

PREFLIGHT_TTL_SECONDS = 60

_SENSITIVE_KEYS = frozenset(
    {
        "token",
        "arm_token",
        "access_token",
        "refresh_token",
        "password",
        "account_number",
        "secret",
        "secret_key",
        "api_key",
        "api_secret",
        "access_key",
        "authorization",
        "ciphertext",
        "encrypted",
        "private_key",
        "stack",
        "traceback",
        "exc_info",
    }
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def sanitize_preflight_payload(value: Any) -> Any:
    """응답·PDF·JSON용 민감정보 제거 (재귀)."""

    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, raw in value.items():
            lowered = str(key).lower()
            # 키 이름 자체가 비밀인 경우만 제거
            # (token_configured 같은 플래그 키는 유지)
            exact_ban = lowered in _SENSITIVE_KEYS
            suffix_ban = any(
                lowered.endswith(sfx)
                for sfx in (
                    "_secret",
                    "_token",
                    "_password",
                    "_ciphertext",
                    "_key",
                    "traceback",
                    "stack_trace",
                    "exc_info",
                )
            )
            # authorization / ciphertext / encrypted 단독 키
            name_ban = lowered in {
                "authorization",
                "ciphertext",
                "encrypted",
                "traceback",
                "stack",
                "exc_info",
                "secret",
                "token",
                "password",
            }
            if exact_ban or suffix_ban or name_ban:
                continue
            out[str(key)] = sanitize_preflight_payload(raw)
        return out
    if isinstance(value, list):
        return [sanitize_preflight_payload(v) for v in value]
    if isinstance(value, tuple):
        return [sanitize_preflight_payload(v) for v in value]
    return value


def _item(
    *,
    code: str,
    name: str,
    status: CheckStatus,
    message: str,
    remediation: str | None = None,
    detail: dict[str, Any] | None = None,
    checked_at: datetime | None = None,
) -> dict[str, Any]:
    normalized = str(status or "WARN").upper()
    if normalized not in {"PASS", "WARN", "FAIL", "NOT_APPLICABLE"}:
        normalized = "WARN"
    blocking = normalized == "FAIL"
    checked = checked_at or _utcnow()
    return {
        "code": code,
        "name": name,
        "status": normalized,
        "blocking": blocking,
        "message": message,
        "detail": sanitize_preflight_payload(detail or {}),
        "checked_at": checked.isoformat(),
        "remediation": remediation,
    }


def _check_broker(session: Session) -> dict[str, Any]:
    """Broker 설정·헬스 (조회 전용)."""
    settings = get_settings()
    try:
        from stock_platform.operation.live_health_gate import (
            evaluate_live_order_health,
        )

        health = evaluate_live_order_health(session)
        allowed = bool(health.get("live_orders_allowed"))
        status_raw = str(health.get("status") or "").upper()
        detail = {
            "health_status": status_raw,
            "live_orders_allowed": allowed,
            "kiwoom_use_mock": bool(settings.kiwoom_use_mock),
            "global_live_order_enabled": bool(
                settings.global_live_order_enabled
            ),
            "upbit_live_order_enabled": bool(
                settings.upbit_live_order_enabled
            ),
            "kiwoom_live_order_enabled": bool(
                settings.kiwoom_live_order_enabled
            ),
        }
        if not allowed or status_raw in {
            "DOWN",
            "UNHEALTHY",
            "FAIL",
            "ERROR",
        }:
            return _item(
                code="BROKER",
                name="Broker",
                status="FAIL",
                message=f"Broker 연결/헬스 실패 (status={status_raw or 'UNKNOWN'})",
                remediation="Broker 연결·헬스 상태를 복구한 뒤 재검사하세요.",
                detail=detail,
            )
        if settings.kiwoom_live_order_enabled and settings.kiwoom_use_mock:
            return _item(
                code="BROKER",
                name="Broker",
                status="FAIL",
                message="LIVE + Mock 동시 활성 충돌",
                remediation="kiwoom_use_mock 또는 live flag 중 하나를 해제하세요.",
                detail=detail,
            )
        return _item(
            code="BROKER",
            name="Broker",
            status="PASS",
            message="Broker 헬스 정상",
            detail=detail,
        )
    except Exception as exc:  # noqa: BLE001
        return _item(
            code="BROKER",
            name="Broker",
            status="FAIL",
            message=f"Broker 점검 실패: {exc.__class__.__name__}",
            remediation="Broker 헬스 게이트 로그를 확인하세요.",
            detail={"error_type": exc.__class__.__name__},
        )


def _check_credential(session: Session) -> dict[str, Any]:
    """전역 스캔 — 타 계좌 미검증은 WARN(Reference). LIVE ON 은 UBA 스코프 검사."""
    try:
        from stock_platform.broker.credential_vault_service import (
            BrokerCredentialVaultService,
        )
        from stock_platform.trading.account_models import UserBrokerAccount

        ubas = list(
            session.scalars(
                select(UserBrokerAccount)
                .where(
                    UserBrokerAccount.is_active.is_(True),
                    UserBrokerAccount.deleted_at.is_(None),
                )
                .limit(100)
            )
        )
        vault = BrokerCredentialVaultService(session)
        verified = 0
        unverified = 0
        unverified_ids: list[int] = []
        for uba in ubas:
            try:
                # status() 만 사용 — 복호화/원문 접근 금지
                st = vault.status(int(uba.user_broker_account_id))
                if (
                    str(getattr(st, "verification_status", "") or "").upper()
                    == "VERIFIED"
                ):
                    verified += 1
                else:
                    unverified += 1
                    unverified_ids.append(int(uba.user_broker_account_id))
            except Exception:  # noqa: BLE001
                unverified += 1
                unverified_ids.append(int(uba.user_broker_account_id))
        detail = {
            "scope": "global_reference",
            "active_uba_checked": len(ubas),
            "verified": verified,
            "unverified_or_missing": unverified,
            "unverified_uba_ids_sample": unverified_ids[:20],
        }
        if ubas and unverified > 0:
            return _item(
                code="CREDENTIAL",
                name="Credential",
                status="WARN",
                message=(
                    f"타 계좌 Credential 미검증 {unverified}건 "
                    f"(선택 UBA LIVE ON 비차단 · Reference)"
                ),
                remediation="LIVE ON 은 선택 UBA 단위 Pre-flight 로 재검증합니다.",
                detail=detail,
            )
        return _item(
            code="CREDENTIAL",
            name="Credential",
            status="PASS",
            message=f"Credential VERIFIED {verified}/{len(ubas)}",
            detail=detail,
        )
    except Exception as exc:  # noqa: BLE001
        return _item(
            code="CREDENTIAL",
            name="Credential",
            status="FAIL",
            message=f"Credential 점검 실패: {exc.__class__.__name__}",
            remediation="Credential vault 서비스 상태를 확인하세요.",
            detail={"error_type": exc.__class__.__name__},
        )


def _check_connection(session: Session) -> dict[str, Any]:
    """전역 스캔 — 미연결 타 계좌는 WARN(Reference)."""
    try:
        from stock_platform.trading.account_models import UserBrokerAccount

        rows = list(
            session.scalars(
                select(UserBrokerAccount)
                .where(
                    UserBrokerAccount.is_active.is_(True),
                    UserBrokerAccount.deleted_at.is_(None),
                )
                .limit(100)
            )
        )
        connected = 0
        not_connected_ids: list[int] = []
        for row in rows:
            conn = str(getattr(row, "connection_status", "") or "").upper()
            if conn in {"CONNECTED", "VERIFIED"}:
                connected += 1
            else:
                not_connected_ids.append(int(row.user_broker_account_id))
        detail = {
            "scope": "global_reference",
            "active_uba": len(rows),
            "connected": connected,
            "not_connected_count": len(not_connected_ids),
            "not_connected_uba_ids_sample": not_connected_ids[:20],
        }
        if not_connected_ids:
            return _item(
                code="CONNECTION",
                name="Connection",
                status="WARN",
                message=(
                    f"connection_status != CONNECTED 계좌 "
                    f"{len(not_connected_ids)}건 (선택 UBA LIVE ON 비차단 · Reference)"
                ),
                remediation="LIVE ON 은 선택 UBA 단위 Pre-flight 로 재검증합니다.",
                detail=detail,
            )
        return _item(
            code="CONNECTION",
            name="Connection",
            status="PASS",
            message=f"CONNECTED {connected}/{len(rows)}",
            detail=detail,
        )
    except Exception as exc:  # noqa: BLE001
        return _item(
            code="CONNECTION",
            name="Connection",
            status="FAIL",
            message=f"Connection 점검 실패: {exc.__class__.__name__}",
            remediation="UBA connection_status 조회 경로를 확인하세요.",
            detail={"error_type": exc.__class__.__name__},
        )


def _safe_int_id(value: Any) -> int | None:
    """NULL PK/FK 를 int() 하지 않음 — TypeError 방지."""
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _check_recovery(session: Session) -> dict[str, Any]:
    """전역 Recovery — 타 계좌 paused/비정상은 WARN. int(None) TypeError 금지."""
    try:
        from stock_platform.broker.recovery_account_state import (
            BrokerRecoveryAccountStateEntity,
        )

        rows = list(
            session.scalars(select(BrokerRecoveryAccountStateEntity).limit(200))
        )
        paused = 0
        abnormal = 0
        abnormal_sample: list[dict[str, Any]] = []
        ok_statuses = {"SUCCESS", "READY", "IDLE", ""}
        for row in rows:
            if bool(getattr(row, "trading_paused", False)):
                paused += 1
            status = str(getattr(row, "recovery_status", "") or "").upper()
            if status and status not in ok_statuses:
                if status in {"MANUAL_REVIEW", "RUNNING", "FAILED"}:
                    abnormal += 1
                    if len(abnormal_sample) < 10:
                        uba_id = _safe_int_id(
                            getattr(row, "user_broker_account_id", None)
                        )
                        paper_id = _safe_int_id(
                            getattr(row, "paper_account_id", None)
                        )
                        abnormal_sample.append(
                            {
                                "uba_id": uba_id,
                                "paper_account_id": paper_id,
                                "recovery_status": status,
                            }
                        )
        detail = {
            "scope": "global_reference",
            "states_checked": len(rows),
            "trading_paused_count": paused,
            "abnormal_recovery_count": abnormal,
            "abnormal_sample": abnormal_sample,
        }
        if paused > 0 or abnormal > 0:
            return _item(
                code="RECOVERY",
                name="Recovery",
                status="WARN",
                message=(
                    f"타 계좌 Recovery 이슈 paused={paused} abnormal={abnormal} "
                    f"(선택 UBA LIVE ON 비차단 · Reference)"
                ),
                remediation="LIVE ON 은 선택 UBA 단위 Pre-flight 로 재검증합니다.",
                detail=detail,
            )
        return _item(
            code="RECOVERY",
            name="Recovery",
            status="PASS",
            message="Recovery 정상 · trading_paused=0",
            detail=detail,
        )
    except Exception as exc:  # noqa: BLE001
        return _item(
            code="RECOVERY",
            name="Recovery",
            status="FAIL",
            message=f"Recovery 점검 실패: {exc.__class__.__name__}",
            remediation="Recovery account state 테이블 접근을 확인하세요.",
            detail={"error_type": exc.__class__.__name__},
        )


def _check_conflict(session: Session) -> dict[str, Any]:
    """전역 Conflict — 활성 Conflict 는 WARN(Reference). UBA 스코프에서 FAIL."""
    try:
        from stock_platform.broker.recovery_conflict_constants import (
            ACTIVE_REVIEW_STATUSES,
        )
        from stock_platform.broker.recovery_conflict_entities import (
            BrokerRecoveryConflictEntity,
        )

        active = int(
            session.scalar(
                select(func.count())
                .select_from(BrokerRecoveryConflictEntity)
                .where(
                    BrokerRecoveryConflictEntity.review_status.in_(
                        list(ACTIVE_REVIEW_STATUSES)
                    )
                )
            )
            or 0
        )
        detail = {
            "scope": "global_reference",
            "active_blocking_conflicts": active,
        }
        if active > 0:
            return _item(
                code="CONFLICT",
                name="Conflict",
                status="WARN",
                message=(
                    f"활성 Conflict {active}건 "
                    f"(선택 UBA LIVE ON 비차단 · Reference)"
                ),
                remediation="LIVE ON 은 선택 UBA 단위 Pre-flight 로 재검증합니다.",
                detail=detail,
            )
        return _item(
            code="CONFLICT",
            name="Conflict",
            status="PASS",
            message="활성 차단 Conflict 0건",
            detail=detail,
        )
    except Exception as exc:  # noqa: BLE001
        return _item(
            code="CONFLICT",
            name="Conflict",
            status="FAIL",
            message=f"Conflict 점검 실패: {exc.__class__.__name__}",
            remediation="Recovery Conflict 조회 경로를 확인하세요.",
            detail={"error_type": exc.__class__.__name__},
        )


def _check_runtime() -> dict[str, Any]:
    """Runtime 조회 — LIVE ON 전 runner idle 이 정상."""
    try:
        from stock_platform.realtime.runtime import (
            realtime_execution_runner,
            realtime_strategy_runner,
        )

        exec_st = realtime_execution_runner.status() or {}
        strat_st = realtime_strategy_runner.status() or {}
        detail = {
            "execution_running": bool(exec_st.get("running")),
            "strategy_running": bool(strat_st.get("running")),
            "active_scopes": int(strat_st.get("active_scopes") or 0),
        }
        return _item(
            code="RUNTIME",
            name="Runtime",
            status="PASS",
            message="Runtime 조회 정상 (LIVE ON 전 대기 가능)",
            detail=detail,
        )
    except Exception as exc:  # noqa: BLE001
        return _item(
            code="RUNTIME",
            name="Runtime",
            status="WARN",
            message=f"Runtime 점검 실패: {exc.__class__.__name__}",
            remediation="비필수 Runtime 모니터링을 확인하세요.",
            detail={"error_type": exc.__class__.__name__},
        )


def _check_scheduler() -> dict[str, Any]:
    """LIVE OFF/ARM OFF/Scheduler PAUSE 는 정상 대기 → WARN 또는 PASS."""
    try:
        from stock_platform.trading.upbit_scheduler_readiness import (
            collect_scheduler_readiness,
        )

        snap = collect_scheduler_readiness()
        desired = str(snap.trading_scheduler_desired_state or "").upper()
        actual = str(snap.trading_scheduler_actual_state or "").upper()
        detail = {
            "desired_state": desired,
            "actual_state": actual,
            "trading_running": bool(getattr(snap, "trading_running", False)),
        }
        paused = desired in {"PAUSE", "PAUSED", ""} and actual in {
            "PAUSE",
            "PAUSED",
            "STOPPED",
            "",
        }
        if paused:
            return _item(
                code="SCHEDULER",
                name="Scheduler",
                status="WARN",
                message="Scheduler PAUSE (LIVE ON 전 정상 대기)",
                remediation="LIVE→ARM 완료 후 별도 승인으로 Scheduler RUN 을 진행하세요.",
                detail=detail,
            )
        return _item(
            code="SCHEDULER",
            name="Scheduler",
            status="WARN",
            message=f"Scheduler desired={desired} actual={actual}",
            remediation="LIVE ON 전에는 Scheduler PAUSE 를 유지하세요.",
            detail=detail,
        )
    except Exception as exc:  # noqa: BLE001
        return _item(
            code="SCHEDULER",
            name="Scheduler",
            status="WARN",
            message=f"Scheduler 점검 실패: {exc.__class__.__name__}",
            remediation="비필수 Scheduler 모니터링을 확인하세요.",
            detail={"error_type": exc.__class__.__name__},
        )


def _check_scheduler_live_invariant(session: Session) -> dict[str, Any]:
    """Scheduler RUN 이면 최소 1개 UBA LIVE ON 필수 (불변식)."""
    try:
        from stock_platform.trading.account_models import UserBrokerAccount
        from stock_platform.trading.upbit_scheduler_readiness import (
            collect_scheduler_readiness,
        )

        snap = collect_scheduler_readiness()
        desired = str(snap.trading_scheduler_desired_state or "").upper()
        actual = str(snap.trading_scheduler_actual_state or "").upper()
        running = bool(getattr(snap, "trading_running", False)) or actual in {
            "RUN",
            "RUNNING",
        }
        desired_run = desired in {"RUN", "RUNNING"}
        live_on = int(
            session.scalar(
                select(func.count())
                .select_from(UserBrokerAccount)
                .where(
                    UserBrokerAccount.is_active.is_(True),
                    UserBrokerAccount.deleted_at.is_(None),
                    UserBrokerAccount.live_order_enabled.is_(True),
                )
            )
            or 0
        )
        detail = {
            "desired_state": desired,
            "actual_state": actual,
            "trading_running": running,
            "live_on_count": live_on,
        }
        if (running or desired_run) and live_on <= 0:
            return _item(
                code="SCHEDULER_LIVE_INVARIANT",
                name="Scheduler↔LIVE",
                status="FAIL",
                message="Scheduler RUN + LIVE OFF (불변식 위반)",
                remediation=(
                    "Fail Closed: Scheduler PAUSE 후 "
                    "Resume → Pre-flight → LIVE ON → ARM ON → Scheduler RUN"
                ),
                detail=detail,
            )
        return _item(
            code="SCHEDULER_LIVE_INVARIANT",
            name="Scheduler↔LIVE",
            status="PASS",
            message="Scheduler/LIVE 불변식 OK",
            remediation=None,
            detail=detail,
        )
    except Exception as exc:  # noqa: BLE001
        return _item(
            code="SCHEDULER_LIVE_INVARIANT",
            name="Scheduler↔LIVE",
            status="WARN",
            message=f"불변식 점검 실패: {exc.__class__.__name__}",
            remediation="Scheduler·LIVE 상태를 수동 확인하세요.",
            detail={"error_type": exc.__class__.__name__},
        )


def _check_live_arm_flags(session: Session) -> dict[str, Any]:
    """LIVE OFF / ARM OFF 는 LIVE ON 전 정상 대기 → WARN (BLOCKED 아님)."""
    try:
        from stock_platform.trading.account_models import UserBrokerAccount

        live_on = int(
            session.scalar(
                select(func.count())
                .select_from(UserBrokerAccount)
                .where(
                    UserBrokerAccount.is_active.is_(True),
                    UserBrokerAccount.deleted_at.is_(None),
                    UserBrokerAccount.live_order_enabled.is_(True),
                )
            )
            or 0
        )
        arm_on = int(
            session.scalar(
                select(func.count())
                .select_from(UserBrokerAccount)
                .where(
                    UserBrokerAccount.is_active.is_(True),
                    UserBrokerAccount.deleted_at.is_(None),
                    UserBrokerAccount.live_armed.is_(True),
                )
            )
            or 0
        )
        detail = {"live_on_count": live_on, "arm_on_count": arm_on}
        if live_on == 0 and arm_on == 0:
            return _item(
                code="LIVE_ARM_STATE",
                name="LIVE/ARM",
                status="WARN",
                message="LIVE OFF · ARM OFF (LIVE ON 전 정상 대기)",
                remediation="Pre-flight READY 후 별도 승인으로 LIVE ON → ARM ON 순서로 진행하세요.",
                detail=detail,
            )
        if arm_on > 0 and live_on == 0:
            return _item(
                code="LIVE_ARM_STATE",
                name="LIVE/ARM",
                status="WARN",
                message="ARM ON 인데 LIVE OFF — 상태 불일치 점검",
                remediation="DISARM 후 LIVE ON → ARM ON 순서를 맞추세요.",
                detail=detail,
            )
        return _item(
            code="LIVE_ARM_STATE",
            name="LIVE/ARM",
            status="PASS",
            message=f"LIVE ON {live_on} · ARM ON {arm_on}",
            detail=detail,
        )
    except Exception as exc:  # noqa: BLE001
        return _item(
            code="LIVE_ARM_STATE",
            name="LIVE/ARM",
            status="WARN",
            message=f"LIVE/ARM 점검 실패: {exc.__class__.__name__}",
            remediation="UBA LIVE/ARM 플래그 조회를 확인하세요.",
            detail={"error_type": exc.__class__.__name__},
        )


def _check_risk(session: Session) -> dict[str, Any]:
    try:
        from stock_platform.risk_engine.kill_switch_service import (
            KillSwitchService,
        )
        from stock_platform.risk_engine.user_risk_entities import (
            UserBrokerAccountRiskSetting,
        )

        kill_active = bool(KillSwitchService(session).is_active())
        paused_accounts = int(
            session.scalar(
                select(func.count())
                .select_from(UserBrokerAccountRiskSetting)
                .where(UserBrokerAccountRiskSetting.account_paused.is_(True))
            )
            or 0
        )
        detail = {
            "scope": "global_reference",
            "kill_switch_active": kill_active,
            "account_paused_count": paused_accounts,
        }
        if kill_active:
            return _item(
                code="RISK",
                name="Risk",
                status="FAIL",
                message="Kill Switch ON",
                remediation="Kill Switch 를 해제한 뒤 재검사하세요.",
                detail=detail,
            )
        if paused_accounts > 0:
            return _item(
                code="RISK",
                name="Risk",
                status="WARN",
                message=(
                    f"account_paused=true 계좌 {paused_accounts}건 "
                    f"(선택 UBA LIVE ON 비차단 · Reference)"
                ),
                remediation="LIVE ON 은 선택 UBA 단위 Pre-flight 로 재검증합니다.",
                detail=detail,
            )
        return _item(
            code="RISK",
            name="Risk",
            status="PASS",
            message="Kill Switch OFF · account_paused=0",
            detail=detail,
        )
    except Exception as exc:  # noqa: BLE001
        return _item(
            code="RISK",
            name="Risk",
            status="FAIL",
            message=f"Risk 설정 점검 실패: {exc.__class__.__name__}",
            remediation="Risk/KillSwitch 서비스를 확인하세요.",
            detail={"error_type": exc.__class__.__name__},
        )


def _check_strategy(*, mode: PreflightMode) -> dict[str, Any]:
    """활성 Strategy 0건: LIVE ON 전 WARN, Scheduler RUN 전 FAIL."""
    try:
        from stock_platform.realtime.runtime import realtime_strategy_runner
        from stock_platform.strategy_deployment.runtime_manager import (
            dynamic_strategy_runtime_manager,
        )

        st = realtime_strategy_runner.status() or {}
        mgr = dynamic_strategy_runtime_manager.status() or {}
        active_scopes = int(
            (st.get("active_scopes") if isinstance(st, dict) else 0) or 0
        )
        running_count = 0
        if isinstance(mgr, dict):
            running_count = int(
                mgr.get("running_count")
                or mgr.get("scoped_runtime_count")
                or 0
            )
        detail = {
            "mode": mode,
            "active_scopes": active_scopes,
            "running_count": running_count,
        }
        zero = active_scopes == 0 and running_count == 0
        if mode == "SCHEDULER_RUN" and zero:
            return _item(
                code="STRATEGY",
                name="Strategy",
                status="FAIL",
                message="Scheduler RUN 전 활성 Strategy 0건",
                remediation="실행할 Strategy Runtime 을 준비한 뒤 재검사하세요.",
                detail=detail,
            )
        if mode == "LIVE_ON" and zero:
            return _item(
                code="STRATEGY",
                name="Strategy",
                status="WARN",
                message="활성 Strategy 0건 (LIVE ON 전 대기 — BLOCKED 아님)",
                remediation="Scheduler RUN 전에 Strategy 를 준비하세요.",
                detail=detail,
            )
        return _item(
            code="STRATEGY",
            name="Strategy",
            status="PASS",
            message=f"Strategy scopes={active_scopes} running={running_count}",
            detail=detail,
        )
    except Exception as exc:  # noqa: BLE001
        return _item(
            code="STRATEGY",
            name="Strategy",
            status="WARN",
            message=f"Strategy 점검 실패: {exc.__class__.__name__}",
            remediation="비필수 Strategy 모니터링을 확인하세요.",
            detail={"error_type": exc.__class__.__name__},
        )


def _check_telegram() -> dict[str, Any]:
    settings = get_settings()
    enabled = bool(getattr(settings, "telegram_enabled", False))
    token_set = bool(str(getattr(settings, "telegram_bot_token", "") or "").strip())
    chat_set = bool(str(getattr(settings, "telegram_chat_id", "") or "").strip())
    detail = {
        "enabled": enabled,
        "token_configured": token_set,
        "chat_configured": chat_set,
    }
    if not enabled:
        return _item(
            code="TELEGRAM",
            name="Telegram",
            status="WARN",
            message="Telegram 미설정/비활성",
            remediation="알림이 필요하면 Telegram 설정을 활성화하세요.",
            detail=detail,
        )
    if not token_set or not chat_set:
        return _item(
            code="TELEGRAM",
            name="Telegram",
            status="WARN",
            message="Telegram 토큰/채팅 미구성",
            remediation="telegram_bot_token · chat_id 를 구성하세요.",
            detail=detail,
        )
    return _item(
        code="TELEGRAM",
        name="Telegram",
        status="PASS",
        message="Telegram 설정 정상",
        detail=detail,
    )


def _check_database(session: Session) -> dict[str, Any]:
    db = check_database()
    latency_status, latency_ms, latency_err = measure_db_latency_ms()
    detail = {
        "database_status": db.get("status"),
        "latency_ms": latency_ms,
        "latency_status": latency_status,
    }
    try:
        session.execute(select(1))
    except Exception as exc:  # noqa: BLE001
        return _item(
            code="DATABASE",
            name="Database",
            status="FAIL",
            message=f"Database 접근 실패: {exc.__class__.__name__}",
            remediation="DB 연결·권한을 복구하세요.",
            detail={**detail, "error_type": exc.__class__.__name__},
        )
    if str(db.get("status") or "").upper() == "DOWN":
        return _item(
            code="DATABASE",
            name="Database",
            status="FAIL",
            message=str(db.get("message") or "Database DOWN"),
            remediation="DB 인스턴스·네트워크를 확인하세요.",
            detail=detail,
        )
    if str(latency_status or "").upper() in {"DOWN", "ERROR", "FAIL"}:
        return _item(
            code="DATABASE",
            name="Database",
            status="FAIL",
            message=f"DB latency check failed ({latency_err})",
            remediation="DB 응답 지연/장애를 해소하세요.",
            detail=detail,
        )
    if latency_ms is not None and float(latency_ms) > 500:
        return _item(
            code="DATABASE",
            name="Database",
            status="WARN",
            message=f"DB latency {latency_ms}ms (높음)",
            remediation="비필수 성능 모니터링 — LIVE ON 은 막지 않습니다.",
            detail=detail,
        )
    return _item(
        code="DATABASE",
        name="Database",
        status="PASS",
        message=f"Database UP · latency={latency_ms}ms",
        detail=detail,
    )


def _check_redis() -> dict[str, Any]:
    settings = get_settings()
    redis_url = str(
        getattr(settings, "redis_url", None)
        or getattr(settings, "REDIS_URL", None)
        or ""
    ).strip()
    if not redis_url:
        return _item(
            code="REDIS",
            name="Redis",
            status="NOT_APPLICABLE",
            message="Redis 미사용 (필수 구성 아님)",
            remediation=None,
            detail={"configured": False, "required": False},
        )
    try:
        import redis  # type: ignore[import-untyped]

        client = redis.from_url(redis_url, socket_connect_timeout=1.5)
        client.ping()
        return _item(
            code="REDIS",
            name="Redis",
            status="PASS",
            message="Redis PING OK",
            detail={"configured": True},
        )
    except Exception as exc:  # noqa: BLE001
        # 구성된 경우에만 FAIL (주문·락 경로 영향 가능)
        return _item(
            code="REDIS",
            name="Redis",
            status="FAIL",
            message=f"Redis 장애: {exc.__class__.__name__}",
            remediation="구성된 Redis 연결을 복구하거나 설정을 비활성화하세요.",
            detail={"configured": True, "error_type": exc.__class__.__name__},
        )


def _check_api_health() -> dict[str, Any]:
    try:
        from stock_platform.operation.release_operation_readiness import (
            build_operation_health,
        )

        snap = build_operation_health()
        components = snap if isinstance(snap, dict) else {}
        statuses: list[str] = []
        for value in components.values():
            if isinstance(value, dict) and "status" in value:
                statuses.append(str(value.get("status") or "").upper())
        if any(s in {"DOWN", "FAIL", "ERROR", "UNHEALTHY"} for s in statuses):
            return _item(
                code="API_HEALTH",
                name="API Health",
                status="FAIL",
                message="API Health 실패 (컴포넌트 DOWN/UNHEALTHY)",
                remediation="장애 컴포넌트를 복구한 뒤 재검사하세요.",
                detail={"component_keys": list(components.keys())[:20]},
            )
        if any(s in {"DEGRADED", "WARN", "WARNING"} for s in statuses):
            return _item(
                code="API_HEALTH",
                name="API Health",
                status="WARN",
                message="API Health 일부 저하 (비필수)",
                remediation="모니터링 경고를 확인하세요. LIVE ON 은 막지 않습니다.",
                detail={"component_keys": list(components.keys())[:20]},
            )
        return _item(
            code="API_HEALTH",
            name="API Health",
            status="PASS",
            message="API Health 정상",
            detail={"component_keys": list(components.keys())[:20]},
        )
    except Exception as exc:  # noqa: BLE001
        return _item(
            code="API_HEALTH",
            name="API Health",
            status="FAIL",
            message=f"API Health 점검 실패: {exc.__class__.__name__}",
            remediation="Operation health 빌더를 확인하세요.",
            detail={"error_type": exc.__class__.__name__},
        )


def _check_sync_freshness(session: Session) -> dict[str, Any]:
    """오래된 잔고/체결 동기화 — WARN (비차단)."""
    try:
        from stock_platform.trading.account_models import UserBrokerAccount

        rows = list(
            session.scalars(
                select(UserBrokerAccount)
                .where(
                    UserBrokerAccount.is_active.is_(True),
                    UserBrokerAccount.deleted_at.is_(None),
                )
                .limit(100)
            )
        )
        now = _utcnow()
        stale = 0
        for row in rows:
            synced = getattr(row, "last_synced_at", None)
            if synced is None:
                stale += 1
                continue
            if synced.tzinfo is None:
                synced = synced.replace(tzinfo=timezone.utc)
            if (now - synced).total_seconds() > 24 * 3600:
                stale += 1
        detail = {"active_uba": len(rows), "stale_or_never_synced": stale}
        if stale > 0:
            return _item(
                code="SYNC_FRESHNESS",
                name="Balance/Fill Sync",
                status="WARN",
                message=f"오래된/미동기화 계좌 {stale}건",
                remediation="잔고·체결 동기화를 새로고침하세요 (LIVE ON 비차단).",
                detail=detail,
            )
        return _item(
            code="SYNC_FRESHNESS",
            name="Balance/Fill Sync",
            status="PASS",
            message="동기화 시각 정상",
            detail=detail,
        )
    except Exception as exc:  # noqa: BLE001
        return _item(
            code="SYNC_FRESHNESS",
            name="Balance/Fill Sync",
            status="WARN",
            message=f"동기화 점검 실패: {exc.__class__.__name__}",
            remediation="비필수 동기화 모니터링을 확인하세요.",
            detail={"error_type": exc.__class__.__name__},
        )


class RuntimePreflightService:
    """LIVE ON / Scheduler RUN 전 운영 조건 자동 점검 (조회 전용)."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def run(self, *, mode: PreflightMode = "LIVE_ON") -> dict[str, Any]:
        checked_at = _utcnow()
        expires_at = checked_at + timedelta(seconds=PREFLIGHT_TTL_SECONDS)

        checks: list[dict[str, Any]] = [
            _check_broker(self._session),
            _check_credential(self._session),
            _check_connection(self._session),
            _check_recovery(self._session),
            _check_conflict(self._session),
            _check_runtime(),
            _check_scheduler(),
            _check_scheduler_live_invariant(self._session),
            _check_live_arm_flags(self._session),
            _check_risk(self._session),
            _check_strategy(mode=mode),
            _check_telegram(),
            _check_database(self._session),
            _check_redis(),
            _check_api_health(),
            _check_sync_freshness(self._session),
        ]
        # checked_at 통일
        for row in checks:
            row["checked_at"] = checked_at.isoformat()

        blockers = [
            {
                "code": c["code"],
                "message": c["message"],
                "status": c["status"],
                "remediation": c.get("remediation"),
            }
            for c in checks
            if c["status"] == "FAIL"
        ]
        warnings = [
            {
                "code": c["code"],
                "message": c["message"],
                "status": c["status"],
                "remediation": c.get("remediation"),
            }
            for c in checks
            if c["status"] == "WARN"
        ]

        fail_count = sum(1 for c in checks if c["status"] == "FAIL")
        if fail_count > 0:
            overall_status = "BLOCKED"
            estimated_ready: str | None = None
            live_on_allowed = False
        else:
            overall_status = "READY_FOR_LIVE"
            estimated_ready = "NOW"
            live_on_allowed = mode == "LIVE_ON"

        payload = {
            "mode": mode,
            "overall": overall_status,
            "overall_status": overall_status,
            "estimated_ready": estimated_ready,
            "live_on_allowed": live_on_allowed and overall_status == "READY_FOR_LIVE",
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
                "pass": sum(1 for c in checks if c["status"] == "PASS"),
                "warn": sum(1 for c in checks if c["status"] == "WARN"),
                "fail": fail_count,
                "not_applicable": sum(
                    1 for c in checks if c["status"] == "NOT_APPLICABLE"
                ),
                "total": len(checks),
            },
        }
        return sanitize_preflight_payload(payload)

    def run_for_uba(
        self,
        *,
        user_broker_account_id: int,
        mode: PreflightMode = "LIVE_ON",
        owner_user_id: int | None = None,
    ) -> dict[str, Any]:
        """특정 UPBIT UBA 만 검사 — 타 계좌(Kiwoom/Paper) 상태는 영향 없음."""
        from stock_platform.broker.credential_vault_service import (
            BrokerCredentialVaultService,
        )
        from stock_platform.broker.recovery_account_state import (
            BrokerRecoveryAccountStateEntity,
        )
        from stock_platform.broker.recovery_conflict_constants import (
            ACTIVE_REVIEW_STATUSES,
        )
        from stock_platform.broker.recovery_conflict_entities import (
            BrokerRecoveryConflictEntity,
        )
        from stock_platform.risk_engine.kill_switch_service import (
            KillSwitchService,
        )
        from stock_platform.risk_engine.user_risk_entities import (
            UserBrokerAccountRiskSetting,
        )
        from stock_platform.trading.account_models import UserBrokerAccount

        checked_at = _utcnow()
        expires_at = checked_at + timedelta(seconds=PREFLIGHT_TTL_SECONDS)
        uba_id = int(user_broker_account_id)
        uba = self._session.get(UserBrokerAccount, uba_id)

        def _fail_closed(code: str, message: str) -> dict[str, Any]:
            item = _item(
                code=code,
                name=code.replace("_", " ").title(),
                status="FAIL",
                message=message,
                remediation="올바른 UPBIT UBA 를 지정하세요.",
                checked_at=checked_at,
            )
            return sanitize_preflight_payload(
                {
                    "mode": mode,
                    "scope": "UBA",
                    "user_broker_account_id": uba_id,
                    "broker_code": None,
                    "account_kind": None,
                    "execution_mode": None,
                    "overall": "BLOCKED",
                    "overall_status": "BLOCKED",
                    "estimated_ready": None,
                    "live_on_allowed": False,
                    "manual_order_allowed": False,
                    "freshness": {
                        "ttl_seconds": PREFLIGHT_TTL_SECONDS,
                        "checked_at": checked_at.isoformat(),
                        "expires_at": expires_at.isoformat(),
                        "status": "FRESH",
                    },
                    "checked_at": checked_at.isoformat(),
                    "expires_at": expires_at.isoformat(),
                    "checks": [item],
                    "warnings": [],
                    "blockers": [
                        {
                            "code": item["code"],
                            "message": item["message"],
                            "status": "FAIL",
                            "remediation": item.get("remediation"),
                        }
                    ],
                    "summary": {
                        "pass": 0,
                        "warn": 0,
                        "fail": 1,
                        "not_applicable": 0,
                        "total": 1,
                    },
                }
            )

        if uba is None or getattr(uba, "deleted_at", None) is not None:
            return _fail_closed("UBA", "UBA not found")
        if owner_user_id is not None and int(uba.user_id) != int(owner_user_id):
            return _fail_closed("OWNERSHIP", "UBA ownership mismatch")
        broker = str(uba.broker_code or "").upper()
        if broker != "UPBIT":
            return _fail_closed("BROKER", f"broker_code={broker} is not UPBIT")

        settings = get_settings()
        account_kind = "LIVE"
        shadow_on = bool(getattr(settings, "upbit_shadow_mode", False)) or bool(
            getattr(settings, "shadow_mode_enabled", False)
        )
        dry_run_on = bool(getattr(settings, "live_order_dry_run_enabled", False))
        if shadow_on:
            execution_mode = "SHADOW"
        elif dry_run_on:
            execution_mode = "DRY_RUN"
        else:
            execution_mode = "LIVE"

        checks: list[dict[str, Any]] = []

        # OWNER / ACCOUNT
        checks.append(
            _item(
                code="OWNER",
                name="Ownership",
                status="PASS",
                message=f"owner_user_id={int(uba.user_id)}",
                detail={"user_id": int(uba.user_id)},
                checked_at=checked_at,
            )
        )
        checks.append(
            _item(
                code="ACCOUNT",
                name="Account",
                status="PASS",
                message=f"UPBIT · kind={account_kind} · mode={execution_mode}",
                detail={
                    "broker_code": broker,
                    "account_kind": account_kind,
                    "execution_mode": execution_mode,
                    "is_active": bool(uba.is_active),
                    "masked_account_number": uba.masked_account_number,
                },
                checked_at=checked_at,
            )
        )

        # CREDENTIAL
        try:
            st = BrokerCredentialVaultService(self._session).status(uba_id)
            verified = (
                str(getattr(st, "verification_status", "") or "").upper()
                == "VERIFIED"
            )
            checks.append(
                _item(
                    code="CREDENTIAL",
                    name="Credential",
                    status="PASS" if verified else "FAIL",
                    message=(
                        "Credential VERIFIED"
                        if verified
                        else "Credential 미검증"
                    ),
                    remediation=(
                        None
                        if verified
                        else "Credential 등록·검증을 완료하세요."
                    ),
                    detail={"verification_status": getattr(st, "verification_status", None)},
                    checked_at=checked_at,
                )
            )
        except Exception as exc:  # noqa: BLE001
            checks.append(
                _item(
                    code="CREDENTIAL",
                    name="Credential",
                    status="FAIL",
                    message=f"Credential 점검 실패: {exc.__class__.__name__}",
                    remediation="Credential vault 를 확인하세요.",
                    checked_at=checked_at,
                )
            )

        # CONNECTION
        conn = str(uba.connection_status or "").upper()
        conn_ok = conn in {"CONNECTED", "VERIFIED"}
        checks.append(
            _item(
                code="CONNECTION",
                name="Connection",
                status="PASS" if conn_ok else "FAIL",
                message=f"connection_status={conn or 'UNKNOWN'}",
                remediation=(
                    None if conn_ok else "connection_status=CONNECTED 로 맞추세요."
                ),
                detail={"connection_status": conn},
                checked_at=checked_at,
            )
        )

        # RECOVERY / trading_paused
        rec = self._session.scalar(
            select(BrokerRecoveryAccountStateEntity).where(
                BrokerRecoveryAccountStateEntity.user_broker_account_id
                == uba_id
            )
        )
        trading_paused = bool(getattr(rec, "trading_paused", False)) if rec else False
        recovery_status = (
            str(getattr(rec, "recovery_status", "") or "").upper() if rec else ""
        )
        recovery_ok = (not trading_paused) and (
            recovery_status in {"", "SUCCESS", "READY", "IDLE"}
        )
        checks.append(
            _item(
                code="RECOVERY",
                name="Recovery",
                status="PASS" if recovery_ok else "FAIL",
                message=(
                    "Recovery 정상"
                    if recovery_ok
                    else f"trading_paused={trading_paused} status={recovery_status or 'N/A'}"
                ),
                remediation=(
                    None if recovery_ok else "Resume Trading / Recovery 해소 후 재검사"
                ),
                detail={
                    "trading_paused": trading_paused,
                    "recovery_status": recovery_status or None,
                },
                checked_at=checked_at,
            )
        )

        # CONFLICT (해당 UBA만)
        active_conflicts = int(
            self._session.scalar(
                select(func.count())
                .select_from(BrokerRecoveryConflictEntity)
                .where(
                    BrokerRecoveryConflictEntity.user_broker_account_id
                    == uba_id,
                    BrokerRecoveryConflictEntity.review_status.in_(
                        list(ACTIVE_REVIEW_STATUSES)
                    ),
                )
            )
            or 0
        )
        checks.append(
            _item(
                code="CONFLICT",
                name="Conflict",
                status="PASS" if active_conflicts == 0 else "FAIL",
                message=f"활성 Conflict {active_conflicts}건",
                remediation=(
                    None if active_conflicts == 0 else "활성 Conflict 해소 후 재검사"
                ),
                detail={"active_blocking_conflicts": active_conflicts},
                checked_at=checked_at,
            )
        )

        # RISK / Kill / account_paused
        kill_active = bool(KillSwitchService(self._session).is_active())
        risk_row = self._session.scalar(
            select(UserBrokerAccountRiskSetting).where(
                UserBrokerAccountRiskSetting.user_broker_account_id == uba_id
            )
        )
        account_paused = bool(getattr(risk_row, "account_paused", False)) if risk_row else False
        risk_present = risk_row is not None
        if kill_active:
            risk_status, risk_msg = "FAIL", "Kill Switch ON"
        elif not risk_present:
            risk_status, risk_msg = "FAIL", "Risk 설정 없음"
        elif account_paused:
            risk_status, risk_msg = "FAIL", "account_paused=true"
        else:
            risk_status, risk_msg = "PASS", "Kill OFF · Risk 설정 정상"
        checks.append(
            _item(
                code="RISK",
                name="Risk",
                status=risk_status,
                message=risk_msg,
                remediation=(
                    None
                    if risk_status == "PASS"
                    else "Kill/Pause/Risk 설정을 정상화하세요."
                ),
                detail={
                    "kill_switch_active": kill_active,
                    "account_paused": account_paused,
                    "risk_setting_present": risk_present,
                },
                checked_at=checked_at,
            )
        )

        # LIVE / ARM / Scheduler (대기 상태 WARN)
        live_on = bool(uba.live_order_enabled)
        arm_on = bool(uba.live_armed)
        if not live_on and not arm_on:
            checks.append(
                _item(
                    code="LIVE_ARM_STATE",
                    name="LIVE/ARM",
                    status="WARN",
                    message="LIVE OFF · ARM OFF (정상 대기)",
                    remediation="별도 승인 후 LIVE ON → ARM ON",
                    detail={"live_on": live_on, "arm_on": arm_on},
                    checked_at=checked_at,
                )
            )
        else:
            checks.append(
                _item(
                    code="LIVE_ARM_STATE",
                    name="LIVE/ARM",
                    status="PASS",
                    message=f"LIVE={'ON' if live_on else 'OFF'} · ARM={'ON' if arm_on else 'OFF'}",
                    detail={
                        "live_on": live_on,
                        "arm_on": arm_on,
                        "arm_expires_at": (
                            uba.arm_expires_at.isoformat()
                            if uba.arm_expires_at
                            else None
                        ),
                    },
                    checked_at=checked_at,
                )
            )

        try:
            from stock_platform.trading.upbit_scheduler_readiness import (
                collect_scheduler_readiness,
            )

            snap = collect_scheduler_readiness()
            desired = str(snap.trading_scheduler_desired_state or "").upper()
            actual = str(snap.trading_scheduler_actual_state or "").upper()
            paused = desired in {"PAUSE", "PAUSED", ""} and actual in {
                "PAUSE",
                "PAUSED",
                "STOPPED",
                "",
            }
            checks.append(
                _item(
                    code="SCHEDULER",
                    name="Scheduler",
                    status="WARN" if paused else "WARN",
                    message=(
                        "Scheduler PAUSE (수동 주문 안전 대기)"
                        if paused
                        else f"Scheduler desired={desired} actual={actual}"
                    ),
                    detail={"desired_state": desired, "actual_state": actual},
                    checked_at=checked_at,
                )
            )
            # UBA 단위: Scheduler RUN + 이 UBA LIVE OFF → FAIL
            running = actual in {"RUN", "RUNNING"} or desired in {
                "RUN",
                "RUNNING",
            }
            uba_live = bool(uba.live_order_enabled)
            if running and not uba_live:
                checks.append(
                    _item(
                        code="SCHEDULER_LIVE_INVARIANT",
                        name="Scheduler↔LIVE",
                        status="FAIL",
                        message="Scheduler RUN + 이 UBA LIVE OFF (불변식 위반)",
                        remediation=(
                            "Fail Closed: Scheduler PAUSE 후 "
                            "LIVE ON → ARM ON → Scheduler RUN"
                        ),
                        detail={
                            "desired_state": desired,
                            "actual_state": actual,
                            "uba_live_order_enabled": uba_live,
                        },
                        checked_at=checked_at,
                    )
                )
        except Exception as exc:  # noqa: BLE001
            checks.append(
                _item(
                    code="SCHEDULER",
                    name="Scheduler",
                    status="WARN",
                    message=f"Scheduler 점검 실패: {exc.__class__.__name__}",
                    checked_at=checked_at,
                )
            )

        # Strategy / Runtime scope (UBA 연결 존재 여부 — 없으면 WARN for LIVE_ON)
        strategy_linked = False
        try:
            from stock_platform.strategy_deployment.definition_entities import (
                AccountStrategyLinkEntity,
            )

            link_count = int(
                self._session.scalar(
                    select(func.count())
                    .select_from(AccountStrategyLinkEntity)
                    .where(
                        AccountStrategyLinkEntity.user_broker_account_id
                        == uba_id
                    )
                )
                or 0
            )
            strategy_linked = link_count > 0
        except Exception:  # noqa: BLE001
            link_count = 0
            strategy_linked = False
        if mode == "SCHEDULER_RUN" and not strategy_linked:
            strat_status, strat_msg = "FAIL", "Scheduler RUN 전 Strategy 연결 0건"
        elif not strategy_linked:
            strat_status, strat_msg = "WARN", "Strategy 연결 0건 (LIVE ON 전 대기)"
        else:
            strat_status, strat_msg = "PASS", f"Strategy 연결 {link_count}건"
        checks.append(
            _item(
                code="STRATEGY",
                name="Strategy",
                status=strat_status,
                message=strat_msg,
                detail={"link_count": link_count},
                checked_at=checked_at,
            )
        )

        # Runtime scope presence (조회 실패는 WARN)
        try:
            from stock_platform.realtime.runtime import realtime_strategy_runner

            st = realtime_strategy_runner.status() or {}
            checks.append(
                _item(
                    code="RUNTIME_SCOPE",
                    name="Runtime Scope",
                    status="WARN" if int(st.get("active_scopes") or 0) == 0 else "PASS",
                    message=f"active_scopes={int(st.get('active_scopes') or 0)}",
                    detail={"active_scopes": int(st.get("active_scopes") or 0)},
                    checked_at=checked_at,
                )
            )
        except Exception as exc:  # noqa: BLE001
            checks.append(
                _item(
                    code="RUNTIME_SCOPE",
                    name="Runtime Scope",
                    status="WARN",
                    message=f"Runtime 조회 실패: {exc.__class__.__name__}",
                    checked_at=checked_at,
                )
            )

        # Upbit WS (비필수 → WARN)
        try:
            from stock_platform.broker.upbit.ws_status import (  # type: ignore[attr-defined]
                get_upbit_ws_status,
            )

            ws = get_upbit_ws_status() or {}
            ws_ok = bool(ws.get("connected") or ws.get("ok"))
            checks.append(
                _item(
                    code="UPBIT_WS",
                    name="Upbit WS",
                    status="PASS" if ws_ok else "WARN",
                    message="WS 연결 정상" if ws_ok else "WS 미연결/저하",
                    detail={"connected": ws_ok},
                    checked_at=checked_at,
                )
            )
        except Exception:  # noqa: BLE001
            checks.append(
                _item(
                    code="UPBIT_WS",
                    name="Upbit WS",
                    status="WARN",
                    message="WS 상태 조회 불가 (비필수)",
                    checked_at=checked_at,
                )
            )

        # Sync freshness
        synced = getattr(uba, "last_synced_at", None)
        sync_stale = True
        if synced is not None:
            if synced.tzinfo is None:
                synced = synced.replace(tzinfo=timezone.utc)
            sync_stale = (checked_at - synced).total_seconds() > 24 * 3600
        checks.append(
            _item(
                code="SYNC_FRESHNESS",
                name="Balance Sync",
                status="WARN" if sync_stale else "PASS",
                message=(
                    "잔고 동기화 오래됨/없음"
                    if sync_stale
                    else "잔고 동기화 최신"
                ),
                detail={
                    "last_synced_at": synced.isoformat() if synced else None
                },
                checked_at=checked_at,
            )
        )

        # 주문 가능 정보 (최소 주문 규칙 — Broker 주문 API 미호출)
        from stock_platform.broker.upbit.rules import UPBIT_MIN_NOTIONAL_KRW

        checks.append(
            _item(
                code="ORDERABILITY",
                name="Orderability",
                status="PASS",
                message=f"최소 주문 {UPBIT_MIN_NOTIONAL_KRW} KRW 규칙 조회 가능",
                detail={
                    "min_notional_krw": str(UPBIT_MIN_NOTIONAL_KRW),
                    "order_api_called": False,
                },
                checked_at=checked_at,
            )
        )

        # DATABASE
        checks.append(_check_database(self._session))
        for row in checks:
            row["checked_at"] = checked_at.isoformat()

        fail_count = sum(1 for c in checks if c["status"] == "FAIL")
        overall = "BLOCKED" if fail_count else "READY_FOR_LIVE"
        live_on_allowed = overall == "READY_FOR_LIVE"
        # 수동 주문: READY + LIVE ON + ARM ON + Shadow/DryRun OFF
        manual_order_allowed = (
            live_on_allowed
            and live_on
            and arm_on
            and not shadow_on
            and not dry_run_on
            and not kill_active
            and not trading_paused
            and not account_paused
        )

        warnings = [
            {
                "code": c["code"],
                "message": c["message"],
                "status": c["status"],
                "remediation": c.get("remediation"),
            }
            for c in checks
            if c["status"] == "WARN"
        ]
        blockers = [
            {
                "code": c["code"],
                "message": c["message"],
                "status": c["status"],
                "remediation": c.get("remediation"),
            }
            for c in checks
            if c["status"] == "FAIL"
        ]
        return sanitize_preflight_payload(
            {
                "mode": mode,
                "scope": "UBA",
                "user_broker_account_id": uba_id,
                "broker_code": broker,
                "account_kind": account_kind,
                "execution_mode": execution_mode,
                "overall": overall,
                "overall_status": overall,
                "estimated_ready": "NOW" if overall == "READY_FOR_LIVE" else None,
                "live_on_allowed": live_on_allowed,
                "manual_order_allowed": manual_order_allowed,
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
                    "pass": sum(1 for c in checks if c["status"] == "PASS"),
                    "warn": sum(1 for c in checks if c["status"] == "WARN"),
                    "fail": fail_count,
                    "not_applicable": sum(
                        1 for c in checks if c["status"] == "NOT_APPLICABLE"
                    ),
                    "total": len(checks),
                },
            }
        )

    def assert_ready_for_live_on(
        self, user_broker_account_id: int
    ) -> dict[str, Any]:
        """LIVE ON 서버 gate — 선택 UBA 단위 Pre-flight 재계산."""
        from stock_platform.trading.live_order_approval_service import (
            LiveOrderApprovalError,
        )

        report = self.run_for_uba(
            user_broker_account_id=int(user_broker_account_id),
            mode="LIVE_ON",
        )
        if report.get("overall_status") != "READY_FOR_LIVE":
            blocker_codes = [
                str(b.get("code") or "")
                for b in (report.get("blockers") or [])
            ]
            raise LiveOrderApprovalError(
                "preflight_blocked",
                "UBA Pre-flight is BLOCKED: "
                + (",".join(blocker_codes) if blocker_codes else "FAIL"),
            )
        return report


def evaluate_preflight_freshness(
    checked_at_iso: str | None,
    *,
    now: datetime | None = None,
    ttl_seconds: int = PREFLIGHT_TTL_SECONDS,
) -> dict[str, Any]:
    """프론트/서버 공통 최신성 판정."""
    current = now or _utcnow()
    if not checked_at_iso:
        return {
            "status": "STALE",
            "fresh": False,
            "age_seconds": None,
            "ttl_seconds": ttl_seconds,
            "reason": "missing_checked_at",
        }
    try:
        checked = datetime.fromisoformat(
            str(checked_at_iso).replace("Z", "+00:00")
        )
        if checked.tzinfo is None:
            checked = checked.replace(tzinfo=timezone.utc)
    except ValueError:
        return {
            "status": "STALE",
            "fresh": False,
            "age_seconds": None,
            "ttl_seconds": ttl_seconds,
            "reason": "invalid_checked_at",
        }
    age = (current - checked).total_seconds()
    fresh = age <= float(ttl_seconds)
    return {
        "status": "FRESH" if fresh else "STALE",
        "fresh": fresh,
        "age_seconds": round(age, 3),
        "ttl_seconds": ttl_seconds,
        "checked_at": checked.isoformat(),
        "expires_at": (checked + timedelta(seconds=ttl_seconds)).isoformat(),
    }
