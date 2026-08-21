"""템플릿 DB 조회 캐시 + seed."""

from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.notification.builtin_templates import BUILTIN_TEMPLATES
from stock_platform.notification.code_dictionary import (
    BUILTIN_KO,
    set_db_overrides,
)
from stock_platform.notification.template_entities import (
    CodeTranslationEntity,
    MessageTemplateEntity,
)

_lock = threading.RLock()
_template_cache: dict[tuple[str, str, str], dict[str, Any]] = {}
_loaded_at: datetime | None = None


def invalidate_template_cache() -> None:
    global _template_cache, _loaded_at
    with _lock:
        _template_cache = {}
        _loaded_at = None


def get_cached_template(
    *,
    event_type: str,
    channel: str,
    locale: str = "ko-KR",
) -> dict[str, Any] | None:
    key = (event_type.upper(), channel.upper(), locale)
    with _lock:
        return _template_cache.get(key)


def load_template_cache(session: Session) -> int:
    """enabled+최신 version 템플릿을 메모리에 적재."""

    global _template_cache, _loaded_at
    rows = list(
        session.scalars(
            select(MessageTemplateEntity).where(
                MessageTemplateEntity.enabled.is_(True)
            )
        )
    )
    # event/channel/locale별 최고 version
    best: dict[tuple[str, str, str], MessageTemplateEntity] = {}
    for row in rows:
        key = (
            str(row.event_type).upper(),
            str(row.channel).upper(),
            str(row.locale),
        )
        cur = best.get(key)
        if cur is None or int(row.version) > int(cur.version):
            best[key] = row

    cache: dict[tuple[str, str, str], dict[str, Any]] = {}
    for key, row in best.items():
        cache[key] = {
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
            "version": int(row.version),
            "variables_json": list(row.variables_json or []),
        }

    code_rows = list(
        session.scalars(
            select(CodeTranslationEntity).where(
                CodeTranslationEntity.enabled.is_(True)
            )
        )
    )
    set_db_overrides(
        [
            {
                "code_group": r.code_group,
                "code": r.code,
                "locale": r.locale,
                "label": r.label,
            }
            for r in code_rows
        ]
    )

    with _lock:
        _template_cache = cache
        _loaded_at = datetime.now(timezone.utc)
    return len(cache)


def ensure_cache_loaded(session: Session | None = None) -> None:
    with _lock:
        if _template_cache and _loaded_at is not None:
            return
    if session is None:
        return
    try:
        load_template_cache(session)
    except Exception:  # noqa: BLE001
        # DB 실패 시 builtin만 사용
        return


def seed_default_templates(
    session: Session,
    *,
    actor: str = "SYSTEM_SEED",
    channels: tuple[str, ...] = ("TELEGRAM", "TOSS", "COMMON"),
) -> dict[str, int]:
    """builtin → DB upsert (version=1, is_default)."""

    created = 0
    skipped = 0
    for channel in channels:
        for row in BUILTIN_TEMPLATES:
            if row["event_type"] == "GENERIC" and channel != "COMMON":
                continue
            exists = session.scalar(
                select(MessageTemplateEntity).where(
                    MessageTemplateEntity.event_type == row["event_type"],
                    MessageTemplateEntity.channel == channel,
                    MessageTemplateEntity.locale == "ko-KR",
                    MessageTemplateEntity.version == 1,
                )
            )
            if exists is not None:
                skipped += 1
                continue
            body = row["body_template"]
            short = row.get("short_body_template")
            if channel == "TOSS":
                body = str(short or body)
            session.add(
                MessageTemplateEntity(
                    event_type=row["event_type"],
                    channel=channel,
                    locale="ko-KR",
                    severity=str(row.get("severity") or "INFO"),
                    category=str(row.get("category") or "INFO"),
                    audience="BOTH",
                    title_template=row["title_template"],
                    body_template=body,
                    short_body_template=short,
                    enabled=True,
                    is_default=True,
                    version=1,
                    variables_json=[],
                    created_by=actor,
                    updated_by=actor,
                )
            )
            created += 1

    code_created = 0
    for group, mapping in BUILTIN_KO.items():
        for code, label in mapping.items():
            exists = session.scalar(
                select(CodeTranslationEntity).where(
                    CodeTranslationEntity.code_group == group,
                    CodeTranslationEntity.code == code,
                    CodeTranslationEntity.locale == "ko-KR",
                )
            )
            if exists is not None:
                continue
            session.add(
                CodeTranslationEntity(
                    code_group=group,
                    code=code,
                    locale="ko-KR",
                    label=label,
                    enabled=True,
                )
            )
            code_created += 1

    session.flush()
    load_template_cache(session)
    return {
        "templates_created": created,
        "templates_skipped": skipped,
        "codes_created": code_created,
    }
