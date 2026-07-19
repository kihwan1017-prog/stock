from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class SettingItemResponse(BaseModel):
    key: str
    category: str
    value: str
    typed_value: Any = None
    value_type: str
    is_secret: bool
    description: str | None = None
    updated_by: str | None = None
    updated_at: datetime | None = None
    version: int = 0
    min_value: float | None = None
    max_value: float | None = None
    allowed_values: list[str] | None = None


class SettingCategoryResponse(BaseModel):
    code: str
    name: str
    count: int


class SettingUpdateItem(BaseModel):
    key: str = Field(min_length=1, max_length=100)
    value: Any


class SettingBatchUpdateRequest(BaseModel):
    items: list[SettingUpdateItem] = Field(min_length=1)
    change_reason: str | None = Field(
        default=None, max_length=255
    )


class SettingHistoryResponse(BaseModel):
    history_id: int
    key: str
    old_value: str | None = None
    new_value: str | None = None
    actor: str
    change_reason: str | None = None
    created_at: datetime
