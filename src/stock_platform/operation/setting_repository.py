from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.operation.setting_models import (
    AppSetting,
    AppSettingHistory,
)


class AppSettingRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, setting_key: str) -> AppSetting | None:
        return self._session.get(AppSetting, setting_key)

    def list_by_category(
        self,
        category: str | None = None,
    ) -> list[AppSetting]:
        stmt = select(AppSetting).order_by(
            AppSetting.category.asc(),
            AppSetting.setting_key.asc(),
        )
        if category:
            stmt = stmt.where(AppSetting.category == category)
        return list(self._session.scalars(stmt))

    def upsert(self, entity: AppSetting) -> AppSetting:
        self._session.add(entity)
        self._session.flush()
        return entity

    def add_history(
        self,
        *,
        setting_key: str,
        old_value: str | None,
        new_value: str | None,
        actor: str,
        change_reason: str | None,
    ) -> AppSettingHistory:
        row = AppSettingHistory(
            setting_key=setting_key,
            old_value=old_value,
            new_value=new_value,
            actor=actor,
            change_reason=change_reason,
            created_at=datetime.now(timezone.utc),
        )
        self._session.add(row)
        self._session.flush()
        return row

    def list_history(
        self,
        *,
        setting_key: str | None = None,
        limit: int = 50,
    ) -> list[AppSettingHistory]:
        stmt = select(AppSettingHistory)
        if setting_key:
            stmt = stmt.where(
                AppSettingHistory.setting_key == setting_key
            )
        stmt = stmt.order_by(
            AppSettingHistory.created_at.desc(),
            AppSettingHistory.history_id.desc(),
        ).limit(max(1, min(limit, 500)))
        return list(self._session.scalars(stmt))
