"""Admin Runtime Pre-flight — 전역 또는 UBA 스코프."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from stock_platform.api.deps_admin import require_admin
from stock_platform.auth.deps import AuthenticatedUser
from stock_platform.database.session import get_db_session
from stock_platform.operation.runtime_preflight_service import (
    RuntimePreflightService,
    sanitize_preflight_payload,
)

router = APIRouter(
    prefix="/api/v1/admin/runtime",
    tags=["Admin Runtime Preflight"],
    dependencies=[Depends(require_admin)],
)


@router.get("/preflight")
def admin_runtime_preflight(
    mode: str = Query(
        default="LIVE_ON",
        description="LIVE_ON | ARM_ON | ORDER | SCHEDULER_RUN",
    ),
    user_broker_account_id: int | None = Query(
        default=None,
        ge=1,
        description="지정 시 해당 UBA만 검사 (UPBIT/KIWOOM dispatch)",
    ),
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
):
    """조회 전용 Pre-flight. DB 변경·실주문 없음."""

    normalized = str(mode or "LIVE_ON").upper()
    if normalized not in {"LIVE_ON", "ARM_ON", "ORDER", "SCHEDULER_RUN"}:
        normalized = "LIVE_ON"
    svc = RuntimePreflightService(session)
    if normalized in {"ARM_ON", "ORDER"} and user_broker_account_id is None:
        return sanitize_preflight_payload(
            {
                "mode": normalized,
                "overall": "BLOCKED",
                "overall_status": "BLOCKED",
                "live_on_allowed": False,
                "blockers": [
                    {
                        "code": "UBA",
                        "message": "ARM_ON/ORDER 는 user_broker_account_id 필수",
                        "status": "FAIL",
                    }
                ],
                "checks": [],
            }
        )
    if user_broker_account_id is not None:
        report = svc.run_for_uba(
            user_broker_account_id=int(user_broker_account_id),
            mode=normalized,  # type: ignore[arg-type]
        )
    else:
        report = svc.run(mode=normalized)  # type: ignore[arg-type]
    return sanitize_preflight_payload(report)
