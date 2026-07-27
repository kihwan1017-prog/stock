"""STEP 11-13 — Revocation blocker checks (READ-ONLY).

strategy/runtime/order 테이블이 candidate_result를 참조하지 않으면 빈 blockers 반환.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import inspect, text
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

# READ-ONLY 조회 대상 (candidate_result_id 컬럼 존재 시에만)
_BLOCKER_TABLES: tuple[tuple[str, str, str], ...] = (
    ("strategy", "strategy_deployment", "candidate_result_id"),
    ("strategy", "strategy_runtime", "candidate_result_id"),
    ("trading", "trading_order", "candidate_result_id"),
)


def check_revocation_blockers(
    session: Session,
    *,
    candidate_id: int,
) -> dict[str, Any]:
    """
    철회 차단 사유 조회 (READ-ONLY).

    현재 스키마에 candidate_result FK가 없으면 blockers=[].
    """
    blockers: list[dict[str, Any]] = []
    bind = session.get_bind()
    if bind is None:
        return {"blocked": False, "blockers": blockers}

    inspector = inspect(bind)
    for schema, table, column in _BLOCKER_TABLES:
        try:
            if not inspector.has_table(table, schema=schema):
                continue
            columns = {
                col["name"]
                for col in inspector.get_columns(table, schema=schema)
            }
            if column not in columns:
                continue
            rows = session.execute(
                text(
                    f"""
                    SELECT COUNT(*) AS cnt
                    FROM {schema}.{table}
                    WHERE {column} = :candidate_id
                    """
                ),
                {"candidate_id": candidate_id},
            ).mappings().all()
            count = int(rows[0]["cnt"]) if rows else 0
            if count > 0:
                blockers.append(
                    {
                        "code": "REFERENCED_BY_TABLE",
                        "schema": schema,
                        "table": table,
                        "column": column,
                        "reference_count": count,
                    }
                )
        except Exception as exc:  # noqa: BLE001 — soft check
            logger.debug(
                "revocation blocker soft-check skipped %s.%s: %s",
                schema,
                table,
                exc,
            )

    return {"blocked": bool(blockers), "blockers": blockers}
