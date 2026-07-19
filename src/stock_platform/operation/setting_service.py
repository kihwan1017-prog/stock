from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from stock_platform.common.settings import Settings, get_settings
from stock_platform.operation.setting_catalog import (
    CATEGORIES,
    DEFINITION_BY_KEY,
    MASKED_VALUE,
    SETTING_DEFINITIONS,
    SettingDefinition,
    is_masked_input,
    mask_secret,
    parse_value,
    serialize_value,
)
from stock_platform.operation.setting_models import AppSetting
from stock_platform.operation.setting_repository import (
    AppSettingRepository,
)


class SettingError(ValueError):
    """설정 도메인 오류."""


class AppSettingService:
    """DB Settings CRUD · 검증 · 마스킹 · 시드."""

    def __init__(
        self,
        repository: AppSettingRepository,
        settings: Settings | None = None,
    ) -> None:
        self._repository = repository
        self._settings = settings or get_settings()

    def ensure_seeded(self) -> int:
        """카탈로그 키가 DB에 없으면 env/default로 시드."""

        created = 0
        for definition in SETTING_DEFINITIONS:
            existing = self._repository.get(definition.key)
            if existing is not None:
                continue
            raw = self._default_raw(definition)
            entity = AppSetting(
                setting_key=definition.key,
                category=definition.category,
                value_text=raw,
                value_type=definition.value_type,
                is_secret=definition.is_secret,
                description=definition.description,
                updated_by="system:seed",
                updated_at=datetime.now(timezone.utc),
                version=1,
            )
            self._repository.upsert(entity)
            created += 1
        return created

    def list_settings(
        self,
        *,
        category: str | None = None,
        include_secrets: bool = False,
    ) -> list[dict[str, Any]]:
        self.ensure_seeded()
        if category and category not in CATEGORIES:
            raise SettingError(
                f"알 수 없는 category: {category}"
            )

        rows = self._repository.list_by_category(category)
        by_key = {row.setting_key: row for row in rows}
        result: list[dict[str, Any]] = []
        for definition in SETTING_DEFINITIONS:
            if category and definition.category != category:
                continue
            row = by_key.get(definition.key)
            result.append(
                self._to_view(
                    definition,
                    row,
                    include_secrets=include_secrets,
                )
            )
        return result

    def get_setting(
        self,
        key: str,
        *,
        include_secrets: bool = False,
    ) -> dict[str, Any]:
        self.ensure_seeded()
        definition = DEFINITION_BY_KEY.get(key)
        if definition is None:
            raise SettingError(f"알 수 없는 설정 키: {key}")
        row = self._repository.get(key)
        return self._to_view(
            definition,
            row,
            include_secrets=include_secrets,
        )

    def update_settings(
        self,
        updates: list[dict[str, Any]],
        *,
        actor: str,
        change_reason: str | None = None,
    ) -> list[dict[str, Any]]:
        self.ensure_seeded()
        if not updates:
            raise SettingError("변경할 설정이 없습니다.")

        # 교차 검증용 스냅샷
        current_map = {
            row.setting_key: row.value_text
            for row in self._repository.list_by_category()
        }
        changed: list[dict[str, Any]] = []

        for item in updates:
            key = str(item.get("key") or "").strip()
            if key not in DEFINITION_BY_KEY:
                raise SettingError(f"알 수 없는 설정 키: {key}")
            definition = DEFINITION_BY_KEY[key]
            raw_input = item.get("value")
            if raw_input is None:
                raise SettingError(f"{key}: value가 필요합니다.")

            raw_text = str(raw_input)
            if definition.is_secret and is_masked_input(raw_text):
                # 마스킹/빈 값이면 기존 유지
                continue

            validated = self._validate(definition, raw_text)
            new_text = serialize_value(
                validated, definition.value_type
            )
            old_text = current_map.get(key, "")
            if old_text == new_text:
                continue

            row = self._repository.get(key)
            if row is None:
                row = AppSetting(
                    setting_key=key,
                    category=definition.category,
                    value_text=new_text,
                    value_type=definition.value_type,
                    is_secret=definition.is_secret,
                    description=definition.description,
                    updated_by=actor,
                    updated_at=datetime.now(timezone.utc),
                    version=1,
                )
            else:
                row.value_text = new_text
                row.updated_by = actor
                row.updated_at = datetime.now(timezone.utc)
                row.version = int(row.version or 1) + 1
            self._repository.upsert(row)

            self._repository.add_history(
                setting_key=key,
                old_value=mask_secret(
                    old_text, is_secret=definition.is_secret
                ),
                new_value=mask_secret(
                    new_text, is_secret=definition.is_secret
                ),
                actor=actor,
                change_reason=change_reason,
            )
            current_map[key] = new_text
            changed.append(
                self._to_view(
                    definition,
                    row,
                    include_secrets=False,
                )
            )

        # trading 교차 규칙
        self._validate_trading_cross(current_map)
        invalidate_setting_cache()
        return changed

    def list_history(
        self,
        *,
        setting_key: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        rows = self._repository.list_history(
            setting_key=setting_key,
            limit=limit,
        )
        return [
            {
                "history_id": row.history_id,
                "key": row.setting_key,
                "old_value": row.old_value,
                "new_value": row.new_value,
                "actor": row.actor,
                "change_reason": row.change_reason,
                "created_at": row.created_at,
            }
            for row in rows
        ]

    def get_raw_value(self, key: str) -> str | None:
        """런타임 오버레이용 — 마스킹하지 않은 원문."""

        self.ensure_seeded()
        row = self._repository.get(key)
        if row is None:
            definition = DEFINITION_BY_KEY.get(key)
            if definition is None:
                return None
            return self._default_raw(definition)
        return row.value_text

    def get_typed_value(self, key: str) -> Any:
        definition = DEFINITION_BY_KEY.get(key)
        if definition is None:
            raise SettingError(f"알 수 없는 설정 키: {key}")
        raw = self.get_raw_value(key) or ""
        return parse_value(raw, definition.value_type)

    def categories(self) -> list[dict[str, Any]]:
        return [
            {
                "code": code,
                "name": {
                    "system": "시스템 설정",
                    "ai": "AI 설정",
                    "risk": "Risk 설정",
                    "scheduler": "Scheduler 설정",
                    "trading": "거래 설정",
                    "environment": "환경설정",
                }.get(code, code),
                "count": sum(
                    1
                    for item in SETTING_DEFINITIONS
                    if item.category == code
                ),
            }
            for code in CATEGORIES
        ]

    def _default_raw(self, definition: SettingDefinition) -> str:
        if definition.env_attr:
            value = getattr(
                self._settings, definition.env_attr, None
            )
            if value is not None:
                return serialize_value(
                    value, definition.value_type
                )
        return definition.default

    def _validate(
        self,
        definition: SettingDefinition,
        raw_text: str,
    ) -> Any:
        try:
            parsed = parse_value(raw_text, definition.value_type)
        except Exception as exc:
            raise SettingError(
                f"{definition.key}: 값 형식이 올바르지 않습니다."
            ) from exc

        if definition.allowed_values is not None:
            as_text = serialize_value(
                parsed, definition.value_type
            )
            if as_text not in definition.allowed_values:
                raise SettingError(
                    f"{definition.key}: 허용 값 "
                    f"{definition.allowed_values}"
                )

        if definition.value_type in {"int", "float"}:
            number = float(parsed)
            if (
                definition.min_value is not None
                and number < definition.min_value
            ):
                raise SettingError(
                    f"{definition.key}: 최소값 "
                    f"{definition.min_value}"
                )
            if (
                definition.max_value is not None
                and number > definition.max_value
            ):
                raise SettingError(
                    f"{definition.key}: 최대값 "
                    f"{definition.max_value}"
                )

        if definition.key == "ollama_base_url":
            text = str(parsed).strip()
            if not (
                text.startswith("http://")
                or text.startswith("https://")
            ):
                raise SettingError(
                    "ollama_base_url은 http(s) URL이어야 합니다."
                )
        return parsed

    def _validate_trading_cross(
        self,
        current_map: dict[str, str],
    ) -> None:
        use_mock = parse_value(
            current_map.get("kiwoom_use_mock", "true"),
            "bool",
        )
        live = parse_value(
            current_map.get(
                "kiwoom_live_order_enabled", "false"
            ),
            "bool",
        )
        if live and use_mock:
            raise SettingError(
                "kiwoom_live_order_enabled=true 와 "
                "kiwoom_use_mock=true 는 함께 사용할 수 없습니다."
            )

    def _to_view(
        self,
        definition: SettingDefinition,
        row: AppSetting | None,
        *,
        include_secrets: bool,
    ) -> dict[str, Any]:
        raw = (
            row.value_text
            if row is not None
            else self._default_raw(definition)
        )
        display = raw
        if definition.is_secret and not include_secrets:
            display = mask_secret(
                raw, is_secret=True
            ) or MASKED_VALUE

        typed: Any
        try:
            typed = parse_value(
                raw if (include_secrets or not definition.is_secret) else "",
                definition.value_type,
            ) if not definition.is_secret or include_secrets else None
        except Exception:
            typed = None

        if definition.is_secret and not include_secrets:
            typed = None

        return {
            "key": definition.key,
            "category": definition.category,
            "value": display,
            "typed_value": typed,
            "value_type": definition.value_type,
            "is_secret": definition.is_secret,
            "description": definition.description,
            "updated_by": (
                row.updated_by if row is not None else None
            ),
            "updated_at": (
                row.updated_at if row is not None else None
            ),
            "version": row.version if row is not None else 0,
            "min_value": definition.min_value,
            "max_value": definition.max_value,
            "allowed_values": (
                list(definition.allowed_values)
                if definition.allowed_values
                else None
            ),
        }


_overlay_cache: dict[str, str] | None = None


def invalidate_setting_cache() -> None:
    global _overlay_cache
    _overlay_cache = None


def load_setting_overlay(
    repository: AppSettingRepository,
) -> dict[str, str]:
    global _overlay_cache
    if _overlay_cache is not None:
        return _overlay_cache
    rows = repository.list_by_category()
    _overlay_cache = {
        row.setting_key: row.value_text for row in rows
    }
    return _overlay_cache
