"""REAL exit protection mode — INHERIT / ENABLED / DISABLED.

UBA NULL rate alone is NOT disable. Explicit mode=DISABLED disables REAL
executor use even when SYSTEM default rates exist.

Shadow research paths must ignore these modes.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal

ExitProtectionMode = Literal["INHERIT", "ENABLED", "DISABLED"]

MODE_INHERIT: ExitProtectionMode = "INHERIT"
MODE_ENABLED: ExitProtectionMode = "ENABLED"
MODE_DISABLED: ExitProtectionMode = "DISABLED"

_VALID_MODES = frozenset({MODE_INHERIT, MODE_ENABLED, MODE_DISABLED})

PROTECTION_KEYS = (
    "stop_loss",
    "take_profit",
    "trailing_stop",
)

_MODE_FIELD = {
    "stop_loss": "stop_loss_mode",
    "take_profit": "take_profit_mode",
    "trailing_stop": "trailing_stop_mode",
}
_RATE_FIELD = {
    "stop_loss": "stop_loss_rate",
    "take_profit": "take_profit_rate",
    "trailing_stop": "trailing_stop_rate",
}


def normalize_exit_protection_mode(raw: Any) -> ExitProtectionMode:
    """알 수 없거나 비어 있으면 INHERIT (기존 NULL 상속 호환)."""

    text = str(raw or "").strip().upper()
    if text in _VALID_MODES:
        return text  # type: ignore[return-value]
    return MODE_INHERIT


@dataclass(frozen=True, slots=True)
class ExitProtectionResolved:
    """단일 보호청산의 raw/effective 표현."""

    mode: ExitProtectionMode
    configured_rate: Decimal | None
    effective_enabled: bool
    effective_rate: Decimal | None
    source: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "configured_rate": (
                str(self.configured_rate)
                if self.configured_rate is not None
                else None
            ),
            "effective_enabled": self.effective_enabled,
            "effective_rate": (
                str(self.effective_rate)
                if self.effective_rate is not None
                else None
            ),
            "source": self.source,
        }


def resolve_exit_protection(
    *,
    key: str,
    system_rate: Decimal | None,
    user_mode: Any,
    user_rate: Decimal | None,
    account_mode: Any,
    account_rate: Decimal | None,
) -> ExitProtectionResolved:
    """SYSTEM rate를 기반으로 USER → ACCOUNT mode를 적용.

    ACCOUNT DISABLED가 최우선으로 REAL 비활성.
    """

    rate_field = _RATE_FIELD[key]
    # 시작: SYSTEM (항상 base enabled if rate present)
    current_rate = system_rate
    current_source = "SYSTEM"
    configured_rate: Decimal | None = None

    u_mode = normalize_exit_protection_mode(user_mode)
    if u_mode == MODE_DISABLED:
        return ExitProtectionResolved(
            mode=MODE_DISABLED,
            configured_rate=user_rate,
            effective_enabled=False,
            effective_rate=None,
            source="USER",
        )
    if u_mode == MODE_ENABLED:
        if user_rate is None:
            # ENABLED인데 rate 없으면 fail-closed disable
            return ExitProtectionResolved(
                mode=MODE_ENABLED,
                configured_rate=None,
                effective_enabled=False,
                effective_rate=None,
                source="USER",
            )
        current_rate = user_rate
        current_source = "USER"
        configured_rate = user_rate
    elif user_rate is not None:
        # INHERIT지만 rate가 있으면 rate overlay (기존 semantics)
        current_rate = user_rate
        current_source = "USER"
        configured_rate = user_rate

    a_mode = normalize_exit_protection_mode(account_mode)
    if a_mode == MODE_DISABLED:
        return ExitProtectionResolved(
            mode=MODE_DISABLED,
            configured_rate=account_rate,
            effective_enabled=False,
            effective_rate=None,
            source="UBA",
        )
    if a_mode == MODE_ENABLED:
        if account_rate is None:
            return ExitProtectionResolved(
                mode=MODE_ENABLED,
                configured_rate=None,
                effective_enabled=False,
                effective_rate=None,
                source="UBA",
            )
        return ExitProtectionResolved(
            mode=MODE_ENABLED,
            configured_rate=account_rate,
            effective_enabled=True,
            effective_rate=account_rate,
            source="UBA",
        )
    if account_rate is not None:
        current_rate = account_rate
        current_source = "UBA"
        configured_rate = account_rate

    # INHERIT chain result
    enabled = current_rate is not None
    return ExitProtectionResolved(
        mode=MODE_INHERIT if a_mode == MODE_INHERIT and u_mode == MODE_INHERIT else (
            a_mode if a_mode != MODE_INHERIT else u_mode
        ),
        configured_rate=configured_rate,
        effective_enabled=enabled,
        effective_rate=current_rate if enabled else None,
        source=current_source,
    )


def exit_protections_bundle(
    *,
    system_rates: dict[str, Decimal | None],
    user_row: Any | None,
    account_row: Any | None,
) -> dict[str, ExitProtectionResolved]:
    out: dict[str, ExitProtectionResolved] = {}
    for key in PROTECTION_KEYS:
        mode_attr = _MODE_FIELD[key]
        rate_attr = _RATE_FIELD[key]
        out[key] = resolve_exit_protection(
            key=key,
            system_rate=system_rates.get(key),
            user_mode=getattr(user_row, mode_attr, None) if user_row else None,
            user_rate=getattr(user_row, rate_attr, None) if user_row else None,
            account_mode=(
                getattr(account_row, mode_attr, None) if account_row else None
            ),
            account_rate=(
                getattr(account_row, rate_attr, None) if account_row else None
            ),
        )
    return out
