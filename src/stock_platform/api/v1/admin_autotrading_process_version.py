"""Admin AutoTrading Process Version / Trace / Map — READ OBSERVABILITY.

Prefix: /api/v1/admin/autotrading
REAL policy mutation 없음.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy.orm import Session

from stock_platform.api.deps_admin import require_admin
from stock_platform.database.session import get_db_session
from stock_platform.operation.autotrading_process_version import service as pvs

router = APIRouter(
    prefix="/api/v1/admin/autotrading",
    tags=["Admin AutoTrading Process Version"],
    dependencies=[Depends(require_admin)],
)


@router.get("/process-versions")
def list_process_versions(
    market: str | None = Query(default=None),
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    pvs.ensure_bootstrap(session, commit=True)
    rows = pvs.list_process_versions(session, market=market)
    return {"ok": True, "items": rows, "count": len(rows)}


@router.get("/process-versions/{process_version_id}")
def get_process_version(
    process_version_id: int,
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    row = pvs.get_process_version(session, process_version_id)
    if row is None:
        raise HTTPException(status_code=404, detail="PROCESS_VERSION_NOT_FOUND")
    return {"ok": True, "item": row}


@router.get("/process-current")
def get_process_current(
    market: str = Query(default="UPBIT"),
    user_broker_account_id: int | None = Query(default=None),
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    return {
        "ok": True,
        **pvs.get_current_process(
            session, market=market, uba_id=user_broker_account_id
        ),
    }


@router.get("/process-versions/{process_version_id}/performance")
def get_process_performance(
    process_version_id: int,
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    return pvs.version_performance(session, process_version_id=process_version_id)


@router.get("/process-changes")
def list_process_changes(
    market: str | None = Query(default=None),
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    items = pvs.list_changes(session, market=market)
    return {"ok": True, "items": items, "count": len(items)}


@router.get("/process-compare")
def process_compare(
    left_id: int = Query(...),
    right_id: int = Query(...),
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    return pvs.compare_versions(session, left_id=left_id, right_id=right_id)


@router.get("/traces")
def list_traces(
    market: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    items = pvs.list_traces(session, market=market, limit=limit)
    return {"ok": True, "items": items, "count": len(items)}


@router.get("/traces/{trace_id}")
def get_trace(
    trace_id: int,
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    row = pvs.get_trace(session, trace_id)
    if row is None:
        raise HTTPException(status_code=404, detail="TRACE_NOT_FOUND")
    return {"ok": True, "item": row}


@router.post("/process-bootstrap")
def bootstrap_process(
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    """System-controlled bootstrap (idempotent). No REAL trading mutation."""
    out = pvs.ensure_bootstrap(session, commit=True)
    recon = pvs.reconstruct_today_traces(session, commit=True)
    return {"ok": True, "bootstrap": out, "reconstruct": recon}


@router.get("/process-versions/{process_version_id}/export.json")
def export_process_json(
    process_version_id: int,
    session: Session = Depends(get_db_session),
) -> dict[str, Any]:
    row = pvs.get_process_version(session, process_version_id)
    if row is None:
        raise HTTPException(status_code=404, detail="PROCESS_VERSION_NOT_FOUND")
    return {"ok": True, "export": row}


@router.get("/process-versions/{process_version_id}/export.md")
def export_process_md(
    process_version_id: int,
    session: Session = Depends(get_db_session),
) -> Response:
    row = pvs.get_process_version(session, process_version_id)
    if row is None:
        raise HTTPException(status_code=404, detail="PROCESS_VERSION_NOT_FOUND")
    lines = [
        f"# {row['version_code']} — {row['version_name']}",
        "",
        f"- market: {row['market']}",
        f"- status: {row['status']}",
        f"- git: {row.get('git_commit')}",
        f"- fingerprint: {row.get('fingerprint')}",
        "",
        "## Summary",
        str(row.get("change_summary") or ""),
        "",
        "## Reason",
        str(row.get("change_reason") or ""),
        "",
        "## Config (secrets excluded)",
        "```json",
        str(row.get("config_snapshot")),
        "```",
    ]
    return Response("\n".join(lines) + "\n", media_type="text/markdown; charset=utf-8")
