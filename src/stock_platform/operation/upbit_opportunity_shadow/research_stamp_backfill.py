"""COMPLETED shadow research stamp backfill — exit_ab / entry_ab / forward features.

기존 window/return 컬럼은 변경하지 않음 (corrupted historical data 보존).
REAL 주문/정책과 무관.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import structlog
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from stock_platform.operation.upbit_opportunity_shadow.constants import (
  SHADOW_STATUS_COMPLETED,
)
from stock_platform.operation.upbit_opportunity_shadow.entities import (
  UpbitOpportunityShadowEntity,
)
from stock_platform.operation.upbit_opportunity_shadow.evaluator import (
  UpbitOpportunityShadowEvaluator,
)

logger = structlog.get_logger(__name__)


def _missing_research_stamps(detail: dict[str, Any] | None) -> bool:
  if not isinstance(detail, dict):
    return True
  ab = detail.get("exit_ab")
  if not isinstance(ab, dict):
    return True
  baseline = ab.get("baseline")
  return not isinstance(baseline, dict)


async def backfill_missing_research_stamps(
  session: Session,
  *,
  limit: int = 100,
  now: datetime | None = None,
) -> dict[str, Any]:
  """COMPLETED 중 exit_ab.baseline 없는 row에 research stamp만 병합."""

  now_utc = now or datetime.now(timezone.utc)
  # exit_ab.baseline 누락 row만 직접 조회 (shadow_id 순 스캔 누락 방지)
  rows = list(
    session.scalars(
      select(UpbitOpportunityShadowEntity)
      .where(
        UpbitOpportunityShadowEntity.status == SHADOW_STATUS_COMPLETED,
        UpbitOpportunityShadowEntity.deleted_at.is_(None),
        or_(
          UpbitOpportunityShadowEntity.evaluation_detail.is_(None),
          UpbitOpportunityShadowEntity.evaluation_detail["exit_ab"].is_(None),
          UpbitOpportunityShadowEntity.evaluation_detail["exit_ab"]["baseline"].is_(
            None
          ),
        ),
      )
      .order_by(UpbitOpportunityShadowEntity.shadow_id.asc())
      .limit(max(1, min(500, limit)))
    )
  )
  targets = [r for r in rows if _missing_research_stamps(r.evaluation_detail)]

  evaluator = UpbitOpportunityShadowEvaluator(session, now=now_utc, allow_sync=True)
  stamped = 0
  skipped = 0
  errors: list[dict[str, Any]] = []

  for row in targets:
    try:
      computed = await evaluator._compute_payload(row)  # noqa: SLF001
      if not computed.get("ok"):
        skipped += 1
        continue
      exit_ab = computed.get("exit_ab")
      if not isinstance(exit_ab, dict) or not isinstance(
        exit_ab.get("baseline"), dict
      ):
        skipped += 1
        continue

      detail = dict(row.evaluation_detail or {})
      detail["exit_ab"] = exit_ab
      if computed.get("entry_ab") is not None:
        detail["entry_ab"] = computed.get("entry_ab")
      if computed.get("entry_forward_features") is not None:
        detail["entry_forward_features"] = computed.get("entry_forward_features")
      detail["research_stamp_backfill"] = {
        "schema": "research_stamp_backfill_v1",
        "stamped_at": now_utc.isoformat(),
        "numeric_columns_mutated": False,
        "note": "exit_ab/entry_ab/entry_forward_features only",
      }
      row.evaluation_detail = detail
      row.updated_at = now_utc
      stamped += 1
    except Exception as exc:  # noqa: BLE001
      errors.append(
        {
          "shadow_id": int(row.shadow_id or 0),
          "error": type(exc).__name__,
        }
      )

  if stamped:
    session.commit()

  return {
    "ok": True,
    "candidates": len(targets),
    "stamped": stamped,
    "skipped": skipped,
    "errors": errors,
    "orders_created": 0,
    "research_only": True,
  }
