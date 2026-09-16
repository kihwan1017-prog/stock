"""KIWOOM feed liveness vs market tick activity — 분리 판정.

connection liveness: WS task/socket/frame (PING 포함)
market activity: REAL trade tick age
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from stock_platform.trading.autotrading_health_slo import (
    AutotradingHealthSlo,
    load_autotrading_health_slo,
)

# JSON frame(PING 등) 수신 증거 — feed_max_age(30s)보다 길게 허용하지 않음
FRAME_LIVENESS_MULTIPLIER = 1.5


def _parse_iso_utc(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:  # noqa: BLE001
        return None


def _age_seconds(since: datetime | None, *, now: datetime | None = None) -> float | None:
    if since is None:
        return None
    ref = now or datetime.now(timezone.utc)
    return max(0.0, (ref - since.astimezone(timezone.utc)).total_seconds())


def evaluate_kiwoom_feed_liveness(
    runtime_status: dict[str, Any],
    *,
    slo: AutotradingHealthSlo | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """CONNECTION / MARKET / PROCESSING liveness 신호 분리."""

    slo = slo or load_autotrading_health_slo()
    ref = now or datetime.now(timezone.utc)
    client = (
        runtime_status.get("client")
        if isinstance(runtime_status.get("client"), dict)
        else {}
    )
    lifecycle = (
        client.get("lifecycle")
        if isinstance(client.get("lifecycle"), dict)
        else {}
    )

    running = bool(runtime_status.get("running"))
    connected = bool(runtime_status.get("connected"))
    reg_ack = bool(client.get("reg_ack"))
    last_error = str(client.get("last_error") or "").strip() or None

    last_frame_at = _parse_iso_utc(
        client.get("last_frame_at") or lifecycle.get("last_frame_at")
    )
    last_tick_at = _parse_iso_utc(
        client.get("last_event_at")
        or lifecycle.get("last_tick_at")
        or runtime_status.get("last_tick_at")
    )
    last_ping_at = _parse_iso_utc(
        client.get("last_ping_at") or lifecycle.get("last_ping_at")
    )

    frame_age = _age_seconds(last_frame_at, now=ref)
    tick_age = runtime_status.get("feed_age_seconds")
    if tick_age is None and last_tick_at is not None:
        tick_age = _age_seconds(last_tick_at, now=ref)

    frame_liveness_max = float(slo.feed_max_age_seconds) * FRAME_LIVENESS_MULTIPLIER

    socket_alive = running and connected and reg_ack and not last_error
    frame_recent = frame_age is not None and float(frame_age) <= frame_liveness_max
    ping_recent = ping_age is not None and float(ping_age) <= frame_liveness_max if (ping_age := _age_seconds(last_ping_at, now=ref)) else False

    # frame 또는 app-layer PING — Kiwoom JSON PING echo 경로
    connection_liveness_ok = bool(
        socket_alive and (frame_recent or ping_recent)
    )
    processing_liveness_ok = bool(
        running
        and int(client.get("frame_count") or client.get("event_count") or 0) >= 0
        and connected
    )
    market_tick_stale = False
    if tick_age is not None:
        try:
            market_tick_stale = float(tick_age) > float(slo.feed_max_age_seconds)
        except (TypeError, ValueError):
            market_tick_stale = True

    return {
        "connection_liveness_ok": connection_liveness_ok,
        "processing_liveness_ok": processing_liveness_ok,
        "market_tick_stale": market_tick_stale,
        "socket_alive": socket_alive,
        "frame_recent": frame_recent,
        "ping_recent": ping_recent,
        "last_frame_age_seconds": frame_age,
        "last_real_tick_age_seconds": tick_age,
        "last_ping_age_seconds": ping_age if last_ping_at else None,
        "frame_liveness_max_seconds": frame_liveness_max,
        "feed_max_age_seconds": float(slo.feed_max_age_seconds),
        "generation_id": runtime_status.get("generation_id") or client.get("generation_id"),
    }


def kiwoom_feed_connection_failure(
    runtime_status: dict[str, Any],
    *,
    slo: AutotradingHealthSlo | None = None,
) -> bool:
    """hard reconnect/L1 대상 — connection/task 장애."""

    lv = evaluate_kiwoom_feed_liveness(runtime_status, slo=slo)
    running = bool(runtime_status.get("running"))
    if not running:
        return True
    if not lv["socket_alive"]:
        return True
    if lv["market_tick_stale"] and not lv["connection_liveness_ok"]:
        return True
    return False


def kiwoom_feed_is_real_idle(
    runtime_status: dict[str, Any],
    *,
    slo: AutotradingHealthSlo | None = None,
) -> bool:
    """WS alive + subscribed + tick silence — 무거래 idle (장애 아님)."""

    lv = evaluate_kiwoom_feed_liveness(runtime_status, slo=slo)
    return bool(
        lv["socket_alive"]
        and lv["connection_liveness_ok"]
        and lv["market_tick_stale"]
    )
