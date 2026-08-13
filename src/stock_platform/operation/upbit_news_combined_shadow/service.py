"""STEP N6 — Combined Shadow Experiment service (CONTROL READ-only)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from stock_platform.common.logger import logger
from stock_platform.common.settings import get_settings
from stock_platform.operation.upbit_news_combined_shadow.entities import (
    UpbitNewsCombinedShadowEntity,
)
from stock_platform.operation.upbit_news_combined_shadow.matching import (
    load_symbol_signals,
)
from stock_platform.operation.upbit_news_combined_shadow.policy import (
    COMBINED_POLICY_VERSION,
    EVAL_ACTIVE,
    EVAL_COMPLETED,
    EVAL_PENDING,
    EXPERIMENT_VERSION,
    NEWS_STATUS_EXCLUDED_ONLY,
    NEWS_STATUS_MATCHED,
    NEWS_STATUS_NO_NEWS,
)
from stock_platform.operation.upbit_news_combined_shadow.scoring import (
    aggregate_news_component,
    assign_counterfactual_ranks,
    experimental_combined_score,
    experimental_decision,
)
from stock_platform.operation.upbit_opportunity_shadow.constants import (
    SHADOW_STATUS_COMPLETED,
)
from stock_platform.operation.upbit_opportunity_shadow.entities import (
    UpbitOpportunityShadowEntity,
)


@dataclass
class CombinedShadowRunStats:
    scanner_runs_processed: int = 0
    technical_candidates: int = 0
    experiment_rows_created: int = 0
    experiment_rows_reused: int = 0
    no_news: int = 0
    news_matched: int = 0
    excluded_only: int = 0
    boost: int = 0
    unchanged: int = 0
    deprioritize: int = 0
    llm_calls: int = 0
    control_mutated: bool = False
    source_shadow: int = 0
    source_memory_top_n: int = 0
    top_n_history_reusable: bool = False
    samples: list[dict[str, Any]] = field(default_factory=list)
    errors: list[dict[str, Any]] = field(default_factory=list)


def _control_snapshot(shadow: UpbitOpportunityShadowEntity) -> dict[str, Any]:
    snap = shadow.entry_snapshot if isinstance(shadow.entry_snapshot, dict) else {}
    return {
        "price": float(shadow.entry_price),
        "ma5": shadow.ma5,
        "ma20": shadow.ma20,
        "ma_spread_pct": snap.get("ma_spread_pct"),
        "momentum": shadow.momentum,
        "rsi": shadow.rsi14,
        "macd": shadow.macd,
        "macd_histogram": snap.get("macd_histogram"),
        "atr": shadow.atr14,
        "volatility": shadow.volatility,
        "volume_surge": shadow.volume_surge,
        "trade_value_24h": shadow.trade_value_24h,
        "trend": shadow.trend,
        "entry_snapshot": snap,
    }


class UpbitNewsCombinedShadowService:
    """CONTROL Shadow READ → EXPERIMENT observation. CONTROL write 금지."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def run_from_control_shadows(
        self,
        *,
        limit_runs: int = 5,
        scanner_run_ids: list[str] | None = None,
        force: bool = False,
        include_memory_top_n: bool = True,
    ) -> CombinedShadowRunStats:
        """CONTROL Shadow + optional in-memory Scanner last_result Top N (READ).

        Historical full Top N DB reconstruction is NOT available
        (SOURCE_COVERAGE_LIMITED). Memory last_result may include HOLD.
        """

        stats = CombinedShadowRunStats(top_n_history_reusable=False)
        run_ids = scanner_run_ids or self._recent_run_ids(limit=limit_runs)
        # memory last_result run_id를 함께 처리
        memory_payloads_by_run: dict[str, list[dict[str, Any]]] = {}
        if include_memory_top_n:
            memory_payloads_by_run = self._memory_top_n_payloads()
            for rid in memory_payloads_by_run:
                if rid not in run_ids:
                    run_ids = [rid, *run_ids]
        stats.scanner_runs_processed = len(run_ids)

        for run_id in run_ids:
            shadows = list(
                self._session.scalars(
                    select(UpbitOpportunityShadowEntity)
                    .where(
                        UpbitOpportunityShadowEntity.scanner_run_id == run_id,
                        UpbitOpportunityShadowEntity.deleted_at.is_(None),
                    )
                    .order_by(
                        UpbitOpportunityShadowEntity.scanner_rank.asc().nullslast(),
                        UpbitOpportunityShadowEntity.shadow_id.asc(),
                    )
                )
            )
            by_symbol: dict[str, dict[str, Any]] = {}
            for shadow in shadows:
                stats.technical_candidates += 1
                stats.source_shadow += 1
                try:
                    payload = self._build_observation(shadow)
                    by_symbol[str(payload["symbol"]).upper()] = payload
                except Exception as exc:  # noqa: BLE001
                    stats.errors.append(
                        {
                            "scanner_run_id": run_id,
                            "symbol": shadow.symbol,
                            "error": f"{type(exc).__name__}: {exc}"[:300],
                        }
                    )
                    logger.warning(
                        "news_combined_shadow_build_failed",
                        shadow_id=shadow.shadow_id,
                        error=str(exc)[:200],
                    )

            # memory Top N: shadow에 없는 HOLD 등만 추가 (dedup by symbol)
            for payload in memory_payloads_by_run.get(run_id, []):
                sym = str(payload["symbol"]).upper()
                if sym in by_symbol:
                    continue
                stats.technical_candidates += 1
                stats.source_memory_top_n += 1
                by_symbol[sym] = payload

            batch_payloads = list(by_symbol.values())
            assign_counterfactual_ranks(batch_payloads)

            for payload in batch_payloads:
                row, action = self._upsert(payload, force=force)
                if action == "created":
                    stats.experiment_rows_created += 1
                else:
                    stats.experiment_rows_reused += 1
                if payload["news_context_status"] == NEWS_STATUS_MATCHED:
                    stats.news_matched += 1
                elif payload["news_context_status"] == NEWS_STATUS_NO_NEWS:
                    stats.no_news += 1
                elif payload["news_context_status"] == NEWS_STATUS_EXCLUDED_ONLY:
                    stats.excluded_only += 1
                dec = payload["experimental_decision"]
                if dec == "BOOST":
                    stats.boost += 1
                elif dec == "DEPRIORITIZE":
                    stats.deprioritize += 1
                else:
                    stats.unchanged += 1
                if len(stats.samples) < 20:
                    stats.samples.append(self._to_sample(row))

        stats.llm_calls = 0
        stats.control_mutated = False
        self._session.commit()
        return stats

    def _memory_top_n_payloads(self) -> dict[str, list[dict[str, Any]]]:
        """Scanner scheduler last_result READ — Scanner 수정/재실행 없음."""

        try:
            from stock_platform.operation.upbit_opportunity_scanner.scheduler import (
                upbit_opportunity_scanner_scheduler,
            )

            status = upbit_opportunity_scanner_scheduler.status()
        except Exception:  # noqa: BLE001
            return {}
        last = status.get("last_result") if isinstance(status, dict) else None
        if not isinstance(last, dict):
            return {}
        run_id = str(last.get("scanner_run_id") or "")
        candidates = last.get("candidates")
        if not run_id or not isinstance(candidates, list):
            return {}
        # shadow map for control_shadow_id join
        shadows = {
            str(s.symbol).upper(): s
            for s in self._session.scalars(
                select(UpbitOpportunityShadowEntity).where(
                    UpbitOpportunityShadowEntity.scanner_run_id == run_id,
                    UpbitOpportunityShadowEntity.deleted_at.is_(None),
                )
            )
        }
        out: list[dict[str, Any]] = []
        detected_at = datetime.now(timezone.utc)
        for cand in candidates:
            if not isinstance(cand, dict):
                continue
            symbol = str(cand.get("symbol") or "").upper()
            if not symbol.startswith("KRW-"):
                continue
            shadow = shadows.get(symbol)
            if shadow is not None:
                # shadow path가 우선 — memory skip (dedup later)
                continue
            try:
                out.append(
                    self._build_observation_from_candidate(
                        scanner_run_id=run_id,
                        candidate=cand,
                        detected_at=detected_at,
                        control_shadow_id=None,
                    )
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "news_combined_memory_candidate_failed",
                    symbol=symbol,
                    error=str(exc)[:200],
                )
        return {run_id: out} if out else {}

    def _build_observation_from_candidate(
        self,
        *,
        scanner_run_id: str,
        candidate: dict[str, Any],
        detected_at: datetime,
        control_shadow_id: int | None,
    ) -> dict[str, Any]:
        symbol = str(candidate.get("symbol") or "").upper()
        t0 = detected_at
        signals = load_symbol_signals(self._session, symbol=symbol, t0=t0)
        influence = [s for s in signals if s.get("influence_allowed")]
        excluded = [s for s in signals if not s.get("influence_allowed")]
        if influence:
            news_status = NEWS_STATUS_MATCHED
        elif excluded:
            news_status = NEWS_STATUS_EXCLUDED_ONLY
        else:
            news_status = NEWS_STATUS_NO_NEWS
        contribs = [float(s["contribution"]) for s in influence]
        agg = aggregate_news_component(contribs)
        scanner_score = float(candidate.get("score") or 0.0)
        combined = experimental_combined_score(
            scanner_score=scanner_score,
            news_component_normalized=agg["news_component_normalized"],
        )
        decision = experimental_decision(agg["news_component_normalized"])
        price = candidate.get("price") or candidate.get("entry_price") or 0
        if float(price or 0) <= 0:
            raise ValueError("candidate missing price")
        return {
            "experiment_version": EXPERIMENT_VERSION,
            "combined_policy_version": COMBINED_POLICY_VERSION,
            "scanner_run_id": scanner_run_id,
            "symbol": symbol,
            "candidate_detected_at": t0,
            "control_scanner_rank": candidate.get("rank"),
            "control_scanner_score": scanner_score,
            "control_market_ai_recommendation": candidate.get(
                "recommendation"
            ),
            "control_market_ai_confidence": candidate.get("confidence"),
            "control_market_ai_risk": candidate.get("risk_level"),
            "control_analysis_id": candidate.get("analysis_id"),
            "control_shadow_id": control_shadow_id,
            "technical_snapshot": {
                "source": "scanner_scheduler_last_result",
                "candidate": candidate,
            },
            "news_context_status": news_status,
            "eligible_news_count": len(influence),
            "news_signal_ids": [s["signal_id"] for s in influence],
            "news_snapshot": {
                "influence_signals": influence,
                "excluded_signals": excluded[:20],
                "excluded_count": len(excluded),
            },
            "experimental_news_component": agg["experimental_news_component"],
            "news_component_normalized": agg["news_component_normalized"],
            "experimental_combined_score": combined,
            "experimental_decision": decision,
            "counterfactual_rank": None,
            "rank_delta": None,
            "entry_price": Decimal(str(price or 0)),
            "evaluation_status": EVAL_PENDING,
            "completed_at": None,
            "evaluation_detail": {
                "source": "SCANNER_MEMORY_TOP_N",
                "note": "ephemeral Top N READ; historical HOLD not in DB",
            },
            "provenance": {
                "experiment_version": EXPERIMENT_VERSION,
                "source": "SCANNER_MEMORY_TOP_N",
                "scanner_run_id": scanner_run_id,
                "control_shadow_id": control_shadow_id,
                "llm_calls": 0,
                "control_write": False,
            },
            "return_5m_pct": None,
            "return_15m_pct": None,
            "return_30m_pct": None,
            "return_60m_pct": None,
            "mfe_pct": None,
            "mae_pct": None,
        }

    def _recent_run_ids(self, *, limit: int) -> list[str]:
        rows = self._session.execute(
            select(UpbitOpportunityShadowEntity.scanner_run_id)
            .where(UpbitOpportunityShadowEntity.deleted_at.is_(None))
            .group_by(UpbitOpportunityShadowEntity.scanner_run_id)
            .order_by(func.max(UpbitOpportunityShadowEntity.detected_at).desc())
            .limit(max(1, min(int(limit), 20)))
        ).all()
        return [str(r[0]) for r in rows]

    def _build_observation(
        self, shadow: UpbitOpportunityShadowEntity
    ) -> dict[str, Any]:
        t0 = shadow.detected_at
        symbol = str(shadow.symbol).upper()
        signals = load_symbol_signals(
            self._session, symbol=symbol, t0=t0
        )
        influence = [s for s in signals if s.get("influence_allowed")]
        excluded = [s for s in signals if not s.get("influence_allowed")]

        if influence:
            news_status = NEWS_STATUS_MATCHED
        elif excluded:
            news_status = NEWS_STATUS_EXCLUDED_ONLY
        else:
            news_status = NEWS_STATUS_NO_NEWS

        contribs = [float(s["contribution"]) for s in influence]
        agg = aggregate_news_component(contribs)
        scanner_score = float(shadow.scanner_score or 0.0)
        combined = experimental_combined_score(
            scanner_score=scanner_score,
            news_component_normalized=agg["news_component_normalized"],
        )
        decision = experimental_decision(agg["news_component_normalized"])

        # outcome seed from CONTROL if completed (same T0/entry)
        eval_status = EVAL_PENDING
        returns: dict[str, float | None] = {
            "return_5m_pct": None,
            "return_15m_pct": None,
            "return_30m_pct": None,
            "return_60m_pct": None,
            "mfe_pct": None,
            "mae_pct": None,
        }
        eval_detail: dict[str, Any] = {"source": None}
        completed_at = None
        if shadow.status == SHADOW_STATUS_COMPLETED and shadow.return_60m_pct is not None:
            returns = {
                "return_5m_pct": shadow.return_5m_pct,
                "return_15m_pct": shadow.return_15m_pct,
                "return_30m_pct": shadow.return_30m_pct,
                "return_60m_pct": shadow.return_60m_pct,
                "mfe_pct": shadow.mfe_pct,
                "mae_pct": shadow.mae_pct,
            }
            eval_status = EVAL_COMPLETED
            completed_at = shadow.completed_at
            eval_detail = {
                "source": "CONTROL_SHADOW_COPY",
                "control_shadow_id": shadow.shadow_id,
                "note": "same T0/entry — outcome identical for A/B selection study",
            }
        elif shadow.return_5m_pct is not None:
            returns["return_5m_pct"] = shadow.return_5m_pct
            returns["return_15m_pct"] = shadow.return_15m_pct
            returns["return_30m_pct"] = shadow.return_30m_pct
            returns["return_60m_pct"] = shadow.return_60m_pct
            returns["mfe_pct"] = shadow.mfe_pct
            returns["mae_pct"] = shadow.mae_pct
            eval_status = EVAL_ACTIVE
            eval_detail = {
                "source": "CONTROL_SHADOW_PARTIAL_COPY",
                "control_shadow_id": shadow.shadow_id,
            }

        return {
            "experiment_version": EXPERIMENT_VERSION,
            "combined_policy_version": COMBINED_POLICY_VERSION,
            "scanner_run_id": shadow.scanner_run_id,
            "symbol": symbol,
            "candidate_detected_at": t0,
            "control_scanner_rank": shadow.scanner_rank,
            "control_scanner_score": scanner_score,
            "control_market_ai_recommendation": shadow.recommendation,
            "control_market_ai_confidence": shadow.confidence,
            "control_market_ai_risk": shadow.risk_level,
            "control_analysis_id": shadow.market_analysis_id,
            "control_shadow_id": shadow.shadow_id,
            "technical_snapshot": _control_snapshot(shadow),
            "news_context_status": news_status,
            "eligible_news_count": len(influence),
            "news_signal_ids": [s["signal_id"] for s in influence],
            "news_snapshot": {
                "influence_signals": influence,
                "excluded_signals": excluded[:20],
                "excluded_count": len(excluded),
            },
            "experimental_news_component": agg["experimental_news_component"],
            "news_component_normalized": agg["news_component_normalized"],
            "experimental_combined_score": combined,
            "experimental_decision": decision,
            "counterfactual_rank": None,
            "rank_delta": None,
            "entry_price": Decimal(str(shadow.entry_price)),
            "evaluation_status": eval_status,
            "completed_at": completed_at,
            "evaluation_detail": eval_detail,
            "provenance": {
                "experiment_version": EXPERIMENT_VERSION,
                "combined_policy_version": COMBINED_POLICY_VERSION,
                "scanner_run_id": shadow.scanner_run_id,
                "control_shadow_id": shadow.shadow_id,
                "news_signal_ids": [s["signal_id"] for s in influence],
                "n4_analysis_ids": sorted(
                    {
                        int(s["news_ai_analysis_id"])
                        for s in influence
                        if s.get("news_ai_analysis_id") is not None
                    }
                ),
                "article_ids": sorted(
                    {
                        int(s["article_id"])
                        for s in influence
                        if s.get("article_id") is not None
                    }
                ),
                "llm_calls": 0,
                "control_write": False,
            },
            **returns,
        }

    def _upsert(
        self, payload: dict[str, Any], *, force: bool
    ) -> tuple[UpbitNewsCombinedShadowEntity, str]:
        existing = self._session.scalar(
            select(UpbitNewsCombinedShadowEntity).where(
                UpbitNewsCombinedShadowEntity.scanner_run_id
                == payload["scanner_run_id"],
                UpbitNewsCombinedShadowEntity.symbol == payload["symbol"],
                UpbitNewsCombinedShadowEntity.experiment_version
                == EXPERIMENT_VERSION,
            )
        )
        if existing is not None and not force:
            return existing, "reused"

        now = datetime.now(timezone.utc)
        if existing is None:
            row = UpbitNewsCombinedShadowEntity(
                experiment_version=EXPERIMENT_VERSION,
                combined_policy_version=COMBINED_POLICY_VERSION,
                scanner_run_id=payload["scanner_run_id"],
                symbol=payload["symbol"],
                candidate_detected_at=payload["candidate_detected_at"],
                control_scanner_rank=payload["control_scanner_rank"],
                control_scanner_score=payload["control_scanner_score"],
                control_market_ai_recommendation=payload[
                    "control_market_ai_recommendation"
                ],
                control_market_ai_confidence=payload[
                    "control_market_ai_confidence"
                ],
                control_market_ai_risk=payload["control_market_ai_risk"],
                control_analysis_id=payload["control_analysis_id"],
                control_shadow_id=payload["control_shadow_id"],
                technical_snapshot=payload["technical_snapshot"],
                news_context_status=payload["news_context_status"],
                eligible_news_count=payload["eligible_news_count"],
                news_signal_ids=payload["news_signal_ids"],
                news_snapshot=payload["news_snapshot"],
                experimental_news_component=payload[
                    "experimental_news_component"
                ],
                news_component_normalized=payload["news_component_normalized"],
                experimental_combined_score=payload[
                    "experimental_combined_score"
                ],
                experimental_decision=payload["experimental_decision"],
                counterfactual_rank=payload.get("counterfactual_rank"),
                rank_delta=payload.get("rank_delta"),
                entry_price=payload["entry_price"],
                evaluation_status=payload["evaluation_status"],
                return_5m_pct=payload.get("return_5m_pct"),
                return_15m_pct=payload.get("return_15m_pct"),
                return_30m_pct=payload.get("return_30m_pct"),
                return_60m_pct=payload.get("return_60m_pct"),
                mfe_pct=payload.get("mfe_pct"),
                mae_pct=payload.get("mae_pct"),
                evaluation_detail=payload.get("evaluation_detail") or {},
                provenance=payload.get("provenance") or {},
                completed_at=payload.get("completed_at"),
            )
            self._session.add(row)
            self._session.flush()
            return row, "created"

        for key in (
            "control_scanner_rank",
            "control_scanner_score",
            "control_market_ai_recommendation",
            "control_market_ai_confidence",
            "control_market_ai_risk",
            "control_analysis_id",
            "control_shadow_id",
            "technical_snapshot",
            "news_context_status",
            "eligible_news_count",
            "news_signal_ids",
            "news_snapshot",
            "experimental_news_component",
            "news_component_normalized",
            "experimental_combined_score",
            "experimental_decision",
            "counterfactual_rank",
            "rank_delta",
            "evaluation_status",
            "return_5m_pct",
            "return_15m_pct",
            "return_30m_pct",
            "return_60m_pct",
            "mfe_pct",
            "mae_pct",
            "evaluation_detail",
            "provenance",
            "completed_at",
        ):
            setattr(existing, key, payload.get(key))
        existing.entry_price = payload["entry_price"]
        existing.candidate_detected_at = payload["candidate_detected_at"]
        existing.updated_at = now
        self._session.flush()
        return existing, "updated"

    @staticmethod
    def _to_sample(row: UpbitNewsCombinedShadowEntity) -> dict[str, Any]:
        return {
            "experiment_id": row.experiment_id,
            "scanner_run_id": row.scanner_run_id,
            "symbol": row.symbol,
            "control_scanner_rank": row.control_scanner_rank,
            "control_scanner_score": row.control_scanner_score,
            "eligible_news_count": row.eligible_news_count,
            "news_context_status": row.news_context_status,
            "experimental_news_component": row.experimental_news_component,
            "news_component_normalized": row.news_component_normalized,
            "experimental_combined_score": row.experimental_combined_score,
            "experimental_decision": row.experimental_decision,
            "counterfactual_rank": row.counterfactual_rank,
            "rank_delta": row.rank_delta,
            "return_60m_pct": row.return_60m_pct,
            "mfe_pct": row.mfe_pct,
            "mae_pct": row.mae_pct,
            "evaluation_status": row.evaluation_status,
            "informational_only": True,
            "experiment_only": True,
        }


def list_recent_experiments(
    session: Session, *, limit: int = 20
) -> list[dict[str, Any]]:
    rows = list(
        session.scalars(
            select(UpbitNewsCombinedShadowEntity)
            .order_by(UpbitNewsCombinedShadowEntity.created_at.desc())
            .limit(max(1, min(limit, 100)))
        )
    )
    return [UpbitNewsCombinedShadowService._to_sample(r) for r in rows]


def experiment_stats_snapshot(session: Session) -> dict[str, Any]:
    total = (
        session.scalar(
            select(func.count()).select_from(UpbitNewsCombinedShadowEntity)
        )
        or 0
    )

    def _group(col):
        rows = session.execute(select(col, func.count()).group_by(col)).all()
        return {str(k): int(v) for k, v in rows if k is not None}

    completed = list(
        session.scalars(
            select(UpbitNewsCombinedShadowEntity).where(
                UpbitNewsCombinedShadowEntity.evaluation_status
                == EVAL_COMPLETED
            )
        )
    )

    def _avg_ret(rows: list[UpbitNewsCombinedShadowEntity]) -> float | None:
        vals = [r.return_60m_pct for r in rows if r.return_60m_pct is not None]
        if not vals:
            return None
        return round(sum(vals) / len(vals), 6)

    def _win_rate(rows: list[UpbitNewsCombinedShadowEntity]) -> float | None:
        vals = [r.return_60m_pct for r in rows if r.return_60m_pct is not None]
        if not vals:
            return None
        return round(sum(1 for v in vals if v > 0) / len(vals), 4)

    by_news = {
        "NEWS_MATCHED": [
            r for r in completed if r.news_context_status == NEWS_STATUS_MATCHED
        ],
        "NO_NEWS": [
            r for r in completed if r.news_context_status == NEWS_STATUS_NO_NEWS
        ],
        "BOOST": [r for r in completed if r.experimental_decision == "BOOST"],
        "DEPRIORITIZE": [
            r for r in completed if r.experimental_decision == "DEPRIORITIZE"
        ],
        "UNCHANGED": [
            r for r in completed if r.experimental_decision == "UNCHANGED"
        ],
    }
    avg60 = {k: _avg_ret(v) for k, v in by_news.items()}
    win60 = {k: _win_rate(v) for k, v in by_news.items()}

    settings = get_settings()
    scores = list(
        session.scalars(
            select(UpbitNewsCombinedShadowEntity.experimental_combined_score)
        )
    )
    score_range = None
    if scores:
        score_range = {
            "min": round(min(scores), 4),
            "max": round(max(scores), 4),
        }

    return {
        "experiment_only": True,
        "informational_only": True,
        "control_mutation": False,
        "llm_calls": 0,
        "experiment_version": EXPERIMENT_VERSION,
        "enabled": bool(
            getattr(settings, "upbit_news_combined_shadow_enabled", False)
        ),
        "total_rows": int(total),
        "by_news_context": _group(
            UpbitNewsCombinedShadowEntity.news_context_status
        ),
        "by_decision": _group(
            UpbitNewsCombinedShadowEntity.experimental_decision
        ),
        "by_evaluation_status": _group(
            UpbitNewsCombinedShadowEntity.evaluation_status
        ),
        "completed_n": len(completed),
        "avg_return_60m": avg60,
        "win_rate_60m": win60,
        "experimental_score_range": score_range,
        "contract": {
            "experimental_score_neq_scanner_score": True,
            "experimental_decision_neq_ai_gate": True,
            "news_signal_neq_buy_sell": True,
        },
        "sample_milestone": _safe_milestone(session),
        "observation": _safe_observation(session),
        "diagnostics": _safe_diagnostics(session),
        "matched_examples": _safe_matched(session),
        "source_policy": {
            "control_shadow": True,
            "scanner_memory_top_n": True,
            "historical_top_n_db": False,
            "top_n_history_reusable": False,
        },
        "n4_n5_auto_enable": False,
        "apply_to_scanner": False,
    }


def _safe_milestone(session: Session) -> dict[str, Any]:
    from stock_platform.operation.upbit_news_combined_shadow.diagnostics import (
        compute_sample_milestone,
    )

    try:
        return compute_sample_milestone(session)
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)[:200]}


def _safe_observation(session: Session) -> dict[str, Any]:
    from stock_platform.operation.upbit_news_combined_shadow.diagnostics import (
        compute_observation_stats,
    )

    try:
        return compute_observation_stats(session)
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)[:200]}


def _safe_diagnostics(session: Session) -> dict[str, Any]:
    from stock_platform.operation.upbit_news_combined_shadow.diagnostics import (
        diagnose_news_availability,
    )

    try:
        return diagnose_news_availability(session)
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)[:200]}


def _safe_matched(session: Session) -> list[dict[str, Any]]:
    from stock_platform.operation.upbit_news_combined_shadow.diagnostics import (
        list_matched_details,
    )

    try:
        return list_matched_details(session, limit=10)
    except Exception as exc:  # noqa: BLE001
        return [{"error": str(exc)[:200]}]
