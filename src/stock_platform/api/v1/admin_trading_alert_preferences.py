"""Admin Trading Alert Preference API — delivery only."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from stock_platform.auth.deps import AuthenticatedUser, require_admin
from stock_platform.database.session import get_db_session
from stock_platform.notification.alert_v2.categories import PREFERENCE_CATALOG
from stock_platform.notification.alert_v2.mapping import (
    resolve_preference_key,
    resolve_top_category,
    title_prefix_for,
)
from stock_platform.notification.alert_v2.preferences import (
    list_preferences,
    patch_preferences,
)
from stock_platform.notification.history import notification_history

router = APIRouter(
    prefix="/api/v1/admin/trading-alert-preferences",
    tags=["AdminTradingAlerts"],
)


class PreferencePatchBody(BaseModel):
    preferences: dict[str, bool] = Field(default_factory=dict)


@router.get("")
def get_trading_alert_preferences(
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
):
    items = list_preferences(session)
    return {
        "items": items,
        "groups": ["UPBIT", "KIWOOM", "SYSTEM"],
        "delivery_only_notice": (
            "알림 수신 여부만 변경하며 자동매매 동작에는 영향을 주지 않습니다."
        ),
        "catalog": PREFERENCE_CATALOG,
    }


@router.patch("")
def patch_trading_alert_preferences(
    body: PreferencePatchBody,
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_admin),
):
    items = patch_preferences(
        session,
        updates=body.preferences or {},
        updated_by=str(getattr(user, "username", None) or user.user_id),
    )
    session.commit()
    return {
        "items": items,
        "delivery_only_notice": (
            "알림 수신 여부만 변경하며 자동매매 동작에는 영향을 주지 않습니다."
        ),
    }


@router.get("/history")
def get_trading_alert_history(
    category: str | None = None,
    event_type: str | None = None,
    limit: int = 50,
    _: AuthenticatedUser = Depends(require_admin),
):
    """In-memory notification history + V2 category labels."""

    lim = max(1, min(int(limit or 50), 200))
    records = list(notification_history.recent(limit=lim))
    items = []
    for rec in records:
        et = str(getattr(rec, "event_type", "") or "")
        # history record has no detail — use empty; title/message still useful
        detail: dict = {}
        if event_type and et.upper() != event_type.upper():
            continue
        top = resolve_top_category(et, detail=detail).value
        if category and top != category.upper():
            continue
        pref = resolve_preference_key(et, detail=detail)
        items.append(
            {
                "event_type": et,
                "title": getattr(rec, "title", None),
                "message": getattr(rec, "message", None),
                "category": top,
                "preference_key": pref.value if pref else None,
                "prefix": title_prefix_for(et, detail=detail),
                "symbol": None,
                "status": "SENT" if getattr(rec, "success", False) else "FAILED",
                "created_at": str(getattr(rec, "created_at", "") or ""),
                "channel_results": getattr(rec, "channel_results", None),
            }
        )
    return {"items": items, "count": len(items)}
