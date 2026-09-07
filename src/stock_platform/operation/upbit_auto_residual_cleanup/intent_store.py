# -*- coding: utf-8 -*-
"""Durable cleanup intent — broker submit 전 meta_json에 persist."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from stock_platform.operation.upbit_auto_residual_cleanup.constants import (
    BLOCKING_REQUEST_STATUSES,
    STATUS_AMBIGUOUS,
    STATUS_APPROVED,
    STATUS_FILLED,
    STATUS_PARTIAL_FILLED,
    STATUS_PREPARED,
    STATUS_SUBMITTED,
)
from stock_platform.risk_engine.strategy_owned_entities import (
    StrategyPositionBindingEntity,
)


INTENT_META_KEY = "controlled_cleanup_intent"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_intent(meta: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(meta, dict):
        return None
    raw = meta.get(INTENT_META_KEY)
    return dict(raw) if isinstance(raw, dict) else None


def intent_blocks_new_sell(intent: dict[str, Any] | None) -> bool:
    if not intent:
        return False
    st = str(intent.get("status") or "").upper()
    return st in BLOCKING_REQUEST_STATUSES


def persist_intent(
    session: Session,
    *,
    binding_id: int,
    uba_id: int,
    intent: dict[str, Any],
) -> StrategyPositionBindingEntity:
    """meta merge only — status/owned/PnL 불변."""

    entity = session.get(StrategyPositionBindingEntity, int(binding_id))
    if entity is None:
        raise ValueError(f"binding not found: {binding_id}")
    if int(entity.user_broker_account_id) != int(uba_id):
        raise ValueError("UBA mismatch on binding")

    meta = dict(entity.meta_json or {})
    meta[INTENT_META_KEY] = dict(intent)
    entity.meta_json = meta
    flag_modified(entity, "meta_json")
    entity.updated_at = datetime.now(timezone.utc)
    session.flush()
    return entity


def merge_cleanup_truth(
    session: Session,
    *,
    binding_id: int,
    uba_id: int,
    cleanup_block: dict[str, Any],
    residual_kind_update: str | None = None,
    residual_qty_update: str | None = None,
) -> StrategyPositionBindingEntity:
    """FILLED 확인 후 auto_residual_truth.cleanup merge."""

    entity = session.get(StrategyPositionBindingEntity, int(binding_id))
    if entity is None:
        raise ValueError(f"binding not found: {binding_id}")
    if int(entity.user_broker_account_id) != int(uba_id):
        raise ValueError("UBA mismatch on binding")

    meta = dict(entity.meta_json or {})
    truth = dict(meta.get("auto_residual_truth") or {})
    if residual_kind_update:
        truth["kind"] = residual_kind_update
    if residual_qty_update is not None:
        truth["owned_qty"] = residual_qty_update
        truth["historical_remaining_qty"] = residual_qty_update
    existing_cleanup = (
        dict(truth.get("cleanup"))
        if isinstance(truth.get("cleanup"), dict)
        else {}
    )
    existing_cleanup.update(cleanup_block)
    truth["cleanup"] = existing_cleanup
    meta["auto_residual_truth"] = truth
    # intent 상태도 동기
    intent = load_intent(meta) or {}
    intent["status"] = str(cleanup_block.get("cleanup_status") or intent.get("status"))
    intent["updated_at"] = _now_iso()
    meta[INTENT_META_KEY] = intent
    entity.meta_json = meta
    flag_modified(entity, "meta_json")
    entity.updated_at = datetime.now(timezone.utc)
    session.flush()
    return entity


__all__ = [
    "INTENT_META_KEY",
    "STATUS_AMBIGUOUS",
    "STATUS_APPROVED",
    "STATUS_FILLED",
    "STATUS_PARTIAL_FILLED",
    "STATUS_PREPARED",
    "STATUS_SUBMITTED",
    "intent_blocks_new_sell",
    "load_intent",
    "merge_cleanup_truth",
    "persist_intent",
]
