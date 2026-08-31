"""Canonical KIWOOM multi-symbol mode resolution."""

from __future__ import annotations

from typing import Any

from stock_platform.operation.kiwoom_multi_symbol_universe.constants import (
    MODE_REAL,
    MODE_SHADOW,
)


def normalize_kiwoom_multi_symbol_mode(raw: Any) -> str:
    text = str(raw or MODE_SHADOW).strip().upper()
    if text == MODE_REAL:
        return MODE_REAL
    return MODE_SHADOW


def resolve_kiwoom_multi_symbol_mode(settings: Any | None = None) -> str:
    """SHADOW | REAL — legacy shadow_only=False 는 REAL 로 해석."""

    from stock_platform.common.settings import get_settings

    cfg = settings or get_settings()
    explicit = normalize_kiwoom_multi_symbol_mode(
        getattr(cfg, "kiwoom_multi_symbol_mode", MODE_SHADOW)
    )
    if explicit == MODE_REAL:
        return MODE_REAL
    # 레거시 호환 — shadow_only=False 이면 REAL
    if not bool(getattr(cfg, "kiwoom_multi_symbol_shadow_only", True)):
        return MODE_REAL
    return MODE_SHADOW


def is_kiwoom_multi_symbol_real_enabled(settings: Any | None = None) -> bool:
    return resolve_kiwoom_multi_symbol_mode(settings) == MODE_REAL


def is_kiwoom_multi_symbol_shadow_observability_enabled(
    settings: Any | None = None,
) -> bool:
    """REAL 승격 후에도 shadow lineage/observability 유지."""

    return bool(getattr(settings or _settings(), "kiwoom_multi_symbol_shadow_enabled", False))


def _settings() -> Any:
    from stock_platform.common.settings import get_settings

    return get_settings()
