"""Heuristic vs TRADING_LLM SHADOW outcome comparison — RESEARCH ONLY.

CLEAN Forward 규칙 재사용. 미래 데이터를 판단 입력에 넣지 않는다.
자동 REAL 승격 없음.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.operation.upbit_market_context.entities import (
    UpbitLlmContextAnalysisEntity,
)
from stock_platform.operation.upbit_opportunity_shadow.clean_forward_research import (
    TARGET_CLEAN_MIN,
    assign_clean_forward_obs,
    classify_forward_row,
)
from stock_platform.operation.upbit_opportunity_shadow.constants import (
    SHADOW_STATUS_COMPLETED,
)
from stock_platform.operation.upbit_opportunity_shadow.entities import (
    UpbitOpportunityShadowEntity,
)
from stock_platform.operation.upbit_opportunity_shadow.entry_quality_early_dump_experiment import (
    N_COLLECTION,
    sample_gate,
)


def promotion_status(clean_n: int) -> dict[str, Any]:
    if clean_n < N_COLLECTION:
        status = "COLLECTION_ONLY"
        ko = "수집 전용 — REAL 승격 근거 아님"
    elif clean_n < TARGET_CLEAN_MIN:
        status = "RESEARCH_ONLY"
        ko = "연구 전용 — 표본 부족"
    else:
        status = "PROMOTION_REVIEW_ELIGIBLE"
        ko = "승격 검토 가능 — 자동 승격 없음, 사용자 승인 필요"
    return {
        "clean_sample_count": clean_n,
        "promotion_status": status,
        "promotion_status_ko": ko,
        "auto_promote": False,
        "sample_gate": sample_gate(clean_n),
        "targets": {"collection": N_COLLECTION, "primary": TARGET_CLEAN_MIN},
    }


def _pnl(obs: Any) -> float:
    try:
        return float((obs.outcome or {}).get("net_pnl_krw") or 0.0)
    except (TypeError, ValueError):
        return 0.0


def build_heuristic_vs_llm_shadow(session: Session) -> dict[str, Any]:
    """COMPLETED shadow + dual LLM rows → SHADOW outcome KPI."""

    completed = list(
        session.scalars(
            select(UpbitOpportunityShadowEntity).where(
                UpbitOpportunityShadowEntity.deleted_at.is_(None),
                UpbitOpportunityShadowEntity.status == SHADOW_STATUS_COMPLETED,
            )
        )
    )
    clean_obs = assign_clean_forward_obs(completed)
    clean_ids = {int(o.shadow_id) for o in clean_obs}
    by_id = {int(r.shadow_id): r for r in completed}

    analyses = list(
        session.scalars(
            select(UpbitLlmContextAnalysisEntity).where(
                UpbitLlmContextAnalysisEntity.shadow_id.is_not(None)
            )
        )
    )
    dual_rows: list[dict[str, Any]] = []
    for a in analyses:
        out = a.output_json if isinstance(a.output_json, dict) else {}
        if out.get("schema_version") != "upbit_dual_llm_shadow_v1":
            # 구 heuristic-only row — 비교 표본에서 제외 (혼동 방지)
            continue
        sid = int(a.shadow_id) if a.shadow_id is not None else 0
        if sid not in clean_ids:
            continue
        row = by_id.get(sid)
        if row is None:
            continue
        cls = classify_forward_row(row)
        if not cls.get("clean"):
            continue
        heur = out.get("current_heuristic") or {}
        shadow = out.get("trading_llm_shadow") or {}
        obs = next((o for o in clean_obs if int(o.shadow_id) == sid), None)
        if obs is None:
            continue
        dual_rows.append(
            {
                "shadow_id": sid,
                "symbol": row.symbol,
                "analysis_id": int(a.analysis_id),
                "heuristic_rec": heur.get("recommendation"),
                "llm_rec": shadow.get("recommendation") if shadow.get("ok") else None,
                "llm_ok": bool(shadow.get("ok")),
                "early_dump_risk": shadow.get("early_dump_risk"),
                "early_dump_actual": bool(obs.early_dump),
                "net_pnl_krw": _pnl(obs),
                "mfe_pct": obs.mfe_pct,
                "mae_pct": obs.mae_pct,
                "return_5m_pct": getattr(row, "return_5m_pct", None),
                "return_15m_pct": getattr(row, "return_15m_pct", None),
                "return_30m_pct": getattr(row, "return_30m_pct", None),
                "return_60m_pct": getattr(row, "return_60m_pct", None),
            }
        )

    def arm_kpi(recs: list[tuple[str | None, dict[str, Any]]]) -> dict[str, Any]:
        """ALLOW만 진입으로 가정한 proxy KPI."""

        accepted = [r for rec, r in recs if rec == "ALLOW"]
        held = [r for rec, r in recs if rec in {"HOLD", "REDUCE"}]
        nets = [float(r["net_pnl_krw"]) for r in accepted]
        wins = sum(1 for n in nets if n > 0)
        losses = sum(1 for n in nets if n < 0)
        gross_win = sum(n for n in nets if n > 0)
        gross_loss = abs(sum(n for n in nets if n < 0))
        pf = (gross_win / gross_loss) if gross_loss > 0 else None
        avoided = [r for r in held if float(r["net_pnl_krw"]) < 0]
        missed = [r for r in held if float(r["net_pnl_krw"]) > 0]
        early_acc = [r for r in accepted if r.get("early_dump_actual")]
        return {
            "accepted": len(accepted),
            "filtered": len(held),
            "allow_precision": (
                round(wins / len(accepted), 4) if accepted else None
            ),
            "avoided_loss_count": len(avoided),
            "avoided_loss_krw": round(
                abs(sum(float(r["net_pnl_krw"]) for r in avoided)), 4
            ),
            "missed_winner_count": len(missed),
            "missed_winner_krw": round(
                sum(float(r["net_pnl_krw"]) for r in missed), 4
            ),
            "net_pnl": round(sum(nets), 4) if nets else 0.0,
            "pf_proxy": round(pf, 4) if pf is not None else None,
            "early_dump_rate": (
                round(len(early_acc) / len(accepted), 4) if accepted else None
            ),
            "wins": wins,
            "losses": losses,
        }

    heur_arm = arm_kpi([(r["heuristic_rec"], r) for r in dual_rows])
    llm_arm = arm_kpi(
        [(r["llm_rec"], r) for r in dual_rows if r.get("llm_ok") and r.get("llm_rec")]
    )

    # Early dump detection when LLM said HIGH and actual early_dump
    dump_pairs = [
        r
        for r in dual_rows
        if r.get("llm_ok") and r.get("early_dump_risk") == "HIGH"
    ]
    dump_hit = sum(1 for r in dump_pairs if r.get("early_dump_actual"))

    promo = promotion_status(len(clean_obs))
    return {
        "schema": "heuristic_vs_trading_llm_shadow_v1",
        "research_only": True,
        "CURRENT_HEURISTIC_VS_LLM_SHADOW_AVAILABLE": len(dual_rows) > 0,
        "dual_shadow_sample_count": len(dual_rows),
        "clean_forward_count": len(clean_obs),
        **promo,
        "current_heuristic": heur_arm,
        "trading_llm_shadow": llm_arm,
        "early_dump_detection": {
            "llm_high_flags": len(dump_pairs),
            "actual_hits": dump_hit,
            "hit_rate": (
                round(dump_hit / len(dump_pairs), 4) if dump_pairs else None
            ),
        },
        "net_benefit_proxy": round(
            float(llm_arm.get("net_pnl") or 0) - float(heur_arm.get("net_pnl") or 0),
            4,
        ),
        "auto_promote": False,
        "REAL_POLICY_CHANGED": "NO",
        "items_preview": dual_rows[:20],
    }
