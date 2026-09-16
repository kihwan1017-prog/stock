"""Admin — Korean message templates CRUD / preview / seed."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.auth.deps import AuthenticatedUser, require_admin
from stock_platform.database.session import get_db_session
from stock_platform.notification.builtin_templates import BUILTIN_TEMPLATES
from stock_platform.notification.events import NotificationEventType
from stock_platform.notification.normalizer import EVENT_CATEGORY
from stock_platform.notification.template_cache import (
    invalidate_template_cache,
    load_template_cache,
    seed_default_templates,
)
from stock_platform.notification.template_entities import (
    ChannelDeliveryLogEntity,
    MessageTemplateEntity,
)
from stock_platform.notification.template_pipeline import preview_template

router = APIRouter(
    prefix="/api/v1/admin/notification-templates",
    tags=["Admin Notification Templates"],
)


class TemplateUpsertBody(BaseModel):
    event_type: str = Field(min_length=1, max_length=80)
    channel: str = Field(default="TELEGRAM", max_length=32)
    locale: str = Field(default="ko-KR", max_length=16)
    severity: str = Field(default="INFO", max_length=20)
    category: str | None = Field(default=None, max_length=32)
    audience: str = Field(default="BOTH", max_length=16)
    title_template: str = Field(min_length=1, max_length=400)
    body_template: str = Field(min_length=1)
    short_body_template: str | None = None
    enabled: bool = True
    version: int | None = None


class TemplatePreviewBody(BaseModel):
    event_type: str = "ORDER_FILLED"
    title_template: str
    body_template: str
    sample_detail: dict[str, Any] = Field(default_factory=dict)


@router.get("")
def list_templates(
    channel: str | None = Query(default=None),
    event_type: str | None = Query(default=None),
    locale: str = Query(default="ko-KR"),
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
):
    stmt = select(MessageTemplateEntity).where(
        MessageTemplateEntity.locale == locale
    )
    if channel:
        stmt = stmt.where(MessageTemplateEntity.channel == channel.upper())
    if event_type:
        stmt = stmt.where(
            MessageTemplateEntity.event_type == event_type.upper()
        )
    rows = list(session.scalars(stmt.order_by(
        MessageTemplateEntity.event_type,
        MessageTemplateEntity.channel,
        MessageTemplateEntity.version.desc(),
    )))
    return {
        "items": [_row_dict(r) for r in rows],
        "total": len(rows),
        "event_catalog": [
            {
                "event_type": e.value,
                "category": EVENT_CATEGORY.get(e.value, "INFO"),
            }
            for e in NotificationEventType
        ],
        "builtin_count": len(BUILTIN_TEMPLATES),
    }


@router.get("/delivery-logs")
def list_delivery_logs(
    limit: int = Query(default=50, ge=1, le=200),
    event_type: str | None = Query(default=None),
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
):
    stmt = select(ChannelDeliveryLogEntity).order_by(
        ChannelDeliveryLogEntity.created_at.desc()
    ).limit(limit)
    if event_type:
        stmt = stmt.where(
            ChannelDeliveryLogEntity.event_type == event_type.upper()
        )
    rows = list(session.scalars(stmt))
    return {
        "items": [
            {
                "id": int(r.channel_delivery_log_id),
                "event_type": r.event_type,
                "channel": r.channel,
                "rendered_title": r.rendered_title,
                "rendered_message": r.rendered_message,
                "original_payload_json": r.original_payload_json,
                "status": r.status,
                "error_message": r.error_message,
                "template_id": r.template_id,
                "template_version": r.template_version,
                "locale": r.locale,
                "missing_variables": r.missing_variables_json,
                "sent_at": r.sent_at.isoformat() if r.sent_at else None,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]
    }


@router.post("/preview")
def preview(
    body: TemplatePreviewBody,
    _: AuthenticatedUser = Depends(require_admin),
):
    return preview_template(
        title_template=body.title_template,
        body_template=body.body_template,
        event_type=body.event_type,
        sample_detail=body.sample_detail or None,
    )


@router.post("/seed")
def seed_templates(
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_admin),
):
    result = seed_default_templates(
        session, actor=f"admin:{user.username}"
    )
    session.commit()
    return {"ok": True, **result}


@router.post("")
def upsert_template(
    body: TemplateUpsertBody,
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_admin),
):
    et = body.event_type.upper()
    ch = body.channel.upper()
    version = body.version
    if version is None:
        existing_versions = list(
            session.scalars(
                select(MessageTemplateEntity.version).where(
                    MessageTemplateEntity.event_type == et,
                    MessageTemplateEntity.channel == ch,
                    MessageTemplateEntity.locale == body.locale,
                )
            )
        )
        version = (max(existing_versions) + 1) if existing_versions else 1

    row = session.scalar(
        select(MessageTemplateEntity).where(
            MessageTemplateEntity.event_type == et,
            MessageTemplateEntity.channel == ch,
            MessageTemplateEntity.locale == body.locale,
            MessageTemplateEntity.version == int(version),
        )
    )
    now = datetime.now(timezone.utc)
    if row is None:
        row = MessageTemplateEntity(
            event_type=et,
            channel=ch,
            locale=body.locale,
            severity=body.severity.upper(),
            category=body.category,
            audience=body.audience.upper(),
            title_template=body.title_template,
            body_template=body.body_template,
            short_body_template=body.short_body_template,
            enabled=body.enabled,
            is_default=False,
            version=int(version),
            variables_json=[],
            created_by=user.username,
            updated_by=user.username,
            created_at=now,
            updated_at=now,
        )
        session.add(row)
    else:
        row.severity = body.severity.upper()
        row.category = body.category
        row.audience = body.audience.upper()
        row.title_template = body.title_template
        row.body_template = body.body_template
        row.short_body_template = body.short_body_template
        row.enabled = body.enabled
        row.updated_by = user.username
        row.updated_at = now

    session.flush()
    load_template_cache(session)
    session.commit()
    return {"ok": True, "item": _row_dict(row)}


@router.patch("/{template_id}/enabled")
def set_enabled(
    template_id: int,
    enabled: bool = Query(...),
    session: Session = Depends(get_db_session),
    user: AuthenticatedUser = Depends(require_admin),
):
    row = session.get(MessageTemplateEntity, int(template_id))
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="NOT_FOUND")
    row.enabled = bool(enabled)
    row.updated_by = user.username
    row.updated_at = datetime.now(timezone.utc)
    session.flush()
    load_template_cache(session)
    session.commit()
    return {"ok": True, "item": _row_dict(row)}


@router.post("/cache/reload")
def reload_cache(
    session: Session = Depends(get_db_session),
    _: AuthenticatedUser = Depends(require_admin),
):
    invalidate_template_cache()
    count = load_template_cache(session)
    return {"ok": True, "cached": count}


def _row_dict(row: MessageTemplateEntity) -> dict[str, Any]:
    return {
        "message_template_id": int(row.message_template_id),
        "event_type": row.event_type,
        "channel": row.channel,
        "locale": row.locale,
        "severity": row.severity,
        "category": row.category,
        "audience": row.audience,
        "title_template": row.title_template,
        "body_template": row.body_template,
        "short_body_template": row.short_body_template,
        "enabled": bool(row.enabled),
        "is_default": bool(row.is_default),
        "version": int(row.version),
        "created_by": row.created_by,
        "updated_by": row.updated_by,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }
