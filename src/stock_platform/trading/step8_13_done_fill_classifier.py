"""STEP 8-13 — DONE Conflict Historical Fill 분류 (조회 전용, 상태 변경 금지)."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal
from typing import Any


CLASS_A = "ALREADY_FULLY_RECONCILED"
CLASS_B = "MISSING_ORDER_ONLY"
CLASS_C = "MISSING_EXECUTION"
CLASS_D = "POSITION_RECONCILABLE"
CLASS_E = "IMPORT_REQUIRED"
CLASS_F = "UNSAFE"

REC_SAFE_IGNORE = "SAFE_IGNORE"
REC_IMPORT = "IMPORT_REQUIRED"
REC_MANUAL = "MANUAL_REVIEW"


@dataclass(slots=True)
class FillImpact:
    position: bool
    balance: bool
    average_price: bool
    realized_pnl: bool
    daily_loss: bool
    risk: bool
    report: bool
    tax: bool
    future_sell_qty: bool

    def to_dict(self) -> dict[str, bool]:
        return asdict(self)


@dataclass(slots=True)
class DoneFillVerdict:
    conflict_id: int
    classification: str
    recommendation: str
    impact: FillImpact
    notes: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "conflict_id": self.conflict_id,
            "classification": self.classification,
            "recommendation": self.recommendation,
            "impact": self.impact.to_dict(),
            "notes": self.notes,
        }


def _dec(value: Any) -> Decimal:
    if value is None:
        return Decimal("0")
    return Decimal(str(value))


def _qty_close(left: Any, right: Any, *, tol: Decimal = Decimal("1e-8")) -> bool:
    try:
        return abs(_dec(left) - _dec(right)) <= tol
    except Exception:  # noqa: BLE001
        return False


def classify_done_fill(
    *,
    conflict_id: int,
    executed_volume: Any,
    trades_count: int,
    has_internal_order: bool,
    has_internal_execution: bool,
    execution_qty_matches_trades: bool,
    broker_balance_known: bool,
    internal_position_known: bool,
    position_matches_broker: bool,
    snapshot_synced_from_broker: bool,
    remote_status: str | None,
) -> DoneFillVerdict:
    """DONE 체결 정합성 분류 — Import/Ignore 수행 없음."""

    exec_v = _dec(executed_volume)
    status = str(remote_status or "").lower()
    notes: list[str] = []

    # 영향도: 체결>0이면 이력·리포트·세금에는 원칙적으로 영향 가능
    has_fill = exec_v > 0 or trades_count > 0
    impact = FillImpact(
        position=has_fill and not position_matches_broker,
        balance=has_fill and not position_matches_broker,
        average_price=has_fill and not has_internal_execution,
        realized_pnl=has_fill and not has_internal_execution,
        daily_loss=False,  # 과거 DONE — 당일 모니터링 재계산 대상 아님(보수적)
        risk=has_fill and not position_matches_broker,
        report=has_fill and not has_internal_order,
        tax=has_fill and not has_internal_order,
        future_sell_qty=has_fill and not position_matches_broker,
    )

    if status and status != "done":
        notes.append(f"remote_status_unexpected:{status}")
        return DoneFillVerdict(
            conflict_id=conflict_id,
            classification=CLASS_F,
            recommendation=REC_MANUAL,
            impact=impact,
            notes="; ".join(notes),
        )

    if has_internal_order and has_internal_execution and execution_qty_matches_trades:
        notes.append("internal_order_and_executions_match_broker_trades")
        impact = FillImpact(
            position=False,
            balance=False,
            average_price=False,
            realized_pnl=False,
            daily_loss=False,
            risk=False,
            report=False,
            tax=False,
            future_sell_qty=False,
        )
        return DoneFillVerdict(
            conflict_id=conflict_id,
            classification=CLASS_A,
            recommendation=REC_SAFE_IGNORE,
            impact=impact,
            notes="; ".join(notes),
        )

    if has_internal_execution and not has_internal_order:
        notes.append("executions_without_order")
        return DoneFillVerdict(
            conflict_id=conflict_id,
            classification=CLASS_B,
            recommendation=REC_MANUAL,
            impact=impact,
            notes="; ".join(notes),
        )

    if has_internal_order and not has_internal_execution:
        notes.append("order_without_execution")
        return DoneFillVerdict(
            conflict_id=conflict_id,
            classification=CLASS_C,
            recommendation=REC_IMPORT,
            impact=impact,
            notes="; ".join(notes),
        )

    if has_internal_order and has_internal_execution and not execution_qty_matches_trades:
        notes.append("execution_qty_mismatch")
        return DoneFillVerdict(
            conflict_id=conflict_id,
            classification=CLASS_C,
            recommendation=REC_MANUAL,
            impact=impact,
            notes="; ".join(notes),
        )

    # Order/Execution 모두 없음
    if not broker_balance_known or not internal_position_known:
        notes.append("cannot_compare_position_or_balance")
        return DoneFillVerdict(
            conflict_id=conflict_id,
            classification=CLASS_F,
            recommendation=REC_MANUAL,
            impact=impact,
            notes="; ".join(notes),
        )

    if position_matches_broker and snapshot_synced_from_broker:
        notes.append(
            "no_internal_order_history; current_position_matches_broker_snapshot"
        )
        # 현재 거래 상태 OK — Conflict Ignore 후보이나 이력 Import는 별도 승인
        impact = FillImpact(
            position=False,
            balance=False,
            average_price=True,  # 내부 평균단가 이력 부재
            realized_pnl=True,  # 내부 실현손익 이력 부재
            daily_loss=False,
            risk=False,
            report=True,
            tax=True,
            future_sell_qty=False,
        )
        return DoneFillVerdict(
            conflict_id=conflict_id,
            classification=CLASS_D,
            recommendation=REC_SAFE_IGNORE,
            impact=impact,
            notes="; ".join(notes),
        )

    if not position_matches_broker:
        notes.append("position_or_balance_mismatch_requires_import_or_review")
        return DoneFillVerdict(
            conflict_id=conflict_id,
            classification=CLASS_E,
            recommendation=REC_IMPORT,
            impact=impact,
            notes="; ".join(notes),
        )

    notes.append("ambiguous_without_history")
    return DoneFillVerdict(
        conflict_id=conflict_id,
        classification=CLASS_F,
        recommendation=REC_MANUAL,
        impact=impact,
        notes="; ".join(notes),
    )
