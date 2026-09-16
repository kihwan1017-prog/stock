"""Waiting lifecycle shadow hooks — fail-open toward REAL trading."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import structlog

from stock_platform.operation.upbit_opportunity_shadow.waiting_lifecycle_shadow.service import (
    enroll_waiting_opportunity,
    observe_evaluation,
    observe_full_slot_block,
    observe_real_stage,
    shadow_enabled,
    tick_active_observations,
)

logger = structlog.get_logger(__name__)


def on_waiting_slot_assigned(
    session: Any,
    *,
    user_broker_account_id: int,
    symbol: str,
    selection_id: int,
    waiting_created_at: datetime | None = None,
    candidate_id: int | None = None,
    strategy_id: int | None = None,
    deployment_id: int | None = None,
    slot_id: int | None = None,
    initial_score: float | None = None,
) -> dict[str, Any]:
    if not shadow_enabled():
        return {"ok": False, "reason": "DISABLED"}
    try:
        from datetime import timezone

        started = waiting_created_at or datetime.now(timezone.utc)
        return enroll_waiting_opportunity(
            session,
            user_broker_account_id=user_broker_account_id,
            symbol=symbol,
            selection_id=int(selection_id),
            waiting_created_at=started,
            candidate_id=candidate_id,
            strategy_id=strategy_id,
            deployment_id=deployment_id,
            slot_id=slot_id,
            initial_score=initial_score,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "waiting_lifecycle_shadow_enroll_failed",
            selection_id=selection_id,
            error=str(exc)[:200],
        )
        return {"ok": False, "error": str(exc)[:200]}


def on_waiting_revalidated(
    session: Any,
    *,
    user_broker_account_id: int,
    assessments: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if not shadow_enabled():
        return {"ok": False, "reason": "DISABLED"}
    try:
        updated = 0
        for a in assessments or []:
            if a.get("skipped"):
                continue
            sel = a.get("selection_id")
            # assessments may lack selection_id — resolve via symbol+uba later optional
            if sel is None and a.get("slot_id") is not None:
                try:
                    from stock_platform.operation.upbit_full_market.entities import (
                        UpbitPositionSlotEntity,
                    )

                    slot = session.get(
                        UpbitPositionSlotEntity, int(a["slot_id"])
                    )
                    if slot is not None and slot.candidate_selection_id:
                        sel = int(slot.candidate_selection_id)
                except Exception:  # noqa: BLE001
                    sel = None
            if sel is None:
                continue
            observe_evaluation(
                session,
                user_broker_account_id=user_broker_account_id,
                symbol=str(a.get("symbol") or ""),
                selection_id=int(sel),
                decision=a.get("last_decision"),
                block_reason=a.get("last_block_reason"),
            )
            updated += 1
        tick_active_observations(
            session, user_broker_account_id=user_broker_account_id
        )
        return {"ok": True, "updated": updated}
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "waiting_lifecycle_shadow_revalidate_failed",
            error=str(exc)[:200],
        )
        return {"ok": False, "error": str(exc)[:200]}


def on_full_slot_or_no_waiting(
    session: Any,
    *,
    user_broker_account_id: int,
    symbol: str,
    selection_id: int | None = None,
    score: float | None = None,
    reason_code: str | None = None,
) -> dict[str, Any]:
    if not shadow_enabled():
        return {"ok": False, "reason": "DISABLED"}
    try:
        return observe_full_slot_block(
            session,
            user_broker_account_id=user_broker_account_id,
            symbol=symbol,
            selection_id=selection_id,
            score=score,
            reason_code=reason_code,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "waiting_lifecycle_shadow_full_slot_failed",
            error=str(exc)[:200],
        )
        return {"ok": False, "error": str(exc)[:200]}


def on_real_entry_stage(
    session: Any,
    *,
    user_broker_account_id: int,
    symbol: str,
    selection_id: int | None,
    stage: str,
) -> dict[str, Any]:
    if not shadow_enabled():
        return {"ok": False, "reason": "DISABLED"}
    try:
        return observe_real_stage(
            session,
            user_broker_account_id=user_broker_account_id,
            symbol=symbol,
            selection_id=selection_id,
            stage=stage,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "waiting_lifecycle_shadow_stage_failed",
            stage=stage,
            error=str(exc)[:200],
        )
        return {"ok": False, "error": str(exc)[:200]}
