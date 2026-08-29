"""Trading alert preference store — delivery only (trading 미영향)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, String, Text, func, select, text
from sqlalchemy.orm import Mapped, Session, mapped_column

from stock_platform.database.base import Base
from stock_platform.notification.alert_v2.categories import (
    PREFERENCE_CATALOG,
    AlertPreferenceKey,
)


class TradingAlertPreference(Base):
    __tablename__ = "trading_alert_preference"
    __table_args__ = ({"schema": "notification"},)

    preference_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    updated_by: Mapped[str | None] = mapped_column(String(80), nullable=True)


_DEFAULTS: dict[str, bool] = {
    str(row["key"]): str(row["default_enabled"]).lower() == "true"
    for row in PREFERENCE_CATALOG
}


def ensure_preference_defaults(session: Session) -> None:
    """누락 키만 insert. 기존 값 강제 변경 금지."""

    existing = {
        r.preference_key
        for r in session.scalars(select(TradingAlertPreference)).all()
    }
    for row in PREFERENCE_CATALOG:
        key = row["key"]
        if key in existing:
            continue
        session.add(
            TradingAlertPreference(
                preference_key=key,
                enabled=_DEFAULTS.get(key, True),
                description=row.get("description"),
            )
        )
    session.flush()


def is_preference_enabled(
    session: Session | None,
    key: AlertPreferenceKey | str,
) -> bool:
    """DB 실패 시 fail-open True (알림 억제로 거래 영향 금지 목적과 별개 — delivery만).

    preference OFF면 False. DB 없으면 default 사용.
    """

    name = str(key.value if isinstance(key, AlertPreferenceKey) else key)
    default = _DEFAULTS.get(name, True)
    if session is None:
        return default
    try:
        row = session.get(TradingAlertPreference, name)
        if row is None:
            return default
        return bool(row.enabled)
    except Exception:  # noqa: BLE001
        return default


def list_preferences(session: Session) -> list[dict[str, Any]]:
    ensure_preference_defaults(session)
    rows = {
        r.preference_key: r
        for r in session.scalars(select(TradingAlertPreference)).all()
    }
    out: list[dict[str, Any]] = []
    for meta in PREFERENCE_CATALOG:
        key = meta["key"]
        row = rows.get(key)
        out.append(
            {
                "key": key,
                "group": meta["group"],
                "label": meta["label"],
                "description": meta["description"],
                "enabled": bool(row.enabled) if row else _DEFAULTS.get(key, True),
                "updated_at": row.updated_at.isoformat() if row and row.updated_at else None,
            }
        )
    return out


def patch_preferences(
    session: Session,
    *,
    updates: dict[str, bool],
    updated_by: str | None = None,
) -> list[dict[str, Any]]:
    ensure_preference_defaults(session)
    valid = {m["key"] for m in PREFERENCE_CATALOG}
    for key, enabled in updates.items():
        if key not in valid:
            continue
        row = session.get(TradingAlertPreference, key)
        if row is None:
            row = TradingAlertPreference(preference_key=key, enabled=bool(enabled))
            session.add(row)
        else:
            row.enabled = bool(enabled)
        row.updated_by = updated_by
    session.flush()
    return list_preferences(session)
