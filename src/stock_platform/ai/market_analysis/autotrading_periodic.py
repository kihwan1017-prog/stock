"""UPBIT autotrading용 주기 Market Analysis Job.

기존 AIMarketAnalysisService create→execute 경로 재사용.
LLM은 주문/Risk 우회 금지. Gate ON도 이 Job에서 하지 않는다.
scheduler 패키지 import 금지 — operation 스케줄러에서 호출.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import structlog
from sqlalchemy import desc, select, text
from sqlalchemy.orm import Session

from stock_platform.ai.market_analysis.entities import AIMarketAnalysisEntity
from stock_platform.ai.market_analysis.gate_enrichment import (
    enrich_safe_result_for_gate,
    validate_gate_recommendation_fields,
)
from stock_platform.ai.market_analysis.service import (
    AIMarketAnalysisError,
    AIMarketAnalysisService,
)
from stock_platform.common.settings import get_settings


logger = structlog.get_logger(__name__)

ACTOR = "job:upbit-autotrading-ai-analysis"
MIN_MINUTE_CANDLES = 30
DEFAULT_CANDLE_LOOKBACK_HOURS = 8


def time_bucket(now: datetime, interval_seconds: float) -> int:
    """동일 symbol·interval 중복 방지용 버킷."""

    ts = now.astimezone(timezone.utc).timestamp()
    step = max(60.0, float(interval_seconds))
    return int(ts // step)


def resolve_news_sentiment(session: Session, *, symbol: str) -> str:
    """Crypto 전용 crawler 없음 — 기사 없으면 NO_DATA (분석 실패 아님)."""

    try:
        n = session.execute(
            text(
                """
                SELECT COUNT(*) FROM news.news_article
                WHERE UPPER(exchange_code) IN ('UPBIT', 'CRYPTO')
                  AND UPPER(symbol) = :symbol
                  AND created_at >= NOW() - INTERVAL '24 hours'
                """
            ),
            {"symbol": symbol.upper()},
        ).scalar()
        if int(n or 0) > 0:
            return "NEUTRAL"
    except Exception:  # noqa: BLE001
        pass
    return "NO_DATA"


def _ollama_circuit_snapshot() -> dict[str, Any]:
    """Ollama circuit 상태 — OPEN이면 분석 create 전에 skip."""

    try:
        from stock_platform.ai.providers.manager import get_ai_manager

        circuit = get_ai_manager()._circuit_for("ollama")
        snap = circuit.snapshot()
        return {
            "allow": bool(circuit.allow()),
            "state": snap.get("state"),
            "failure_count": snap.get("failure_count"),
            "reset_seconds": snap.get("reset_seconds"),
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "allow": True,
            "state": "UNKNOWN",
            "error": type(exc).__name__,
        }


def _reset_ollama_circuit_after_warmup() -> dict[str, Any]:
    """warmup 성공 후 cold-start TIMEOUT으로 열린 circuit을 복구."""

    try:
        from stock_platform.ai.providers.manager import get_ai_manager

        circuit = get_ai_manager()._circuit_for("ollama")
        circuit.record_success()
        return {"reset": True, **circuit.snapshot()}
    except Exception as exc:  # noqa: BLE001
        return {"reset": False, "error": type(exc).__name__}


async def _warmup_ollama(settings: Any) -> dict[str, Any]:
    """모델 cold-start 완화용 초소형 ping. 실패해도 분석은 계속."""

    import httpx

    base = str(
        getattr(settings, "ollama_base_url", None) or "http://127.0.0.1:11434"
    ).rstrip("/")
    model = str(
        getattr(settings, "autotrading_ai_analysis_model", None)
        or getattr(settings, "ollama_model", None)
        or "qwen3.5:4b"
    )
    try:
        # cold start는 60~120s 소요 가능 — warmup만 여유, 분석 timeout과 분리
        async with httpx.AsyncClient(timeout=150.0) as client:
            tags = await client.get(f"{base}/api/tags")
            tags.raise_for_status()
            # 짧은 generate로 모델 로드 + keep_alive 유지
            gen = await client.post(
                f"{base}/api/generate",
                json={
                    "model": model,
                    "prompt": "ping",
                    "stream": False,
                    "keep_alive": "30m",
                    "options": {"num_predict": 1},
                },
            )
            ok = gen.status_code < 500
            out = {
                "ok": ok,
                "tags_ok": True,
                "generate_status": gen.status_code,
                "note": "cold_start_warmup",
            }
            if ok:
                out["circuit"] = _reset_ollama_circuit_after_warmup()
            return out
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "error": type(exc).__name__,
            "note": "warmup_failed_continue",
        }


def find_latest_validated(
    session: Session,
    *,
    exchange_code: str,
    symbol: str,
) -> AIMarketAnalysisEntity | None:
    """최신 validated 분석 — normalized fallback은 정상 분석으로 취급하지 않음."""

    rows = list(
        session.scalars(
            select(AIMarketAnalysisEntity)
            .where(
                AIMarketAnalysisEntity.exchange_code == exchange_code.upper(),
                AIMarketAnalysisEntity.symbol == symbol.upper(),
                AIMarketAnalysisEntity.analysis_status.in_(
                    ("VALIDATED_ANALYSIS", "VALIDATED_WITH_WARNINGS")
                ),
            )
            .order_by(
                desc(AIMarketAnalysisEntity.analyzed_at),
                desc(AIMarketAnalysisEntity.market_analysis_id),
            )
            .limit(20)
        )
    )
    for row in rows:
        warns = list(row.warnings or [])
        if "normalized_for_validation" in warns:
            continue
        safe = row.safe_result if isinstance(row.safe_result, dict) else {}
        safe_warns = list(safe.get("warnings") or [])
        if "normalized_for_validation" in safe_warns:
            continue
        return row
    return None


def is_analysis_fresh(
    row: AIMarketAnalysisEntity | None,
    *,
    ttl_seconds: float,
    now: datetime | None = None,
) -> bool:
    if row is None or row.analyzed_at is None:
        return False
    now_utc = now or datetime.now(timezone.utc)
    at = row.analyzed_at
    if at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)
    age = (now_utc - at.astimezone(timezone.utc)).total_seconds()
    return age <= float(ttl_seconds)


def resolve_analysis_reuse_seconds(
    settings: Any | None = None,
    *,
    interval_seconds: float | None = None,
    ttl_seconds: float | None = None,
) -> float:
    """Scheduler skip window — Gate TTL과 분리.

    우선순위:
    1) autotrading_ai_analysis_reuse_seconds (명시)
    2) interval_seconds
    3) ttl_seconds (하위호환 fallback)
    """

    settings = settings if settings is not None else get_settings()
    interval = float(
        interval_seconds
        if interval_seconds is not None
        else (
            getattr(settings, "autotrading_ai_analysis_interval_seconds", 300.0)
            or 300.0
        )
    )
    ttl = float(
        ttl_seconds
        if ttl_seconds is not None
        else (
            getattr(settings, "autotrading_ai_analysis_ttl_seconds", 900.0)
            or 900.0
        )
    )
    raw = getattr(settings, "autotrading_ai_analysis_reuse_seconds", None)
    if raw is None or str(raw).strip() == "":
        reuse = interval
    else:
        reuse = float(raw)
    if reuse <= 0:
        reuse = interval
    # reuse가 TTL보다 크면 Gate STALE 전에 refresh가 안 됨 → TTL로 clamp
    return min(reuse, ttl)


async def ensure_chart_prompt_active(session: Session) -> dict[str, Any]:
    """CHART_ANALYSIS_BASE ACTIVE + variable_schema 정합 보장."""

    from stock_platform.ai.prompt.entities import (
        AIPromptTemplateEntity,
        AIPromptTemplateVersionEntity,
    )
    from stock_platform.ai.prompt.management_service import (
        AIPromptManagementService,
    )
    from stock_platform.ai.prompt.seed_data import SEED_PROMPTS

    tmpl = session.scalar(
        select(AIPromptTemplateEntity).where(
            AIPromptTemplateEntity.code == "CHART_ANALYSIS_BASE"
        )
    )
    if tmpl is None:
        return {"ok": False, "error": "PROMPT_TEMPLATE_MISSING"}

    seed = next(
        (p for p in SEED_PROMPTS if p.get("code") == "CHART_ANALYSIS_BASE"),
        None,
    )
    required_vars = {
        "symbol",
        "exchange_code",
        "timeframe",
        "indicators",
        "current_price",
        "snapshot_json",
        "market_type",
        "data_quality",
    }

    svc = AIPromptManagementService(session)
    active_ver = None
    if tmpl.active_version_id is not None:
        active_ver = session.get(
            AIPromptTemplateVersionEntity, int(tmpl.active_version_id)
        )

    schema_ok = False
    prompt_text_ok = False
    if active_ver is not None and active_ver.status == "ACTIVE":
        props = (active_ver.variable_schema or {}).get("properties") or {}
        schema_ok = required_vars.issubset(set(props.keys()))
        # seed 시스템 프롬프트 마커 — V2 envelope 지시가 없으면 재시드
        prompt_text_ok = "CHART_JSON_ENVELOPE_V3" in str(
            active_ver.system_template or ""
        )

    if tmpl.status == "ACTIVE" and schema_ok and prompt_text_ok:
        return {
            "ok": True,
            "already_active": True,
            "version_id": int(tmpl.active_version_id),
            "schema_ok": True,
            "prompt_text_ok": True,
        }

    # schema 불완전하면 seed 기준으로 새 version 생성 후 activate
    if seed is None:
        if active_ver is None:
            versions = list(
                session.scalars(
                    select(AIPromptTemplateVersionEntity)
                    .where(
                        AIPromptTemplateVersionEntity.prompt_template_id
                        == int(tmpl.prompt_template_id)
                    )
                    .order_by(
                        desc(
                            AIPromptTemplateVersionEntity.prompt_template_version_id
                        )
                    )
                )
            )
            if not versions:
                return {"ok": False, "error": "PROMPT_VERSION_MISSING"}
            target_id = int(versions[0].prompt_template_version_id)
        else:
            target_id = int(active_ver.prompt_template_version_id)
    else:
        try:
            created = svc.create_version(
                int(tmpl.prompt_template_id),
                actor=ACTOR,
                reason="fix chart prompt variables for UPBIT autotrading analysis",
                system_template=str(seed["system"]),
                user_template=str(seed["user"]),
                context_template=str(seed.get("context") or ""),
                variable_schema=dict(seed["variable_schema"]),
                required_capabilities=list(seed.get("capabilities") or []),
                output_schema_id=active_ver.output_schema_id if active_ver else None,
                policy_id=active_ver.policy_id if active_ver else None,
                allow_duplicate_checksum=True,
            )
            target_id = int(created["id"])
        except Exception as exc:  # noqa: BLE001
            # duplicate 등 — 최신 version 사용
            versions = list(
                session.scalars(
                    select(AIPromptTemplateVersionEntity)
                    .where(
                        AIPromptTemplateVersionEntity.prompt_template_id
                        == int(tmpl.prompt_template_id)
                    )
                    .order_by(
                        desc(
                            AIPromptTemplateVersionEntity.prompt_template_version_id
                        )
                    )
                )
            )
            if not versions:
                return {
                    "ok": False,
                    "error": f"PROMPT_VERSION_CREATE_FAILED:{type(exc).__name__}",
                }
            target_id = int(versions[0].prompt_template_version_id)

    activated = svc.activate_version(
        target_id,
        actor=ACTOR,
        reason="UPBIT autotrading AI analysis requires ACTIVE chart prompt",
        confirm=True,
    )
    return {
        "ok": True,
        "already_active": False,
        "version_id": target_id,
        "activated": True,
        "schema_ok": True,
        "template_status": activated.get("template", {}).get("status"),
    }


async def ensure_minute_candles(
    session: Session,
    *,
    symbol: str,
    timeframe: int = 1,
    min_count: int = MIN_MINUTE_CANDLES,
    stale_seconds: float = 300.0,
    lookback_hours: int = DEFAULT_CANDLE_LOOKBACK_HOURS,
) -> dict[str, Any]:
    """분석 전 최소 분봉 확보 — 기존 UpbitMinuteSyncService 재사용."""

    from stock_platform.broker.upbit.market.client import UpbitQuotationClient
    from stock_platform.collectors.upbit.minute_collector import (
        UpbitMinuteCollector,
    )
    from stock_platform.collectors.upbit.minute_sync_service import (
        UpbitMinuteSyncService,
    )
    from stock_platform.markets.repository import (
        CandleMinuteRepository,
        InstrumentRepository,
    )
    from stock_platform.markets.service import (
        CandleMinuteService,
        InstrumentService,
    )

    count_row = session.execute(
        text(
            """
            SELECT COUNT(*) AS n, MAX(c.candle_at) AS last_at
            FROM market.candle_minute c
            JOIN market.instrument i ON i.instrument_id = c.instrument_id
            WHERE i.exchange_code = 'UPBIT'
              AND i.symbol = :symbol
              AND c.timeframe = :tf
            """
        ),
        {"symbol": symbol.upper(), "tf": int(timeframe)},
    ).mappings().first()
    count = int((count_row or {}).get("n") or 0)
    last_at = (count_row or {}).get("last_at")
    now = datetime.now(timezone.utc)
    age = None
    if isinstance(last_at, datetime):
        at = last_at if last_at.tzinfo else last_at.replace(tzinfo=timezone.utc)
        age = max(0.0, (now - at.astimezone(timezone.utc)).total_seconds())

    needs_sync = count < int(min_count) or age is None or age > float(stale_seconds)
    sync_result: dict[str, Any] | None = None
    if needs_sync:
        end = now
        start = end - timedelta(hours=int(lookback_hours))
        async with UpbitQuotationClient() as client:
            instr = InstrumentService(InstrumentRepository(session))
            candle = CandleMinuteService(
                CandleMinuteRepository(session),
                instrument_service=instr,
            )
            result = await UpbitMinuteSyncService(
                collector=UpbitMinuteCollector(client),
                candle_service=candle,
                instrument_service=instr,
            ).sync(
                market=symbol.upper(),
                timeframe=int(timeframe),
                start_at=start,
                end_at=end,
                resume=True,
            )
            session.commit()
            sync_result = {
                "collected": result.collected_count,
                "saved": result.saved_count,
                "timeframe": result.timeframe,
            }
        count_row = session.execute(
            text(
                """
                SELECT COUNT(*) AS n, MAX(c.candle_at) AS last_at
                FROM market.candle_minute c
                JOIN market.instrument i ON i.instrument_id = c.instrument_id
                WHERE i.exchange_code = 'UPBIT'
                  AND i.symbol = :symbol
                  AND c.timeframe = :tf
                """
            ),
            {"symbol": symbol.upper(), "tf": int(timeframe)},
        ).mappings().first()
        count = int((count_row or {}).get("n") or 0)
        last_at = (count_row or {}).get("last_at")
        if isinstance(last_at, datetime):
            at = last_at if last_at.tzinfo else last_at.replace(tzinfo=timezone.utc)
            age = max(0.0, (now - at.astimezone(timezone.utc)).total_seconds())

    ok = count >= int(min_count) and age is not None and age <= max(
        float(stale_seconds) * 2, 600.0
    )
    return {
        "ok": ok,
        "count": count,
        "last_at": last_at.isoformat() if isinstance(last_at, datetime) else None,
        "age_seconds": age,
        "synced": bool(sync_result),
        "sync": sync_result,
        "min_required": int(min_count),
    }


class UpbitAutotradingAiAnalysisJob:
    """KRW-XRP(기본) 주기 차트 분석 — Ollama EXTERNAL 명시."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._svc = AIMarketAnalysisService(session)

    async def run_once(
        self,
        *,
        symbol: str | None = None,
        timeframe: str | None = None,
        force: bool = False,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        settings = get_settings()
        exchange = "UPBIT"
        sym = (
            symbol
            or getattr(settings, "autotrading_ai_analysis_symbol", None)
            or "KRW-XRP"
        ).upper()
        tf = (
            timeframe
            or getattr(settings, "autotrading_ai_analysis_timeframe", None)
            or "1m"
        )
        interval = float(
            getattr(settings, "autotrading_ai_analysis_interval_seconds", 300.0)
            or 300.0
        )
        ttl = float(
            getattr(settings, "autotrading_ai_analysis_ttl_seconds", 900.0) or 900.0
        )
        # Gate TTL(900)과 Scheduler reuse/skip window 분리 — STALE gap 방지
        reuse_seconds = resolve_analysis_reuse_seconds(
            settings,
            interval_seconds=interval,
            ttl_seconds=ttl,
        )
        min_conf = float(
            getattr(settings, "autotrading_ai_min_confidence", 0.4) or 0.4
        )
        provider = str(
            getattr(settings, "autotrading_ai_analysis_provider", None) or "ollama"
        ).lower()
        model = str(
            getattr(settings, "autotrading_ai_analysis_model", None)
            or getattr(settings, "ollama_model", None)
            or "qwen3.5:4b"
        )
        now_utc = now or datetime.now(timezone.utc)
        if now_utc.tzinfo is None:
            now_utc = now_utc.replace(tzinfo=timezone.utc)
        bucket = time_bucket(now_utc, interval)
        idem = f"autotrading-ai-{sym}-{tf}-{bucket}"[:64]

        out: dict[str, Any] = {
            "job": "upbit_autotrading_ai_analysis",
            "symbol": sym,
            "timeframe": tf,
            "bucket": bucket,
            "provider": provider,
            "model": model,
            "ttl_seconds": ttl,
            "reuse_seconds": reuse_seconds,
            "interval_seconds": interval,
            "skipped": False,
            "orders_created": 0,
            "gate_enabled_changed": False,
        }

        latest = find_latest_validated(
            self._session, exchange_code=exchange, symbol=sym
        )
        if not force and is_analysis_fresh(
            latest, ttl_seconds=reuse_seconds, now=now_utc
        ):
            out.update(
                {
                    "skipped": True,
                    "skip_reason": "FRESH_RESULT_EXISTS",
                    "market_analysis_id": int(latest.market_analysis_id)
                    if latest
                    else None,
                    "analysis_at": latest.analyzed_at.isoformat()
                    if latest and latest.analyzed_at
                    else None,
                }
            )
            return out

        existing_bucket = self._session.scalar(
            select(AIMarketAnalysisEntity).where(
                AIMarketAnalysisEntity.created_by == ACTOR,
                AIMarketAnalysisEntity.idempotency_key == idem,
            )
        )
        if existing_bucket is not None and not force:
            out.update(
                {
                    "skipped": True,
                    "skip_reason": "DUPLICATE_TIME_BUCKET",
                    "market_analysis_id": int(
                        existing_bucket.market_analysis_id
                    ),
                    "analysis_status": existing_bucket.analysis_status,
                }
            )
            return out

        prompt_state = await ensure_chart_prompt_active(self._session)
        out["prompt"] = prompt_state
        if not prompt_state.get("ok"):
            out["ok"] = False
            out["error"] = prompt_state.get("error") or "PROMPT_NOT_READY"
            return out

        minute_tf = int(str(tf).rstrip("m") or "1")
        candle_state = await ensure_minute_candles(
            self._session,
            symbol=sym,
            timeframe=minute_tf,
            min_count=MIN_MINUTE_CANDLES,
            stale_seconds=min(interval, 300.0),
        )
        out["candle"] = candle_state
        if not candle_state.get("ok"):
            out["ok"] = False
            out["error"] = "MISSING_OR_STALE_CANDLE"
            return out

        news_sentiment = resolve_news_sentiment(self._session, symbol=sym)
        out["news_sentiment"] = news_sentiment

        # cold start 완화 — 작은 warmup (timeout 대폭 확대 금지)
        if bool(
            getattr(settings, "autotrading_ai_analysis_warmup_enabled", True)
        ) and provider == "ollama":
            out["warmup"] = await _warmup_ollama(settings)

        # TIMEOUT 이후 CIRCUIT_OPEN으로 FAILED 분석만 쌓이는 것 방지
        if provider == "ollama":
            circuit = _ollama_circuit_snapshot()
            out["circuit"] = circuit
            if not circuit.get("allow", True):
                out["ok"] = False
                out["skipped"] = True
                out["skip_reason"] = "OLLAMA_CIRCUIT_OPEN"
                out["error"] = "CIRCUIT_OPEN"
                return out

        try:
            created = self._svc.create(
                actor=ACTOR,
                reason="periodic UPBIT autotrading chart analysis (reference only)",
                analysis_type="SYMBOL_CHART",
                exchange_code=exchange,
                symbol=sym,
                timeframe=tf,
                execution_mode="EXTERNAL",
                provider_code=provider,
                model=model,
                # qwen3.5:4b 차트 JSON — think OFF + 1024 tokens (512는 thinking/본문 절단)
                max_tokens=int(
                    getattr(
                        settings,
                        "autotrading_ai_analysis_max_tokens",
                        1024,
                    )
                    or 1024
                ),
                timeout_sec=float(
                    getattr(
                        settings,
                        "autotrading_ai_analysis_timeout_seconds",
                        None,
                    )
                    or getattr(settings, "ollama_timeout_seconds", 180.0)
                    or 180.0
                ),
                fallback_enabled=False,
                idempotency_key=idem if not force else f"{idem}-f{int(now_utc.timestamp())}"[:64],
                force_new_version=True,
            )
        except AIMarketAnalysisError as exc:
            self._session.rollback()
            out["ok"] = False
            out["error"] = f"{exc.code}:{exc.message}"
            logger.warning(
                "autotrading_ai_analysis_create_failed",
                code=exc.code,
                message=exc.message,
                symbol=sym,
            )
            return out

        analysis = created.get("analysis") or {}
        analysis_id = int(analysis.get("id") or analysis.get("market_analysis_id") or 0)
        out["create"] = {
            "idempotent_replay": bool(created.get("idempotent_replay")),
            "market_analysis_id": analysis_id,
            "status": analysis.get("analysis_status") or analysis.get("status"),
        }
        if analysis_id <= 0:
            out["ok"] = False
            out["error"] = "CREATE_NO_ID"
            return out

        # 이미 validated면 execute 생략
        status = str(analysis.get("analysis_status") or analysis.get("status") or "")
        if status in {"VALIDATED_ANALYSIS", "VALIDATED_WITH_WARNINGS"} and not force:
            row = self._session.get(AIMarketAnalysisEntity, analysis_id)
            if row is not None:
                self._apply_enrichment(row, news_sentiment=news_sentiment, min_conf=min_conf)
                self._session.commit()
            out["ok"] = True
            out["executed"] = False
            out["validated"] = True
            out["market_analysis_id"] = analysis_id
            return out

        try:
            executed = await self._svc.execute(
                analysis_id,
                actor=ACTOR,
                confirm=True,
            )
        except AIMarketAnalysisError as exc:
            self._session.rollback()
            out["ok"] = False
            out["error"] = f"{exc.code}:{exc.message}"
            out["market_analysis_id"] = analysis_id
            logger.warning(
                "autotrading_ai_analysis_execute_failed",
                code=exc.code,
                message=exc.message,
                analysis_id=analysis_id,
            )
            return out

        row = self._session.get(AIMarketAnalysisEntity, analysis_id)
        if row is None:
            out["ok"] = False
            out["error"] = "ROW_MISSING_AFTER_EXECUTE"
            return out

        # FAILED/INVALID는 시장 HOLD로 enrichment하지 않음 (파싱 실패 구분)
        if row.analysis_status not in {
            "VALIDATED_ANALYSIS",
            "VALIDATED_WITH_WARNINGS",
        }:
            out.update(
                {
                    "ok": False,
                    "executed": True,
                    "validated": False,
                    "market_analysis_id": int(row.market_analysis_id),
                    "analysis_status": row.analysis_status,
                    "external_ai_called": bool(
                        executed.get("external_ai_called")
                    ),
                    "mock_called": bool(executed.get("mock_called")),
                    "error": f"ANALYSIS_NOT_VALIDATED:{row.analysis_status}",
                }
            )
            return out

        enrichment_ok = self._apply_enrichment(
            row, news_sentiment=news_sentiment, min_conf=min_conf
        )
        # malformed enrichment → validated 플래그만 false 표시 (status 유지)
        if not enrichment_ok:
            row.analysis_status = "VALIDATED_WITH_WARNINGS"
            warns = list(row.warnings or [])
            warns.append("GATE_ENRICHMENT_INVALID")
            row.warnings = warns

        self._session.commit()
        self._session.refresh(row)

        exec_info = executed.get("execution") or {}
        out.update(
            {
                "ok": row.analysis_status
                in {"VALIDATED_ANALYSIS", "VALIDATED_WITH_WARNINGS"},
                "executed": True,
                "validated": row.analysis_status
                in {"VALIDATED_ANALYSIS", "VALIDATED_WITH_WARNINGS"},
                "market_analysis_id": int(row.market_analysis_id),
                "analysis_status": row.analysis_status,
                "analysis_at": row.analyzed_at.isoformat() if row.analyzed_at else None,
                "confidence": row.confidence,
                "recommendation": (row.safe_result or {}).get("recommendation"),
                "risk_level": (row.safe_result or {}).get("risk_level"),
                "trend": row.trend_classification,
                "external_ai_called": bool(executed.get("external_ai_called")),
                "mock_called": bool(executed.get("mock_called")),
                "provider_used": row.provider_code,
                "model_used": row.model,
                "execution_latency_ms": exec_info.get("latency_ms")
                or exec_info.get("duration_ms"),
                "execution_request_id": row.execution_request_id,
                "enrichment_ok": enrichment_ok,
            }
        )
        logger.info(
            "autotrading_ai_analysis_completed",
            symbol=sym,
            analysis_id=row.market_analysis_id,
            status=row.analysis_status,
            recommendation=(row.safe_result or {}).get("recommendation"),
            external_ai_called=out["external_ai_called"],
        )
        return out

    def _apply_enrichment(
        self,
        row: AIMarketAnalysisEntity,
        *,
        news_sentiment: str,
        min_conf: float,
    ) -> bool:
        enriched = enrich_safe_result_for_gate(
            row.safe_result if isinstance(row.safe_result, dict) else {},
            news_sentiment=news_sentiment,
            min_confidence=min_conf,
        )
        # confidence를 top-level에 유지
        if enriched.get("confidence") is None and row.confidence is not None:
            enriched["confidence"] = row.confidence
        errors = validate_gate_recommendation_fields(enriched)
        row.safe_result = enriched
        return len(errors) == 0


def snapshot_latest_for_gate_lookup(
    session: Session,
    *,
    symbol: str = "KRW-XRP",
    ttl_seconds: float | None = None,
) -> dict[str, Any]:
    """AI Gate OFF 상태에서도 latest 분석 lookup 검증용."""

    settings = get_settings()
    ttl = float(
        ttl_seconds
        if ttl_seconds is not None
        else getattr(settings, "autotrading_ai_analysis_ttl_seconds", 900.0)
        or 900.0
    )
    row = find_latest_validated(
        session, exchange_code="UPBIT", symbol=symbol.upper()
    )
    if row is None:
        return {
            "status": "AI_ANALYSIS_MISSING",
            "fresh": False,
            "symbol": symbol.upper(),
        }
    fresh = is_analysis_fresh(row, ttl_seconds=ttl)
    safe = row.safe_result if isinstance(row.safe_result, dict) else {}
    return {
        "status": "AI_ANALYSIS_FOUND",
        "fresh": fresh,
        "symbol": symbol.upper(),
        "market_analysis_id": int(row.market_analysis_id),
        "analysis_at": row.analyzed_at.isoformat() if row.analyzed_at else None,
        "recommendation": safe.get("recommendation"),
        "confidence": row.confidence,
        "risk_level": safe.get("risk_level"),
        "news_sentiment": safe.get("news_sentiment"),
        "provider": row.provider_code,
        "model": row.model,
        "trend": row.trend_classification,
        "reasons": safe.get("reasons"),
        "summary": safe.get("summary"),
        "ttl_seconds": ttl,
    }
