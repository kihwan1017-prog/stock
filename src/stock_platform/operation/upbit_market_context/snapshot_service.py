"""Snapshot persistence + context bundle builder (research only)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.operation.upbit_market_context.as_of import (
    as_utc,
    select_latest_as_of,
    validate_bundle_no_lookahead,
)
from stock_platform.operation.upbit_market_context.collectors import (
    blocked_datalab_placeholder,
    build_market_metrics_from_tickers,
    dedupe_news_items,
    fetch_fear_greed_alternative_me,
)
from stock_platform.operation.upbit_market_context.constants import (
    STALE_AFTER_ASSET,
    STALE_AFTER_DESCRIPTION,
    TTL_ASSET_DESCRIPTION,
)
from stock_platform.operation.upbit_market_context.entities import (
    UpbitAssetContextSnapshotEntity,
    UpbitAssetDescriptionCacheEntity,
    UpbitLlmContextAnalysisEntity,
    UpbitMarketContextSnapshotEntity,
)
from stock_platform.operation.upbit_market_context.schemas import (
    LlmContextInput,
    LlmContextOutput,
    fail_open_output,
    parse_llm_output,
)
from stock_platform.operation.upbit_market_context.source_registry import (
    QUALITY_AVAILABLE,
    QUALITY_MISSING,
    QUALITY_STALE,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _quality_with_stale(
    quality: str, *, source_timestamp: datetime, stale_after: datetime | None
) -> str:
    if quality != QUALITY_AVAILABLE:
        return quality
    if stale_after is not None and _now() > as_utc(stale_after):  # type: ignore[operator]
        return QUALITY_STALE
    return quality


class MarketContextSnapshotService:
    """시장/자산 snapshot 저장·조회. REAL 주문과 무관."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def persist_rows(self, rows: list[dict[str, Any]]) -> int:
        n = 0
        for row in rows:
            sym = row.get("symbol")
            if sym:
                ent = UpbitAssetContextSnapshotEntity(
                    source=str(row["source"]),
                    symbol=str(sym),
                    feature_key=str(row["feature_key"]),
                    observed_at=row.get("observed_at") or _now(),
                    source_timestamp=row["source_timestamp"],
                    stale_after=row.get("stale_after"),
                    quality=str(row["quality"]),
                    value_json=dict(row.get("value_json") or {}),
                    raw_provenance=row.get("raw_provenance"),
                )
                self._session.add(ent)
            else:
                ent_m = UpbitMarketContextSnapshotEntity(
                    source=str(row["source"]),
                    feature_key=str(row["feature_key"]),
                    observed_at=row.get("observed_at") or _now(),
                    source_timestamp=row["source_timestamp"],
                    stale_after=row.get("stale_after"),
                    quality=str(row["quality"]),
                    value_json=dict(row.get("value_json") or {}),
                    raw_provenance=row.get("raw_provenance"),
                )
                self._session.add(ent_m)
            n += 1
        return n

    def collect_and_persist_from_tickers(
        self, tickers: list[dict[str, Any]], *, include_fear_greed: bool = True
    ) -> dict[str, Any]:
        rows = build_market_metrics_from_tickers(tickers)
        if include_fear_greed:
            rows.append(fetch_fear_greed_alternative_me())
        # DataLab blocked placeholders (once per cycle — market level)
        for key in (
            "upbit_market_index",
            "altcoin_index",
            "upbit10",
            "upbit30",
            "altcoin_season",
            "btc_dominance",
        ):
            rows.append(blocked_datalab_placeholder(key))
        saved = self.persist_rows(rows)
        self._session.flush()
        return {"saved": saved, "rows": len(rows)}

    def list_market_feature(
        self, feature_key: str, *, limit: int = 50
    ) -> list[dict[str, Any]]:
        q = (
            select(UpbitMarketContextSnapshotEntity)
            .where(UpbitMarketContextSnapshotEntity.feature_key == feature_key)
            .order_by(UpbitMarketContextSnapshotEntity.source_timestamp.desc())
            .limit(limit)
        )
        return [self._market_to_dict(r) for r in self._session.scalars(q)]

    def list_asset_feature(
        self, symbol: str, feature_key: str, *, limit: int = 50
    ) -> list[dict[str, Any]]:
        q = (
            select(UpbitAssetContextSnapshotEntity)
            .where(
                UpbitAssetContextSnapshotEntity.symbol == symbol,
                UpbitAssetContextSnapshotEntity.feature_key == feature_key,
            )
            .order_by(UpbitAssetContextSnapshotEntity.source_timestamp.desc())
            .limit(limit)
        )
        return [self._asset_to_dict(r) for r in self._session.scalars(q)]

    @staticmethod
    def _market_to_dict(r: UpbitMarketContextSnapshotEntity) -> dict[str, Any]:
        return {
            "snapshot_id": int(r.snapshot_id),
            "source": r.source,
            "feature_key": r.feature_key,
            "observed_at": r.observed_at,
            "source_timestamp": r.source_timestamp,
            "stale_after": r.stale_after,
            "quality": r.quality,
            "value_json": r.value_json,
            "raw_provenance": r.raw_provenance,
        }

    @staticmethod
    def _asset_to_dict(r: UpbitAssetContextSnapshotEntity) -> dict[str, Any]:
        return {
            "snapshot_id": int(r.snapshot_id),
            "source": r.source,
            "symbol": r.symbol,
            "feature_key": r.feature_key,
            "observed_at": r.observed_at,
            "source_timestamp": r.source_timestamp,
            "stale_after": r.stale_after,
            "quality": r.quality,
            "value_json": r.value_json,
            "raw_provenance": r.raw_provenance,
        }

    def upsert_description_stub(
        self,
        *,
        symbol: str,
        korean_name: str | None,
        english_name: str | None,
        market_warning: dict[str, Any] | None,
    ) -> UpbitAssetDescriptionCacheEntity:
        """공식 market/all details 기반 stub — DataLab 설명서 대체."""

        now = _now()
        existing = self._session.scalar(
            select(UpbitAssetDescriptionCacheEntity).where(
                UpbitAssetDescriptionCacheEntity.symbol == symbol
            )
        )
        summary = f"{korean_name or symbol} / {english_name or ''}".strip(" /")
        risks = None
        if isinstance(market_warning, dict) and (
            market_warning.get("warning") or market_warning.get("caution")
        ):
            risks = f"market_event={market_warning}"
        if existing is not None:
            # TTL: skip refresh if fresh
            if existing.refreshed_at and as_utc(existing.refreshed_at) and (
                now - as_utc(existing.refreshed_at)  # type: ignore[operator]
                < TTL_ASSET_DESCRIPTION
            ):
                return existing
            existing.project_summary = summary
            existing.known_risks = risks
            existing.quality = QUALITY_AVAILABLE if summary else QUALITY_MISSING
            existing.refreshed_at = now
            existing.stale_after = now + STALE_AFTER_DESCRIPTION
            existing.raw_provenance = {
                "source": "upbit_market_all_isDetails",
                "note": "static stub; full DataLab description deferred",
            }
            return existing
        ent = UpbitAssetDescriptionCacheEntity(
            symbol=symbol,
            source="upbit_market_all_isDetails",
            quality=QUALITY_AVAILABLE if summary else QUALITY_MISSING,
            project_summary=summary,
            sector=None,
            main_use_case=None,
            token_characteristics=None,
            known_risks=risks,
            official_links=None,
            raw_provenance={
                "source": "upbit_market_all_isDetails",
                "note": "static stub; full DataLab description deferred",
            },
            refreshed_at=now,
            stale_after=now + STALE_AFTER_DESCRIPTION,
        )
        self._session.add(ent)
        return ent

    def build_llm_input(
        self,
        *,
        detected_at: datetime,
        candidate: dict[str, Any],
        technical: dict[str, Any] | None = None,
        news_items: list[dict[str, Any]] | None = None,
    ) -> tuple[LlmContextInput, dict[str, Any]]:
        """as-of bundle — lookahead 검증 포함."""

        det = as_utc(detected_at) or _now()
        symbol = str(candidate.get("symbol") or "")

        fear_rows = self.list_market_feature("fear_greed", limit=20)
        fear = select_latest_as_of(fear_rows, detected_at=det)
        adv_rows = self.list_market_feature("advancing_asset_ratio", limit=20)
        adv = select_latest_as_of(adv_rows, detected_at=det)
        turn_rows = self.list_market_feature("24h_turnover", limit=20)
        turn = select_latest_as_of(turn_rows, detected_at=det)
        mret_rows = self.list_market_feature("market_return", limit=20)
        mret = select_latest_as_of(mret_rows, detected_at=det)

        asset_rows = self.list_asset_feature(
            symbol, "asset_ticker_bundle", limit=20
        )
        asset = select_latest_as_of(asset_rows, detected_at=det)

        desc = self._session.scalar(
            select(UpbitAssetDescriptionCacheEntity).where(
                UpbitAssetDescriptionCacheEntity.symbol == symbol
            )
        )

        parts = {
            "fear_greed": fear.get("source_timestamp") if fear else None,
            "advancing_asset_ratio": adv.get("source_timestamp") if adv else None,
            "24h_turnover": turn.get("source_timestamp") if turn else None,
            "market_return": mret.get("source_timestamp") if mret else None,
            "asset_ticker": asset.get("source_timestamp") if asset else None,
        }
        alignment = validate_bundle_no_lookahead(detected_at=det, parts=parts)

        news = dedupe_news_items(news_items or [])
        # filter news published after detected_at
        news_ok = []
        for n in news:
            pub = as_utc(n.get("published_at"))
            if pub is None or pub <= det:
                news_ok.append(n)

        market_context = {
            "fear_greed": fear,
            "advancing_asset_ratio": adv,
            "24h_turnover": turn,
            "market_return": mret,
            "upbit_market_index": blocked_datalab_placeholder("upbit_market_index"),
            "altcoin_index": blocked_datalab_placeholder("altcoin_index"),
        }
        asset_context = {
            "ticker": asset,
            "buy_execution_strength_rank": blocked_datalab_placeholder(
                "buy_execution_strength_rank"
            ),
            "sell_execution_strength_rank": blocked_datalab_placeholder(
                "sell_execution_strength_rank"
            ),
        }
        returns = {}
        if asset and isinstance(asset.get("value_json"), dict):
            returns = {
                "daily_signed_change_rate": asset["value_json"].get(
                    "signed_change_rate"
                ),
                "turnover_rank": asset["value_json"].get("turnover_rank"),
                "acc_trade_price_24h": asset["value_json"].get(
                    "acc_trade_price_24h"
                ),
            }

        desc_payload = {}
        if desc is not None:
            desc_payload = {
                "project_summary": desc.project_summary,
                "sector": desc.sector,
                "known_risks": desc.known_risks,
                "quality": desc.quality,
                "refreshed_at": (
                    desc.refreshed_at.isoformat() if desc.refreshed_at else None
                ),
            }

        inp = LlmContextInput(
            context_as_of=det.isoformat(),
            candidate=candidate,
            technical=technical or {},
            market_context=market_context,
            asset_context=asset_context,
            execution_strength={
                "status": "DATALAB_DEFERRED",
                "buy_sell_pressure_ratio": QUALITY_MISSING,
            },
            returns=returns,
            news=news_ok,
            asset_description=desc_payload,
            research_only=True,
            may_create_orders=False,
        )
        meta = {
            "alignment": alignment,
            "stale_after_asset_default": STALE_AFTER_ASSET.total_seconds(),
        }
        return inp, meta

    def save_llm_analysis(
        self,
        *,
        symbol: str,
        detected_at: datetime,
        context_as_of: datetime,
        inp: LlmContextInput,
        out: LlmContextOutput,
        shadow_id: int | None = None,
        lookahead_ok: bool = True,
        quality: str = QUALITY_AVAILABLE,
    ) -> UpbitLlmContextAnalysisEntity:
        # JSONB는 datetime/Decimal 직렬화 불가 — mode=json 필수
        # (미적용 시 flush TypeError → fail-open swallow → calls>0 rows=0)
        ent = UpbitLlmContextAnalysisEntity(
            symbol=symbol,
            shadow_id=shadow_id,
            detected_at=as_utc(detected_at) or _now(),
            context_as_of=as_utc(context_as_of) or _now(),
            input_json=inp.model_dump(mode="json"),
            output_json=out.model_dump(mode="json"),
            recommendation=out.recommendation,
            confidence=float(out.confidence),
            entry_quality_score=int(out.entry_quality_score),
            quality=quality,
            lookahead_ok=lookahead_ok,
            research_only=True,
        )
        self._session.add(ent)
        return ent


def heuristic_llm_analyze(inp: LlmContextInput) -> LlmContextOutput:
    """Provider 없이 research heuristic — REAL 적용 금지.

    Early-dump 관련 risk flags만 보수적으로 표기.
    """

    try:
        flags: list[str] = []
        pos: list[str] = []
        neg: list[str] = []
        score = 55
        tech = inp.technical or {}
        rsi = tech.get("rsi14")
        pre5 = tech.get("pre_entry_return_5m")
        vol = tech.get("volume_surge")

        if rsi is not None and float(rsi) > 70:
            flags.append("OVERHEATED")
            neg.append(f"RSI={rsi}")
            score -= 15
        elif rsi is not None and float(rsi) <= 60:
            pos.append(f"RSI={rsi}")
            score += 5

        if pre5 is not None and float(pre5) >= 0.5:
            flags.append("RECENT_SPIKE")
            neg.append(f"pre5={pre5}")
            score -= 12

        if vol is not None and float(vol) >= 2.5:
            flags.append("OVERHEATED")
            neg.append(f"vol={vol}")
            score -= 8

        fear = (inp.market_context.get("fear_greed") or {}).get("value_json") or {}
        if fear.get("value") is not None and int(fear["value"]) >= 75:
            flags.append("OVERHEATED")
            neg.append(f"F&G={fear.get('value')}")
            score -= 5
        elif fear.get("value") is not None and int(fear["value"]) <= 30:
            pos.append(f"F&G fear {fear.get('value')}")
            score += 3

        adv = (inp.market_context.get("advancing_asset_ratio") or {}).get(
            "value_json"
        ) or {}
        if adv.get("ratio") is not None and float(adv["ratio"]) < 0.35:
            flags.append("MARKET_WEAK")
            neg.append("상승종목 비율 낮음")
            score -= 8

        context_missing = not inp.news and not fear and not tech
        if context_missing:
            flags.append("CONTEXT_UNAVAILABLE")

        score = max(0, min(100, score))
        if score >= 65 and "OVERHEATED" not in flags and "RECENT_SPIKE" not in flags:
            rec = "ALLOW"
        elif score <= 40 or "RECENT_SPIKE" in flags:
            rec = "REDUCE"
        else:
            rec = "HOLD"

        return LlmContextOutput(
            recommendation=rec,  # type: ignore[arg-type]
            confidence=round(min(0.85, 0.35 + abs(score - 50) / 100), 3),
            entry_quality_score=score,
            risk_flags=sorted(set(flags)),
            positive_factors=pos[:5],
            negative_factors=neg[:5],
            short_reason_ko="연구용 휴리스틱 평가(REAL 미적용)",
            context_unavailable=context_missing,
        )
    except Exception as exc:  # noqa: BLE001
        return fail_open_output(reason=str(exc)[:120])


# re-export parse for callers
__all__ = [
    "MarketContextSnapshotService",
    "heuristic_llm_analyze",
    "parse_llm_output",
    "fail_open_output",
]
