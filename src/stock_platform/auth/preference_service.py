"""User Preferences Service — STEP72.

관리자 `/api/v1/settings`(app_setting)와 완전 분리.
본인 JWT user_id 행만 조회·수정.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.auth.preference_models import UserPreference
from stock_platform.auth.preference_repository import UserPreferenceRepository
from stock_platform.trading.account_repository import PaperAccountRepository
from stock_platform.trading.watchlist_models import WatchlistItem


logger = logging.getLogger(__name__)

THEMES = frozenset({"light", "dark", "system"})
LANGUAGES = frozenset({"KO", "EN"})
TIMEZONES = frozenset({"Asia/Seoul", "UTC"})
DATE_FORMATS = frozenset({"YYYY-MM-DD", "YYYY/MM/DD", "DD/MM/YYYY", "MM/DD/YYYY"})
NUMBER_FORMATS = frozenset({"1,234.56", "1.234,56"})
CURRENCIES = frozenset({"KRW", "USD"})
MARKETS = frozenset({"KRX", "NASDAQ", "UPBIT"})
DASHBOARDS = frozenset(
    {"Dashboard", "Portfolio", "Watchlist", "News", "AI", "Notifications"}
)

DEFAULTS: dict[str, Any] = {
    "theme": "system",
    "language": "KO",
    "timezone": "Asia/Seoul",
    "date_format": "YYYY-MM-DD",
    "number_format": "1,234.56",
    "currency": "KRW",
    "default_market": "KRX",
    "default_account_id": None,
    "default_watchlist_id": None,
    "default_dashboard": "Dashboard",
    "items_per_page": 20,
    "ai_enabled": True,
    "ai_auto_summary": True,
    "ai_recommendation_enabled": True,
    "notification_enabled": True,
    "telegram_enabled": False,
    "email_enabled": False,
    "web_enabled": True,
}

UPDATABLE_FIELDS = frozenset(DEFAULTS.keys())


class UserPreferenceError(ValueError):
    pass


class UserPreferenceService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._repo = UserPreferenceRepository(session)
        self._paper = PaperAccountRepository(session)

    def get_or_create(self, user_id: int) -> dict[str, Any]:
        row = self._repo.get(user_id)
        if row is None:
            row = UserPreference(user_id=user_id, **DEFAULTS)
            self._repo.add(row)
            self._repo.commit()
            logger.info("user_preference_created user_id=%s", user_id)
        return self._to_dict(row)

    def update(
        self,
        user_id: int,
        patch: dict[str, Any],
        *,
        replace: bool = False,
    ) -> dict[str, Any]:
        """replace=True 이면 PUT(전체 교체), False면 PATCH(부분)."""

        cleaned = self._validate_patch(patch)
        row = self._repo.get(user_id)
        if row is None:
            row = UserPreference(user_id=user_id, **DEFAULTS)
            self._repo.add(row)

        if replace:
            # 지정되지 않은 필드는 기본값으로 되돌림
            for key, default in DEFAULTS.items():
                setattr(row, key, cleaned.get(key, default))
        else:
            for key, value in cleaned.items():
                setattr(row, key, value)

        self._assert_account_ownership(user_id, row.default_account_id)
        self._assert_watchlist_ownership(user_id, row.default_watchlist_id)
        if row.default_account_id is not None:
            self._sync_paper_default(user_id, int(row.default_account_id))

        row.updated_at = datetime.now(timezone.utc)
        self._repo.commit()
        logger.info(
            "user_preference_updated user_id=%s fields=%s replace=%s",
            user_id,
            sorted(cleaned.keys()),
            replace,
        )
        return self._to_dict(row)

    def reset(self, user_id: int) -> dict[str, Any]:
        row = self._repo.get(user_id)
        if row is None:
            row = UserPreference(user_id=user_id, **DEFAULTS)
            self._repo.add(row)
        else:
            for key, default in DEFAULTS.items():
                setattr(row, key, default)
            row.updated_at = datetime.now(timezone.utc)
        self._repo.commit()
        logger.info("user_preference_reset user_id=%s", user_id)
        return self._to_dict(row)

    def _validate_patch(self, patch: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(patch, dict):
            raise UserPreferenceError("설정 본문이 올바르지 않습니다.")
        unknown = set(patch.keys()) - UPDATABLE_FIELDS
        if unknown:
            raise UserPreferenceError(
                f"허용되지 않는 필드: {', '.join(sorted(unknown))}"
            )
        cleaned: dict[str, Any] = {}
        for key, value in patch.items():
            cleaned[key] = self._coerce_field(key, value)
        return cleaned

    def _coerce_field(self, key: str, value: Any) -> Any:
        if key == "theme":
            text = str(value).strip().lower()
            if text not in THEMES:
                raise UserPreferenceError(
                    "theme은 light|dark|system 만 허용됩니다."
                )
            return text
        if key == "language":
            text = str(value).strip().upper()
            if text not in LANGUAGES:
                raise UserPreferenceError("language는 KO|EN 만 허용됩니다.")
            return text
        if key == "timezone":
            text = str(value).strip()
            if text not in TIMEZONES:
                raise UserPreferenceError(
                    "timezone은 Asia/Seoul|UTC 만 허용됩니다."
                )
            return text
        if key == "date_format":
            text = str(value).strip()
            if text not in DATE_FORMATS:
                raise UserPreferenceError("지원하지 않는 date_format 입니다.")
            return text
        if key == "number_format":
            text = str(value).strip()
            if text not in NUMBER_FORMATS:
                raise UserPreferenceError(
                    "number_format은 1,234.56|1.234,56 만 허용됩니다."
                )
            return text
        if key == "currency":
            text = str(value).strip().upper()
            if text not in CURRENCIES:
                raise UserPreferenceError("currency는 KRW|USD 만 허용됩니다.")
            return text
        if key == "default_market":
            text = str(value).strip().upper()
            if text not in MARKETS:
                raise UserPreferenceError(
                    "default_market은 KRX|NASDAQ|UPBIT 만 허용됩니다."
                )
            return text
        if key == "default_dashboard":
            text = str(value).strip()
            if text not in DASHBOARDS:
                raise UserPreferenceError(
                    f"default_dashboard는 {', '.join(sorted(DASHBOARDS))} 만 허용됩니다."
                )
            return text
        if key == "items_per_page":
            try:
                n = int(value)
            except (TypeError, ValueError) as exc:
                raise UserPreferenceError(
                    "items_per_page는 정수여야 합니다."
                ) from exc
            if n < 5 or n > 100:
                raise UserPreferenceError(
                    "items_per_page는 5~100 범위여야 합니다."
                )
            return n
        if key in {
            "default_account_id",
            "default_watchlist_id",
        }:
            if value is None or value == "":
                return None
            try:
                return int(value)
            except (TypeError, ValueError) as exc:
                raise UserPreferenceError(
                    f"{key}는 정수 또는 null 이어야 합니다."
                ) from exc
        if key in {
            "ai_enabled",
            "ai_auto_summary",
            "ai_recommendation_enabled",
            "notification_enabled",
            "telegram_enabled",
            "email_enabled",
            "web_enabled",
        }:
            if not isinstance(value, bool):
                raise UserPreferenceError(f"{key}는 boolean 이어야 합니다.")
            return value
        return value

    def _assert_account_ownership(
        self, user_id: int, account_id: int | None
    ) -> None:
        if account_id is None:
            return
        account = self._paper.get_account(account_id)
        if account is None:
            raise UserPreferenceError("기본 계좌를 찾을 수 없습니다.")
        if account.user_id is None or int(account.user_id) != int(user_id):
            raise UserPreferenceError(
                "본인 소유가 아닌 계좌는 기본 계좌로 설정할 수 없습니다."
            )

    def _assert_watchlist_ownership(
        self, user_id: int, watchlist_id: int | None
    ) -> None:
        if watchlist_id is None:
            return
        row = self._session.scalar(
            select(WatchlistItem).where(
                WatchlistItem.watchlist_id == watchlist_id,
                WatchlistItem.user_id == user_id,
            )
        )
        if row is None:
            raise UserPreferenceError(
                "본인 관심종목이 아니거나 존재하지 않습니다."
            )

    def _sync_paper_default(self, user_id: int, account_id: int) -> None:
        """preferences 기본 계좌와 paper_account.is_default 동기화."""

        accounts = self._paper.list_accounts(user_id=user_id)
        for account in accounts:
            account.is_default = int(account.account_id) == int(account_id)

    @staticmethod
    def _to_dict(row: UserPreference) -> dict[str, Any]:
        return {
            "user_id": row.user_id,
            "theme": row.theme,
            "language": row.language,
            "timezone": row.timezone,
            "date_format": row.date_format,
            "number_format": row.number_format,
            "currency": row.currency,
            "default_market": row.default_market,
            "default_account_id": row.default_account_id,
            "default_watchlist_id": row.default_watchlist_id,
            "default_dashboard": row.default_dashboard,
            "items_per_page": row.items_per_page,
            "ai_enabled": row.ai_enabled,
            "ai_auto_summary": row.ai_auto_summary,
            "ai_recommendation_enabled": row.ai_recommendation_enabled,
            "notification_enabled": row.notification_enabled,
            "telegram_enabled": row.telegram_enabled,
            "email_enabled": row.email_enabled,
            "web_enabled": row.web_enabled,
            "created_at": row.created_at,
            "updated_at": row.updated_at,
        }
