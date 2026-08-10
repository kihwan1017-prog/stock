"""AI Signal Gate 환경별 활성 판정 — LIVE Gate 기본 OFF."""

from __future__ import annotations

from typing import Any

from stock_platform.common.settings import get_settings


def is_ai_signal_gate_active(
    environment: str,
    *,
    settings: Any | None = None,
) -> bool:
    """Paper/MOCK/Shadow에서만 Gate ON 가능. LIVE는 별도 플래그 필요."""

    cfg = settings or get_settings()
    if not bool(getattr(cfg, "autotrading_ai_signal_gate_enabled", False)):
        return False

    env = str(environment or "").strip().upper()
    if env in {"PAPER", "MOCK"}:
        return True

    if env == "LIVE":
        # LIVE Shadow / Dry-Run은 Shadow Gate 정책
        try:
            from stock_platform.order.live_dry_run import is_live_dry_run_mode
            from stock_platform.order.live_shadow import is_live_shadow_mode

            if is_live_shadow_mode() or is_live_dry_run_mode():
                return bool(
                    getattr(
                        cfg,
                        "autotrading_ai_signal_gate_shadow_enabled",
                        True,
                    )
                )
        except Exception:  # noqa: BLE001
            pass
        return bool(
            getattr(cfg, "autotrading_ai_signal_gate_live_enabled", False)
        )

    return False
