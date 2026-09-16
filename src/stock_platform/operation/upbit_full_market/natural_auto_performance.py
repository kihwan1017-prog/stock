"""NATURAL AUTO 성과 윈도우 — Daily/7D/30D (Smoke/Test 분리)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.order.entities import TradingOrderEntity

KST = ZoneInfo("Asia/Seoul")
ZERO = Decimal("0")

# 성과에서 제외할 태그 (metadata)
_TEST_TAGS = frozenset(
    {
        "REAL_E2E_SMOKE",
        "REAL_E2E_SMOKE_5500",
        "SMOKE",
        "E2E_TEST",
        "MANUAL_TEST",
    }
)


def _is_natural_auto(meta: dict[str, Any] | None) -> bool:
    if not isinstance(meta, dict):
        return True
    source = str(meta.get("order_source") or "AUTO").upper()
    if source not in {"AUTO", ""}:
        return False
    tag = str(
        meta.get("test_tag")
        or meta.get("smoke_tag")
        or meta.get("wrk_tag")
        or meta.get("tag")
        or ""
    ).upper()
    for t in _TEST_TAGS:
        if t in tag:
            return False
    env = str(meta.get("environment") or "LIVE").upper()
    return env in {"LIVE", ""}


def _order_provenance(meta: dict[str, Any] | None) -> str:
    if not isinstance(meta, dict):
        return "UNKNOWN"
    if not _is_natural_auto(meta):
        src = str(meta.get("order_source") or "").upper()
        if src == "MANUAL":
            return "MANUAL"
        tag = str(
            meta.get("test_tag")
            or meta.get("smoke_tag")
            or meta.get("wrk_tag")
            or meta.get("tag")
            or ""
        ).upper()
        if any(t in tag for t in _TEST_TAGS):
            return "TEST"
        if src and src != "AUTO":
            return "MANUAL"
        return "TEST"
    return "NATURAL_AUTO"


def build_natural_auto_performance_windows(
    session: Session,
    *,
    user_broker_account_id: int,
    now: datetime | None = None,
) -> dict[str, Any]:
    """TODAY / 7D / 30D NATURAL_AUTO 요약 (READ-ONLY)."""

    uba = int(user_broker_account_id)
    now_utc = now or datetime.now(timezone.utc)
    if now_utc.tzinfo is None:
        now_utc = now_utc.replace(tzinfo=timezone.utc)

    windows = {
        "TODAY": _kst_today_start(now_utc),
        "7D": now_utc - timedelta(days=7),
        "30D": now_utc - timedelta(days=30),
    }
    out: dict[str, Any] = {}
    for name, start in windows.items():
        out[name] = _window_stats(
            session, uba_id=uba, start_utc=start, end_utc=now_utc
        )
    out["as_of"] = now_utc.isoformat()
    out["provenance_default"] = "NATURAL_AUTO"
    return out


def _kst_today_start(now_utc: datetime) -> datetime:
    kst = now_utc.astimezone(KST)
    start_kst = kst.replace(hour=0, minute=0, second=0, microsecond=0)
    return start_kst.astimezone(timezone.utc)


def _window_stats(
    session: Session,
    *,
    uba_id: int,
    start_utc: datetime,
    end_utc: datetime,
) -> dict[str, Any]:
    rows = list(
        session.scalars(
            select(TradingOrderEntity).where(
                TradingOrderEntity.user_broker_account_id == uba_id,
                TradingOrderEntity.broker_code == "UPBIT",
                TradingOrderEntity.created_at >= start_utc,
                TradingOrderEntity.created_at < end_utc,
            )
        )
    )
    buys = sells = 0
    fees = ZERO
    natural_buys = natural_sells = 0
    test_buys = 0
    for o in rows:
        meta = o.metadata_payload if isinstance(o.metadata_payload, dict) else {}
        if str(meta.get("order_source") or "").upper() not in {"AUTO", ""}:
            continue
        side = str(o.side_code or "").upper()
        prov = _order_provenance(meta)
        filled = Decimal(str(o.filled_quantity or 0))
        if filled <= ZERO and str(o.status_code or "").upper() not in {
            "FILLED",
            "PARTIALLY_FILLED",
        }:
            continue
        fee = Decimal(str(getattr(o, "fee_amount", None) or 0))
        if fee <= ZERO:
            # paid_fee / commission 대체
            fee = Decimal(
                str(
                    meta.get("paid_fee")
                    or meta.get("fee")
                    or 0
                )
            )
        if prov == "NATURAL_AUTO":
            if side == "BUY":
                natural_buys += 1
            elif side == "SELL":
                natural_sells += 1
            fees += fee
        elif prov == "TEST":
            if side == "BUY":
                test_buys += 1
        if side == "BUY":
            buys += 1
        elif side == "SELL":
            sells += 1

    round_trips = min(natural_buys, natural_sells)
    return {
        "auto_buy_count": natural_buys,
        "auto_sell_count": natural_sells,
        "round_trips": round_trips,
        "fees": str(fees),
        "test_buy_count": test_buys,
        "all_auto_buy_count": buys,
        "all_auto_sell_count": sells,
        "sample_note": (
            "PnL/win-rate는 performance service 연계; "
            "여기선 체결 건수·fee·RT 근사"
        ),
    }
