"""UPBIT AUTO position slot count — ownership 분리 SoT.

AUTO slot:
  AUTO-owned open holdings + AUTO ENTRY_PENDING/reservation

Account exposure/risk:
  AUTO + MANUAL + UNKNOWN 전체 (이 모듈이 약화하지 않음)

MANUAL/UNKNOWN은 AUTO slot을 소비하지 않는다.
ownership 판정 실패는 UNKNOWN 유지 (AUTO 승격 금지).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.broker.account_models import BrokerPositionSnapshotEntity
from stock_platform.trading.symbol_ownership.constants import (
    OWNER_AUTO,
    OWNER_MANUAL,
    OWNER_UNKNOWN,
)

ZERO = Decimal("0")

# max-open AUTO slot에 예약으로 포함
_AUTO_RESERVATION_SLOT_STATUSES = frozenset(
    {
        "ENTRY_PENDING",
        "RESERVED",
    }
)

REASON_AUTO_POSITION_LIMIT = "AUTO_POSITION_LIMIT_REACHED"
# compat alias (기존 로그/테스트)
REASON_MAX_OPEN_POSITIONS = "MAX_OPEN_POSITIONS_REACHED"


def count_auto_owned_open_positions(
    session: Session,
    *,
    user_broker_account_id: int,
    broker_code: str = "UPBIT",
) -> int:
    """qty>0 broker holdings 중 ownership=AUTO 인 심볼 수."""

    summary = summarize_position_ownership(
        session,
        user_broker_account_id=user_broker_account_id,
        broker_code=broker_code,
    )
    return int(summary["auto_position_count"])


def count_auto_entry_reservations(
    session: Session,
    *,
    user_broker_account_id: int,
) -> int:
    """AUTO ENTRY_PENDING/RESERVED slot 수 (orderless rollback 후 해제됨)."""

    from stock_platform.operation.upbit_full_market.entities import (
        UpbitPositionSlotEntity,
    )

    uba = int(user_broker_account_id)
    rows = list(
        session.scalars(
            select(UpbitPositionSlotEntity).where(
                UpbitPositionSlotEntity.user_broker_account_id == uba,
                UpbitPositionSlotEntity.status.in_(
                    list(_AUTO_RESERVATION_SLOT_STATUSES)
                ),
            )
        )
    )
    return len(rows)


def count_auto_slots_used(
    session: Session,
    *,
    user_broker_account_id: int,
    broker_code: str = "UPBIT",
) -> int:
    """AUTO max-position 게이트용 slot 사용량."""

    open_auto = count_auto_owned_open_positions(
        session,
        user_broker_account_id=user_broker_account_id,
        broker_code=broker_code,
    )
    reserved = count_auto_entry_reservations(
        session, user_broker_account_id=user_broker_account_id
    )
    # OPEN과 ENTRY_PENDING이 같은 심볼이면 이중 집계 방지
    # (OPEN 전환 전 ENTRY_PENDING만, OPEN 후 ENTRY_PENDING 해제 가정)
    return int(open_auto) + int(reserved)


def summarize_position_ownership(
    session: Session,
    *,
    user_broker_account_id: int,
    broker_code: str = "UPBIT",
) -> dict[str, Any]:
    """보유 ownership 요약 — AUTO slot / account total 분리 표시용."""

    from stock_platform.trading.symbol_ownership import SymbolOwnershipService
    from stock_platform.trading.symbol_ownership.constants import OWNER_FREE

    uba = int(user_broker_account_id)
    broker = str(broker_code or "UPBIT").upper()
    svc = SymbolOwnershipService(session)

    held_symbols: list[str] = []
    for row in session.scalars(
        select(BrokerPositionSnapshotEntity).where(
            BrokerPositionSnapshotEntity.user_broker_account_id == uba,
            BrokerPositionSnapshotEntity.quantity > 0,
        )
    ):
        sym = str(row.symbol or "").strip().upper()
        if sym:
            held_symbols.append(sym)

    # 심볼 중복 제거 (snapshot 중복 방어)
    held_unique = sorted(set(held_symbols))

    auto_syms: list[str] = []
    manual_syms: list[str] = []
    unknown_syms: list[str] = []
    free_syms: list[str] = []

    for sym in held_unique:
        try:
            resolved = svc.resolve(
                broker_code=broker,
                user_broker_account_id=uba,
                symbol=sym,
            )
            owner = str(resolved.owner or OWNER_UNKNOWN).upper()
        except Exception:  # noqa: BLE001 — fail-safe UNKNOWN
            owner = OWNER_UNKNOWN

        if owner == OWNER_AUTO:
            auto_syms.append(sym)
        elif owner == OWNER_MANUAL:
            manual_syms.append(sym)
        elif owner == OWNER_FREE:
            # 보유 qty>0 인데 FREE면 provenance 부족 → UNKNOWN 취급 (AUTO 승격 금지)
            unknown_syms.append(sym)
        else:
            unknown_syms.append(sym)

    reserved = count_auto_entry_reservations(
        session, user_broker_account_id=uba
    )
    auto_slots_used = len(auto_syms) + reserved

    return {
        "broker_code": broker,
        "user_broker_account_id": uba,
        "broker_held_position_count": len(held_unique),
        "auto_position_count": len(auto_syms),
        "manual_position_count": len(manual_syms),
        "unknown_position_count": len(unknown_syms),
        "auto_symbols": auto_syms,
        "manual_symbols": manual_syms,
        "unknown_symbols": unknown_syms,
        "auto_entry_reservation_count": reserved,
        "auto_slots_used": auto_slots_used,
        "account_total_holdings": len(held_unique),
        "manual_consumes_auto_slot": False,
        "unknown_consumes_auto_slot": False,
        "account_risk_includes_manual": True,
        "account_risk_includes_unknown": True,
        "count_semantics": "AUTO_OWNED_OPEN_PLUS_ENTRY_RESERVATION",
    }


def account_exposure_position_count(
    session: Session,
    *,
    user_broker_account_id: int,
) -> int:
    """Account risk용 — MANUAL/UNKNOWN 포함 전체 qty>0 보유 수."""

    uba = int(user_broker_account_id)
    rows = list(
        session.scalars(
            select(BrokerPositionSnapshotEntity.symbol).where(
                BrokerPositionSnapshotEntity.user_broker_account_id == uba,
                BrokerPositionSnapshotEntity.quantity > 0,
            )
        )
    )
    return len({str(s).upper() for s in rows if s})
