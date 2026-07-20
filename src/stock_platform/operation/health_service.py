from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx
from sqlalchemy import text

from stock_platform.common.settings import get_settings


@dataclass(frozen=True, slots=True)
class ComponentHealth:
    name: str
    status: str
    detail: dict[str, Any]


def _safe_message(exc: Exception) -> str:
    text_value = str(exc)
    if len(text_value) > 200:
        return text_value[:200] + "..."
    return text_value


def check_database() -> dict[str, Any]:
    try:
        from stock_platform.database.session import get_engine

        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"status": "UP"}
    except Exception as ex:
        return {"status": "DOWN", "message": _safe_message(ex)}


def check_ollama() -> dict[str, Any]:
    settings = get_settings()
    try:
        response = httpx.get(
            f"{settings.ollama_base_url.rstrip('/')}/api/tags",
            timeout=3.0,
        )
        response.raise_for_status()
        models = response.json().get("models", [])
        return {
            "status": "UP",
            "model_count": len(models),
        }
    except Exception as ex:
        return {"status": "DOWN", "message": _safe_message(ex)}


def check_http_endpoint(
    *,
    name: str,
    url: str,
    timeout_seconds: float = 3.0,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    try:
        response = httpx.get(
            url,
            timeout=timeout_seconds,
            headers=headers or {},
        )
        if response.status_code >= 500:
            return {
                "status": "DOWN",
                "message": f"HTTP {response.status_code}",
            }
        return {
            "status": "UP",
            "http_status": response.status_code,
        }
    except Exception as ex:
        return {
            "status": "DOWN",
            "message": _safe_message(ex),
        }


class SystemHealthService:
    """운영용 통합 헬스 집계."""

    async def build(self) -> dict[str, Any]:
        settings = get_settings()
        components: dict[str, Any] = {
            "database": check_database(),
            "ollama": check_ollama(),
            "upbit_rest": check_http_endpoint(
                name="upbit_rest",
                url=(
                    f"{settings.upbit_base_url.rstrip('/')}"
                    "/v1/market/all?isDetails=false"
                ),
                timeout_seconds=settings.upbit_timeout_seconds,
            ),
            "dart": (
                check_http_endpoint(
                    name="dart",
                    url=(
                        f"{settings.dart_base_url.rstrip('/')}"
                        f"/corpCode.xml?crtfc_key={settings.dart_api_key}"
                    ),
                    timeout_seconds=min(
                        5.0,
                        settings.dart_timeout_seconds,
                    ),
                )
                if settings.dart_api_key.strip()
                else {
                    "status": "SKIPPED",
                    "message": "DART API key not configured",
                }
            ),
            "news": (
                {
                    "status": "CONFIGURED",
                    "message": "Naver news credentials present",
                }
                if (
                    settings.naver_client_id.strip()
                    and settings.naver_client_secret.strip()
                )
                else {
                    "status": "SKIPPED",
                    "message": "Naver news credentials missing",
                }
            ),
            "kiwoom_rest": (
                {
                    "status": "CONFIGURED",
                    "use_mock": settings.kiwoom_use_mock,
                    "live_order_enabled": (
                        settings.kiwoom_live_order_enabled
                    ),
                }
                if settings.kiwoom_app_key.strip()
                else {
                    "status": "SKIPPED",
                    "message": "Kiwoom credentials missing",
                }
            ),
            "kiwoom_websocket": {
                "status": (
                    "CONFIGURED"
                    if (
                        settings.kiwoom_ws_url.strip()
                        or settings.kiwoom_order_ws_url.strip()
                    )
                    else "SKIPPED"
                ),
            },
            "scheduler": {
                "status": (
                    "UP"
                    if settings.scheduler_enabled
                    else "DISABLED"
                ),
            },
            "live_trading": {
                "status": (
                    "ENABLED"
                    if settings.kiwoom_live_order_enabled
                    else "DISABLED"
                ),
                "live_order_enabled": (
                    settings.kiwoom_live_order_enabled
                ),
            },
        }

        try:
            from stock_platform.realtime.manager import (
                realtime_manager,
            )
            from stock_platform.realtime.persistence import (
                market_data_persistence_worker,
            )

            components["realtime"] = await realtime_manager.status()
            components["queue"] = (
                market_data_persistence_worker.status()
            )
        except Exception as ex:
            components["realtime"] = {
                "status": "DOWN",
                "message": _safe_message(ex),
            }
            components["queue"] = {
                "status": "DOWN",
                "message": _safe_message(ex),
            }

        try:
            from stock_platform.realtime.cache import (
                realtime_quote_cache,
            )

            components["market_data_freshness"] = (
                await realtime_quote_cache.health()
            )
        except Exception:
            components["market_data_freshness"] = {
                "status": "UNKNOWN",
            }

        overall = "UP"
        for item in components.values():
            status = str(
                item.get("status", "")
                if isinstance(item, dict)
                else ""
            ).upper()
            if status in {"DOWN", "ERROR", "FAILED"}:
                overall = "DEGRADED"
                break
            if status in {"DEGRADED"} and overall == "UP":
                overall = "DEGRADED"

        return {
            "status": overall,
            "checked_at": datetime.now(timezone.utc),
            "components": components,
        }
