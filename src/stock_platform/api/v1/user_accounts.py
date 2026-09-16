"""회원 전용 계좌 CRUD API — STEP65."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from stock_platform.auth.account_ownership import assert_account_access
from stock_platform.auth.deps import (
    AuthenticatedUser,
    require_permission,
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
from stock_platform.database.session import get_db_session
from stock_platform.trading.user_account_service import (
    UserAccountError,
    UserAccountService,
)


router = APIRouter(
    prefix="/api/v1/user/accounts",
    tags=["User Accounts"],
)


class CreateUserAccountRequest(BaseModel):
    account_type: str = Field(
        min_length=1,
        max_length=20,
        description="PAPER | KIWOOM | UPBIT",
    )
    account_name: str | None = Field(
        default=None,
        max_length=100,
        description="별칭 / Paper 계좌명",
    )
    initial_cash: Decimal | None = Field(
        default=None,
        gt=0,
        description="PAPER 전용 초기 현금",
    )
    currency_code: str = Field(default="KRW", max_length=10)
    # Broker 연결 시에만 수신 — 응답·DB 원문 저장 금지
    account_number: str | None = Field(
        default=None,
        max_length=64,
        description="Broker 계좌번호 (해시·마스킹만 저장)",
    )
    is_default: bool = False


class UpdateUserAccountRequest(BaseModel):
    account_name: str | None = Field(default=None, max_length=100)
    is_active: bool | None = None
    account_type: str | None = Field(
        default=None,
        max_length=20,
        description="ID 충돌 시 PAPER/KIWOOM/UPBIT 구분",
    )


def _service(session: Session) -> UserAccountService:
    return UserAccountService(session)


def _enrich_recovery_status(
    session: Session, item: dict[str, Any]
) -> dict[str, Any]:
    """USER용 Recovery 요약 — Conflict 상세·UUID 전체는 노출하지 않음."""

    out = dict(item)
    out.setdefault("trading_paused", False)
    out.setdefault("recovery_review_required", False)
    out.setdefault("recovery_status", None)
    out.setdefault("recovery_user_message", None)
    out.setdefault("pause_reasons", [])
    out.setdefault("live_trading_ready", False)
    out.setdefault("trading_scheduler_desired", None)
    out.setdefault("trading_scheduler_actual", None)
    out.setdefault("trading_scheduler_state", None)

    account_type = str(out.get("account_type") or "").upper()
    if account_type not in {"UPBIT", "KIWOOM"}:
        return out

    uba_id = int(out["account_id"])
    broker = account_type

    # Credential VERIFIED ↔ connection_status 불일치 치유
    try:
        from stock_platform.broker.credential_vault_service import (
            BrokerCredentialVaultService,
        )

        healed = BrokerCredentialVaultService(
            session
        ).sync_uba_connection_status(uba_id)
        if healed == "CONNECTED":
            out["connection_status"] = "CONNECTED"
            session.commit()
    except Exception:  # noqa: BLE001 — 목록 조회는 치유 실패해도 계속
        session.rollback()

    state = session.scalar(
        select(BrokerRecoveryAccountStateEntity)
        .where(
            BrokerRecoveryAccountStateEntity.user_broker_account_id
            == uba_id,
            BrokerRecoveryAccountStateEntity.broker_code == broker,
        )
        .limit(1)
    )
    active_conflicts = int(
        session.scalar(
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
    paused = bool(state.trading_paused) if state is not None else False
    recovery_status = (
        str(state.recovery_status or "").upper() if state else ""
    )
    review = active_conflicts > 0 or recovery_status == "MANUAL_REVIEW"
    out["trading_paused"] = paused
    out["recovery_review_required"] = review
    out["recovery_status"] = (
        state.recovery_status if state is not None else None
    )

    # 사용자용 친절한 원인 (내부 예외·UUID·코드 원문 비노출)
    reasons: list[str] = []
    conn = str(out.get("connection_status") or "").upper()
    if conn in {"CREDENTIAL_PENDING", "PENDING"}:
        reasons.append("Credential 등록 필요")
    elif conn in {"CREDENTIAL_FAILED", "DISCONNECTED"}:
        reasons.append("Credential 확인 필요")

    if recovery_status == "RUNNING":
        reasons.append("Recovery 진행 중")
    elif recovery_status == "MANUAL_REVIEW":
        reasons.append("Recovery 검토 필요")
    elif recovery_status == "FAILED":
        reasons.append("Recovery 실패 · 관리자 확인 필요")

    if active_conflicts > 0:
        reasons.append("Conflict 발생")

    # Conflict로 auto_retry가 꺼진 경우는 Conflict 메시지로 충분
    if (
        state is not None
        and not bool(state.auto_retry_enabled)
        and active_conflicts == 0
        and recovery_status not in {"MANUAL_REVIEW", "RUNNING"}
    ):
        reasons.append("Scheduler Pause")

    # Risk account_paused
    try:
        from stock_platform.risk_engine.user_risk_service import (
            UserRiskSettingService,
        )

        risk_snap = UserRiskSettingService(session).snapshot_account(
            uba_id
        )
        if isinstance(risk_snap, dict) and risk_snap.get(
            "account_paused"
        ):
            reasons.append("Risk 차단")
    except Exception:  # noqa: BLE001
        pass

    uba_row = None
    try:
        from stock_platform.trading.account_models import UserBrokerAccount

        uba_row = session.get(UserBrokerAccount, uba_id)
    except Exception:  # noqa: BLE001
        uba_row = None
    if uba_row is not None:
        out["live_order_enabled"] = bool(
            getattr(uba_row, "live_order_enabled", False)
        )
        out["live_armed"] = bool(getattr(uba_row, "live_armed", False))
        arm_exp = getattr(uba_row, "arm_expires_at", None)
        out["arm_expires_at"] = (
            arm_exp.isoformat() if arm_exp is not None else None
        )
        if not bool(getattr(uba_row, "is_active", True)):
            reasons.append("관리자 일시중지")
    elif paused and not reasons:
        # 구체 원인 없이 trading_paused만 켜진 경우
        reasons.append("관리자 일시중지")

    # 중복 제거·순서 유지
    deduped: list[str] = []
    for reason in reasons:
        if reason not in deduped:
            deduped.append(reason)
    out["pause_reasons"] = deduped

    if review or paused or deduped:
        if (
            recovery_status == "MANUAL_REVIEW"
            or active_conflicts > 0
        ) and conn in {"CONNECTED", "VERIFIED"}:
            out["pause_reasons"] = [
                "관리자 검토 중",
                "거래 기능은 아직 일시중지 상태",
            ]
            if "API 인증정보 정상" not in out["pause_reasons"]:
                out["pause_reasons"].insert(0, "API 인증정보 정상")
            out["recovery_user_message"] = (
                "과거 외부 주문 이력과 플랫폼 기록을 확인하고 있습니다. "
                "현재 미체결 주문은 없지만 안전한 거래 재개를 위해 "
                "관리자 검토가 필요합니다."
            )
        elif deduped:
            out["recovery_user_message"] = (
                " · ".join(deduped)
                + ". 자세한 조치는 관리자에게 문의해 주세요."
            )
        else:
            out["recovery_user_message"] = (
                "관리자 확인이 필요합니다. 해당 계좌 거래가 일시중지되었을 수 "
                "있습니다."
            )
    elif (
        not paused
        and not review
        and recovery_status in {"SUCCESS", "READY", "IDLE", ""}
        and conn in {"CONNECTED", "VERIFIED"}
    ):
        # Resume 완료 후 Runtime 상태 안내 (읽기 전용)
        live_on = bool(out.get("live_order_enabled"))
        arm_on = bool(out.get("live_armed"))
        sched_state = str(out.get("trading_scheduler_state") or "PAUSE").upper()
        # scheduler enrichment는 아래에서 채우므로 일단 기본 PAUSE
        out["live_trading_ready"] = False
        if not live_on:
            out["pause_reasons"] = ["실거래 기능 비활성"]
            out["recovery_user_message"] = (
                "실거래 기능이 비활성화되어 있습니다."
            )
        elif live_on and not arm_on:
            out["pause_reasons"] = [
                "LIVE 허용",
                "주문 준비(ARM) 비활성",
            ]
            out["recovery_user_message"] = (
                "실거래 연결은 허용되었지만 주문 준비는 비활성화되어 있습니다."
            )
        else:
            # LIVE+ARM — Scheduler 메시지는 아래에서 보정
            out["pause_reasons"] = ["자동매매 준비"]
            out["recovery_user_message"] = (
                "자동매매 준비 완료, 스케줄러는 정지 상태입니다."
            )
            out["live_trading_ready"] = False

    # Trading Scheduler 상태 (읽기 전용 — 사용자 변경 불가)
    try:
        from stock_platform.trading.upbit_scheduler_readiness import (
            collect_scheduler_readiness,
        )

        sched = collect_scheduler_readiness()
        out["trading_scheduler_desired"] = sched.trading_scheduler_desired_state
        out["trading_scheduler_actual"] = sched.trading_scheduler_actual_state
        desired = str(sched.trading_scheduler_desired_state or "").upper()
        actual = str(sched.trading_scheduler_actual_state or "").upper()
        if desired in {"RUN", "RUNNING"} or actual in {"RUN", "RUNNING"}:
            out["trading_scheduler_state"] = "RUN"
        else:
            out["trading_scheduler_state"] = "PAUSE"
    except Exception:  # noqa: BLE001
        out["trading_scheduler_state"] = out.get("trading_scheduler_state") or "PAUSE"

    # LIVE+ARM 조합 메시지를 Scheduler 반영해 최종 확정
    if (
        not paused
        and not review
        and bool(out.get("live_order_enabled"))
        and bool(out.get("live_armed"))
        and conn in {"CONNECTED", "VERIFIED"}
    ):
        if out.get("trading_scheduler_state") == "RUN":
            out["live_trading_ready"] = True
            out["pause_reasons"] = ["자동매매 실행 중"]
            out["recovery_user_message"] = "자동매매가 실행 중입니다."
        else:
            out["live_trading_ready"] = False
            out["pause_reasons"] = [
                "자동매매 준비 완료",
                "스케줄러 정지",
            ]
            out["recovery_user_message"] = (
                "자동매매 준비 완료, 스케줄러는 정지 상태입니다."
            )

    # STEP 8-5-8 — Upbit Rate Limit 요약 (내부 Endpoint 비노출)
    out.setdefault("upbit_api_status", None)
    out.setdefault("upbit_rate_limit_message", None)
    out.setdefault("upbit_retry_scheduled_at", None)
    if broker == "UPBIT":
        try:
            from stock_platform.broker.upbit.rate_limit_coordinator import (
                get_upbit_rate_limit_coordinator,
            )

            rows = get_upbit_rate_limit_coordinator().get_uba_states(
                uba_id
            )
            from datetime import datetime, timezone

            now = datetime.now(timezone.utc)
            blocked = False
            cooldown = False
            retry_at = None
            for row in rows:
                st = str(row.get("status") or "").upper()
                if st == "BLOCKED_418":
                    blocked = True
                elif st in {"COOLDOWN", "DEFERRED"}:
                    cooldown = True
                for key in ("cooldown_until", "blocked_until"):
                    raw = row.get(key)
                    if not raw:
                        continue
                    try:
                        dt = datetime.fromisoformat(
                            str(raw).replace("Z", "+00:00")
                        )
                    except ValueError:
                        continue
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    if dt > now and (
                        retry_at is None or dt < retry_at
                    ):
                        retry_at = dt
            if blocked or (
                state is not None
                and str(state.next_retry_reason or "")
                == "BLOCKED_UPBIT_418"
            ):
                out["upbit_api_status"] = "ADMIN_REVIEW_REQUIRED"
                out["upbit_rate_limit_message"] = (
                    "관리자 확인이 필요합니다."
                )
            elif cooldown or (
                state is not None
                and str(state.next_retry_reason or "")
                == "DEFERRED_RATE_LIMIT"
            ):
                out["upbit_api_status"] = "RATE_LIMITED"
                out["upbit_rate_limit_message"] = (
                    "일시적 요청 제한 중 · 동기화가 지연될 수 있습니다."
                )
                if retry_at is None and state is not None:
                    retry_at = state.next_retry_at
            else:
                out["upbit_api_status"] = "OK"
                out["upbit_rate_limit_message"] = "Upbit API 정상"
            out["upbit_retry_scheduled_at"] = (
                retry_at.isoformat() if retry_at else None
            )
        except Exception:  # noqa: BLE001
            out["upbit_api_status"] = "UNKNOWN"

    return out


def _http_error(exc: UserAccountError) -> HTTPException:
    message = str(exc)
    code = (
        status.HTTP_404_NOT_FOUND
        if "찾을 수 없" in message
        else status.HTTP_400_BAD_REQUEST
    )
    return HTTPException(status_code=code, detail=message)


@router.get("")
def list_user_accounts(
    default: bool = Query(
        False,
        description="기본 계좌만 조회",
    ),
    include_inactive: bool = Query(False),
    user: AuthenticatedUser = Depends(
        require_permission("trading:read")
    ),
    session: Session = Depends(get_db_session),
):
    """로그인 사용자 본인 계좌만 반환. user_id 는 JWT 에서만 결정."""

    rows = _service(session).list_accounts(
        user.user_id,
        default_only=default,
        include_inactive=include_inactive,
    )
    items = [
        _enrich_recovery_status(session, row.as_dict()) for row in rows
    ]
    return {
        "items": items,
        "total": len(items),
    }


@router.post("")
def create_user_account(
    request: CreateUserAccountRequest,
    user: AuthenticatedUser = Depends(
        require_permission("trading:write")
    ),
    session: Session = Depends(get_db_session),
):
    try:
        view = _service(session).create_account(
            user.user_id,
            account_type=request.account_type,
            account_name=request.account_name,
            initial_cash=request.initial_cash,
            currency_code=request.currency_code,
            account_number=request.account_number,
            is_default=request.is_default,
        )
    except UserAccountError as exc:
        raise _http_error(exc) from exc
    return view.as_dict()


@router.get("/accounts/{account_id}/runtimes")
def list_account_runtimes(
    account_id: int,
    account_type: str | None = Query(None),
    user: AuthenticatedUser = Depends(
        require_permission("trading:read")
    ),
    session: Session = Depends(get_db_session),
):
    """본인 계좌에 연결된 Runtime만 반환."""

    assert_account_access(
        user, account_id, session, account_type=account_type
    )
    from stock_platform.strategy_deployment.runtime_manager import (
        dynamic_strategy_runtime_manager,
    )

    kind = (account_type or "").upper()
    if kind == "PAPER":
        entries = dynamic_strategy_runtime_manager.list_entries(
            user_id=int(user.user_id),
            paper_account_id=int(account_id),
        )
    else:
        entries = dynamic_strategy_runtime_manager.list_entries(
            user_id=int(user.user_id),
            user_broker_account_id=int(account_id),
        )
    return {
        "items": [e.as_dict() for e in entries],
        "total": len(entries),
        "account_id": account_id,
    }


@router.get("/{account_id}")
def get_user_account(
    account_id: int,
    account_type: str | None = Query(None),
    user: AuthenticatedUser = Depends(
        require_permission("trading:read")
    ),
    session: Session = Depends(get_db_session),
):
    assert_account_access(
        user, account_id, session, account_type=account_type
    )
    try:
        view = _service(session).get_account(
            user.user_id,
            account_id,
            account_type=account_type,
        )
    except UserAccountError as exc:
        raise _http_error(exc) from exc
    return _enrich_recovery_status(session, view.as_dict())


@router.patch("/{account_id}")
def update_user_account(
    account_id: int,
    request: UpdateUserAccountRequest,
    user: AuthenticatedUser = Depends(
        require_permission("trading:write")
    ),
    session: Session = Depends(get_db_session),
):
    assert_account_access(
        user,
        account_id,
        session,
        account_type=request.account_type,
    )
    try:
        view = _service(session).update_account(
            user.user_id,
            account_id,
            account_type=request.account_type,
            account_name=request.account_name,
            is_active=request.is_active,
        )
    except UserAccountError as exc:
        raise _http_error(exc) from exc
    return view.as_dict()


@router.delete("/{account_id}")
def delete_user_account(
    account_id: int,
    account_type: str | None = Query(None),
    user: AuthenticatedUser = Depends(
        require_permission("trading:write")
    ),
    session: Session = Depends(get_db_session),
):
    assert_account_access(
        user, account_id, session, account_type=account_type
    )
    try:
        return _service(session).delete_account(
            user.user_id,
            account_id,
            account_type=account_type,
        )
    except UserAccountError as exc:
        raise _http_error(exc) from exc


@router.post("/{account_id}/set-default")
def set_default_user_account(
    account_id: int,
    account_type: str | None = Query(None),
    user: AuthenticatedUser = Depends(
        require_permission("trading:write")
    ),
    session: Session = Depends(get_db_session),
):
    assert_account_access(
        user, account_id, session, account_type=account_type
    )
    try:
        view = _service(session).set_default(
            user.user_id,
            account_id,
            account_type=account_type,
        )
    except UserAccountError as exc:
        raise _http_error(exc) from exc
    return view.as_dict()


@router.post("/{account_id}/connect")
def connect_user_account(
    account_id: int,
    account_type: str | None = Query(None),
    user: AuthenticatedUser = Depends(
        require_permission("trading:write")
    ),
    session: Session = Depends(get_db_session),
):
    assert_account_access(
        user, account_id, session, account_type=account_type
    )
    try:
        view = _service(session).connect(
            user.user_id,
            account_id,
            account_type=account_type,
        )
    except UserAccountError as exc:
        raise _http_error(exc) from exc
    return view.as_dict()


@router.post("/{account_id}/disconnect")
def disconnect_user_account(
    account_id: int,
    account_type: str | None = Query(None),
    user: AuthenticatedUser = Depends(
        require_permission("trading:write")
    ),
    session: Session = Depends(get_db_session),
):
    assert_account_access(
        user, account_id, session, account_type=account_type
    )
    try:
        view = _service(session).disconnect(
            user.user_id,
            account_id,
            account_type=account_type,
        )
    except UserAccountError as exc:
        raise _http_error(exc) from exc
    return view.as_dict()


@router.post("/{account_id}/sync")
def sync_user_account(
    account_id: int,
    account_type: str | None = Query(None),
    user: AuthenticatedUser = Depends(
        require_permission("trading:write")
    ),
    session: Session = Depends(get_db_session),
):
    """
    회원 스코프 동기화 메타 갱신.
    키움 OpenAPI 실동기화는 서버 공용 credential 을 사용하며
    admin 전용 POST /broker/kiwoom/account/sync 를 참고한다.
    """

    assert_account_access(
        user, account_id, session, account_type=account_type
    )
    try:
        view = _service(session).sync(
            user.user_id,
            account_id,
            account_type=account_type,
        )
    except UserAccountError as exc:
        raise _http_error(exc) from exc
    return {
        **view.as_dict(),
        "sync_note": (
            "Broker 실동기화는 서버 공용 Kiwoom 설정을 사용합니다. "
            "회원별 Client Secret 은 저장·노출하지 않습니다."
        ),
    }
