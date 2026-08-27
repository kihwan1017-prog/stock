"""Entry signal shadow summary — Admin / Assistant READ ONLY."""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from stock_platform.operation.upbit_opportunity_shadow.entry_signal_shadow.constants import (
    ALL_VARIANTS,
    FORWARD_SAMPLE_TARGET,
    SOURCE_FORWARD,
    VARIANT_E0,
)
from stock_platform.operation.upbit_opportunity_shadow.entry_signal_shadow.replay import (
    run_historical_replay,
)
from stock_platform.operation.upbit_opportunity_shadow.entry_signal_shadow.service import (
    forward_collection_status,
)
from stock_platform.operation.upbit_opportunity_shadow.entry_signal_shadow.variants import (
    VARIANT_SPECS,
)


def summarize_entry_signal_shadow(
    session: Session,
    *,
    user_broker_account_id: int = 1380,
    include_replay: bool = True,
) -> dict[str, Any]:
    """Canonical research panel payload."""

    uba = int(user_broker_account_id)
    fwd = forward_collection_status(session, uba_id=uba)

    # block attribution from forward E0 rows
    blocks = session.execute(
        text(
            """
            SELECT baseline_block_reason AS reason, COUNT(*) AS n
            FROM operation.upbit_entry_signal_shadow
            WHERE user_broker_account_id = :uba
              AND source = :src AND variant = 'E0'
            GROUP BY baseline_block_reason
            """
        ),
        {"uba": uba, "src": SOURCE_FORWARD},
    ).mappings().all()
    block_panel = {
        (r["reason"] or "PASS"): int(r["n"]) for r in blocks
    }

    variant_panel: dict[str, Any] = {}
    for code in ALL_VARIANTS:
        row = session.execute(
            text(
                """
                SELECT
                  COUNT(*) AS samples,
                  COUNT(*) FILTER (WHERE shadow_decision = 'PASS') AS entries,
                  COUNT(*) FILTER (
                    WHERE outcome_status = 'COMPLETED' AND net_return_15m_pct > 0
                  ) AS wins,
                  COUNT(*) FILTER (
                    WHERE outcome_status = 'COMPLETED' AND net_return_15m_pct <= 0
                  ) AS losses,
                  AVG(net_return_15m_pct) FILTER (
                    WHERE outcome_status = 'COMPLETED'
                  ) AS avg_net,
                  AVG(mfe_pct) FILTER (WHERE outcome_status = 'COMPLETED') AS avg_mfe,
                  AVG(mae_pct) FILTER (WHERE outcome_status = 'COMPLETED') AS avg_mae
                FROM operation.upbit_entry_signal_shadow
                WHERE user_broker_account_id = :uba
                  AND source = :src AND variant = :var
                """
            ),
            {"uba": uba, "src": SOURCE_FORWARD, "var": code},
        ).mappings().first()
        samples = int((row or {}).get("samples") or 0)
        entries = int((row or {}).get("entries") or 0)
        wins = int((row or {}).get("wins") or 0)
        losses = int((row or {}).get("losses") or 0)
        decided = wins + losses
        variant_panel[code] = {
            "description": VARIANT_SPECS[code].description,
            "SAMPLES": samples,
            "ENTRIES": entries,
            "ENTRY_RATE": round(entries / samples, 4) if samples else 0.0,
            "WIN_RATE": round(wins / decided, 4) if decided else None,
            "NET_AVG_15M": (
                float(row["avg_net"]) if row and row.get("avg_net") is not None else None
            ),
            "AVG_MFE": (
                float(row["avg_mfe"]) if row and row.get("avg_mfe") is not None else None
            ),
            "AVG_MAE": (
                float(row["avg_mae"]) if row and row.get("avg_mae") is not None else None
            ),
            "STATUS": "COLLECTING",
            "REAL_APPLIED": False,
        }

    replay = None
    if include_replay:
        try:
            replay = run_historical_replay(session, uba_id=uba, limit=500)
        except Exception as exc:  # noqa: BLE001
            replay = {"ok": False, "error": type(exc).__name__}

    return {
        "schema": "upbit_entry_signal_shadow_v1",
        "market": "UPBIT",
        "research_only": True,
        "REAL_ENTRY_POLICY": "PORTFOLIO_BULLISH / E0",
        "REAL_ENTRY_POLICY_CHANGED": False,
        "REAL_APPLIED_VARIANT": None,
        "variants": variant_panel,
        "block_reasons": block_panel,
        "forward": fwd,
        "replay": replay,
        "assistant_hints": {
            "why_no_buy_today": (
                "E0 blocks dominate: SHORT_MA / MA_SEPARATION / RSI / "
                "SIGNAL_EMIT_SUPPRESSED — see block_reasons"
            ),
            "promotion": "FORBIDDEN in this STEP — collect ≥100 forward samples first",
        },
        "target_forward_samples": FORWARD_SAMPLE_TARGET,
        "e0_code": VARIANT_E0,
    }


def list_entry_signal_shadow_rows(
    session: Session,
    *,
    user_broker_account_id: int = 1380,
    limit: int = 50,
) -> dict[str, Any]:
    rows = session.execute(
        text(
            """
            SELECT shadow_id, symbol, observed_at, variant, source,
                   baseline_decision, baseline_block_reason,
                   shadow_decision, shadow_block_reason,
                   outcome_status, net_return_15m_pct, mfe_pct, mae_pct
            FROM operation.upbit_entry_signal_shadow
            WHERE user_broker_account_id = :uba
            ORDER BY observed_at DESC, shadow_id DESC
            LIMIT :lim
            """
        ),
        {"uba": int(user_broker_account_id), "lim": int(limit)},
    ).mappings().all()
    return {
        "ok": True,
        "count": len(rows),
        "rows": [dict(r) for r in rows],
    }
