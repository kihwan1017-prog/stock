from fastapi import APIRouter
from pydantic import BaseModel, Field

from stock_platform.notification.runtime import (
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


@router.post("/test")
async def send_test_notification(
    request: NotificationTestRequest,
):
    return await risk_notification_sender.send(
        title=request.title,
        message=request.message,
        detail=request.detail,
    )


@router.get("/status")
def get_notification_status():
    return risk_notification_sender.status()
