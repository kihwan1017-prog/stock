"""User Preference Repository — STEP72."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.auth.preference_models import UserPreference


class UserPreferenceRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, user_id: int) -> UserPreference | None:
        return self._session.get(UserPreference, user_id)

    def add(self, row: UserPreference) -> UserPreference:
        self._session.add(row)
        self._session.flush()
        return row

    def delete(self, row: UserPreference) -> None:
        self._session.delete(row)
        self._session.flush()

    def commit(self) -> None:
        self._session.commit()

    def list_by_users(self, user_ids: list[int]) -> list[UserPreference]:
        if not user_ids:
            return []
        return list(
            self._session.scalars(
                select(UserPreference).where(
                    UserPreference.user_id.in_(user_ids)
                )
            ).all()
        )
