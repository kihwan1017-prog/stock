from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from stock_platform.auth.deps import (
    AuthenticatedUser,
    require_permission,
)
from stock_platform.common.rate_limit import enforce_rate_limit
from stock_platform.notification.events import (
    NotificationEventType,
)
from stock_platform.notification.publisher import (
    notification_publisher,
)
from stock_platform.notification.runtime import (
    notification_service,
    risk_notification_sender,
)


router = APIRouter(
    prefix="/api/v1/notification",
    tags=["Notification"],
)


class NotificationTestRequest(BaseModel):
    title: str = Field(
        default="Stock Platform 테스트 알림",
        min_length=1,
        max_length=200,
    )
    message: str = Field(
        default="Telegram과 Slack 알림 연결 테스트입니다.",
        min_length=1,
        max_length=1000,
    )
    detail: dict = {}
    event_type: str = Field(
        default=NotificationEventType.SYSTEM_START.value,
        min_length=1,
        max_length=64,
    )


@router.post("/test")
async def send_test_notification(
    request: NotificationTestRequest,
    http_request: Request,
    _: AuthenticatedUser = Depends(
        require_permission("trading:write")
    ),
):
    enforce_rate_limit(
        http_request,
        scope="notification_test",
        limit=10,
        window_seconds=60,
    )
    event = await notification_publisher.publish_async(
        event_type=request.event_type,
        title=request.title,
        message=request.message,
        detail=request.detail,
    )
    return {
        "published": True,
        "event_type": event.event_type,
        "published_at": event.published_at,
        "channels": risk_notification_sender.status(),
    }


@router.get("/status")
def get_notification_status(
    _: AuthenticatedUser = Depends(
        require_permission("trading:read")
    ),
):
    return notification_service.status()
