"""AUTO / MANUAL / TEST provenance — AUTO 알림만 AUTO category에 포함."""

from __future__ import annotations

from typing import Any

_AUTO_MARKERS = frozenset(
    {
        "AUTO",
        "AUTOTRADING",
        "FULL_MARKET",
        "PORTFOLIO",
        "STRATEGY",
        "NATURAL_AUTO",
        "OPPORTUNITY",
    }
)
_MANUAL_MARKERS = frozenset({"MANUAL", "USER", "BROKER_MANUAL"})
_TEST_MARKERS = frozenset(
    {
        "TEST",
        "SMOKE",
        "LIVE_SMOKE",
        "E2E",
        "DRY_RUN",
        "PAPER_SMOKE",
    }
)


def _collect_tags(detail: dict[str, Any] | None) -> set[str]:
    d = detail or {}
    out: set[str] = set()
    for key in (
        "order_source",
        "provenance",
        "trade_provenance",
        "source",
        "actor",
        "execution_mode",
        "smoke_tag",
        "test_tag",
    ):
        val = d.get(key)
        if val is None:
            continue
        out.add(str(val).strip().upper())
    tags = d.get("tags") or d.get("provenance_tags")
    if isinstance(tags, (list, tuple, set)):
        for t in tags:
            out.add(str(t).strip().upper())
    if d.get("is_smoke") or d.get("is_test") or d.get("live_smoke"):
        out.add("SMOKE")
    if d.get("is_manual"):
        out.add("MANUAL")
    return {x for x in out if x}


def classify_trade_provenance(
    detail: dict[str, Any] | None,
) -> str:
    """AUTO | MANUAL | TEST | UNKNOWN"""

    tags = _collect_tags(detail)
    if tags & _TEST_MARKERS:
        return "TEST"
    d = detail or {}
    # 기존 ownership SoT 재사용
    try:
        from stock_platform.order.order_ownership import is_local_auto_provenance

        if is_local_auto_provenance(
            strategy_id=d.get("strategy_id"),
            strategy_deployment_id=d.get("strategy_deployment_id")
            or d.get("deployment_id"),
            metadata_payload=d.get("metadata_payload")
            if isinstance(d.get("metadata_payload"), dict)
            else d,
            order_source=d.get("order_source") or d.get("provenance"),
        ):
            if not (tags & _MANUAL_MARKERS):
                return "AUTO"
    except Exception:  # noqa: BLE001
        pass
    if tags & _MANUAL_MARKERS and not (tags & _AUTO_MARKERS):
        return "MANUAL"
    if tags & _AUTO_MARKERS:
        return "AUTO"
    if d.get("strategy_id") or d.get("portfolio_slot") or d.get("auto_slot"):
        if not (tags & _MANUAL_MARKERS):
            return "AUTO"
    return "UNKNOWN"


def allow_auto_trade_alert(detail: dict[str, Any] | None) -> bool:
    """AUTO BUY/SELL Telegram 허용 여부. MANUAL/TEST/UNKNOWN 제외."""

    return classify_trade_provenance(detail) == "AUTO"
