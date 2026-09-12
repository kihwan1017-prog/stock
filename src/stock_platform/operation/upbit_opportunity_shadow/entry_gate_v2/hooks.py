"""Fail-open hook — LIVE E0 path에 영향 0."""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any, Sequence

from stock_platform.operation.upbit_full_market.portfolio_entry_signal import (
    SymbolEntrySnapshot,
)

logger = logging.getLogger(__name__)


def maybe_enroll_entry_gate_v2_shadow(
    *,
    uba_id: int,
    symbol: str,
    short_ma: Decimal | None,
    long_ma: Decimal | None,
    snap: SymbolEntrySnapshot | None,
    live_e0_decision: str,
    live_e0_block_reason: str | None,
    closes: Sequence[float] | None = None,
    detail: dict[str, Any] | None = None,
    strategy_id: int | None = None,
    entry_price: Decimal | float | None = None,
) -> dict[str, Any]:
    """ma_evaluator 이후 호출 — 예외를 절대 밖으로 전파하지 않음."""

    try:
        from stock_platform.common.settings import get_settings

        if not bool(
            getattr(get_settings(), "upbit_entry_gate_v2_shadow_enabled", True)
        ):
            return {"ok": False, "reason": "DISABLED"}
        if short_ma is None or long_ma is None:
            return {"ok": False, "reason": "NO_MA"}
        closes_list = list(closes or [])
        if len(closes_list) < 20:
            # MA만으로라도 최소 feature 구성 (pre/gc는 null → 보수적 HOLD 가능)
            closes_list = [float(long_ma)] * 19 + [float(short_ma)]

        rsi14 = None
        volume_surge = None
        cand_score = None
        cand_rank = None
        selection_id = None
        if snap is not None:
            selection_id = snap.selection_id
            rsi14 = snap.rsi14
            volume_surge = snap.volume_surge
            cand_score = snap.scanner_score
            if snap.technical_metrics:
                cand_score = cand_score or snap.technical_metrics.get(
                    "candidate_score"
                ) or snap.technical_metrics.get("score")
                cand_rank = snap.technical_metrics.get(
                    "candidate_rank"
                ) or snap.technical_metrics.get("rank")
        if detail:
            rsi14 = rsi14 if rsi14 is not None else detail.get("rsi14")
            volume_surge = (
                volume_surge
                if volume_surge is not None
                else detail.get("volume_surge")
            )

        from stock_platform.database.session import get_session_factory
        from stock_platform.operation.upbit_opportunity_shadow.entry_gate_v2.service import (
            enroll_v2_shadow,
        )

        sf = get_session_factory()
        session = sf()
        try:
            return enroll_v2_shadow(
                session,
                uba_id=int(uba_id),
                symbol=str(symbol).upper(),
                live_e0_decision=live_e0_decision,
                live_e0_block_reason=live_e0_block_reason,
                short_ma=short_ma,
                long_ma=long_ma,
                closes=closes_list,
                selection_id=int(selection_id) if selection_id else None,
                strategy_id=int(strategy_id) if strategy_id else None,
                rsi14=float(rsi14) if rsi14 is not None else None,
                volume_surge=float(volume_surge) if volume_surge is not None else None,
                cand_score=float(cand_score) if cand_score is not None else None,
                cand_rank=float(cand_rank) if cand_rank is not None else None,
                entry_reference_price=entry_price,
                commit=True,
            )
        except Exception as exc:  # noqa: BLE001
            session.rollback()
            logger.warning(
                "entry_gate_v2_shadow_enroll_failed",
                extra={"error": type(exc).__name__, "uba": uba_id},
            )
            return {"ok": False, "error": type(exc).__name__}
        finally:
            session.close()
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "entry_gate_v2_shadow_hook_failed",
            extra={"error": type(exc).__name__},
        )
        return {"ok": False, "error": type(exc).__name__}
