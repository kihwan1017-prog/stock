"""STEP 11-6 — Entity/Symbol 해석 (AI 반환값 자동 신뢰 금지)."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.disclosure.models import DartCorp


def resolve_entities(
    session: Session,
    *,
    document_type: str,
    source_symbols: list[dict[str, Any]] | None,
    source_corp_code: str | None,
    source_stock_code: str | None,
    ai_symbols: list[str] | None,
    ai_entities: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """
    우선순위:
    1) 원본 연결
    2) DART corp↔stock
    3) AI 반환은 보조만
    """

    resolved: list[dict[str, Any]] = []
    unmatched: list[str] = []
    unresolved: list[dict[str, Any]] = []

    for item in source_symbols or []:
        resolved.append(
            {
                "entity_type": "SYMBOL",
                "entity_code": item.get("symbol"),
                "entity_name": item.get("symbol"),
                "source": "SOURCE_LINK",
                "market_code": item.get("market_code"),
            }
        )

    if source_corp_code:
        corp = session.get(DartCorp, source_corp_code)
        resolved.append(
            {
                "entity_type": "COMPANY",
                "entity_code": source_corp_code,
                "entity_name": corp.corp_name if corp else source_corp_code,
                "source": "SOURCE_CORP",
                "stock_code": (
                    corp.stock_code if corp else source_stock_code
                ),
            }
        )

    if source_stock_code and not any(
        r.get("entity_code") == source_stock_code for r in resolved
    ):
        # DART 역매핑 시도
        corp = session.scalar(
            select(DartCorp).where(DartCorp.stock_code == source_stock_code)
        )
        resolved.append(
            {
                "entity_type": "SYMBOL",
                "entity_code": source_stock_code,
                "entity_name": corp.corp_name if corp else source_stock_code,
                "source": "SOURCE_STOCK" if not corp else "DART_MAP",
            }
        )

    known = {str(r.get("entity_code") or "").upper() for r in resolved}
    for sym in ai_symbols or []:
        s = str(sym).strip().upper()
        if not s:
            continue
        if s in known:
            continue
        # AI만 제시 → unmatched (자동 Master 생성 금지)
        unmatched.append(s)
        unresolved.append(
            {
                "entity_type": "SYMBOL",
                "entity_name": s,
                "source": "AI_SUGGESTION",
                "status": "UNRESOLVED",
            }
        )

    for ent in ai_entities or []:
        code = str(ent.get("code") or "").strip().upper()
        name = str(ent.get("name") or "").strip()
        if code and code in known:
            continue
        unresolved.append(
            {
                "entity_type": ent.get("type") or "ENTITY",
                "entity_code": code or None,
                "entity_name": name or code or "unknown",
                "source": "AI_SUGGESTION",
                "status": "UNRESOLVED",
            }
        )

    return {
        "resolved_entities": resolved,
        "unmatched_symbols": unmatched,
        "unresolved_entities": unresolved,
        "document_type": document_type,
    }
