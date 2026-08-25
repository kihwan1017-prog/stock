"""LLM Learning Center aggregation — reuses Dual LLM / RAG / Shadow engines."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from stock_platform.common.settings import get_settings
from stock_platform.operation.dual_llm.markets import (
    MARKET_KIWOOM,
    MARKET_UPBIT,
    market_of_payload,
    normalize_market,
)
from stock_platform.operation.dual_llm.prompt_versions import (
    ANALYSIS_KIWOOM_PROMPT_V1,
    TEACHER_KIWOOM_PROMPT_V1,
    TRADING_KIWOOM_PROMPT_V1,
)
from stock_platform.operation.kiwoom_dual_llm.clean_research import (
    classify_kiwoom_research_row,
    kiwoom_sample_stage,
)
from stock_platform.operation.upbit_market_context.dual_llm_runtime import (
    analysis_config,
    runtime_stats,
    teacher_config,
    trading_config,
)
from stock_platform.operation.upbit_market_context.entities import (
    UpbitLlmContextAnalysisEntity,
)
from stock_platform.operation.upbit_market_context.feedback_scoring import (
    aggregate_feedback_metrics,
)
from stock_platform.operation.upbit_market_context.learning_dataset import (
    export_jsonl_rows,
    sample_stage,
)
from stock_platform.operation.upbit_market_context.prompt_versions import (
    ANALYSIS_PROMPT_VERSION,
    TEACHER_PROMPT_VERSION,
    TRADING_PROMPT_VERSION,
    is_dual_llm_schema,
)
from stock_platform.operation.upbit_market_context.rag_retrieval import rag_cache
from stock_platform.operation.upbit_market_context.teacher_llm import teacher_rate_stats
from stock_platform.operation.upbit_opportunity_shadow.clean_forward_research import (
    assign_clean_forward_obs,
)
from stock_platform.operation.upbit_opportunity_shadow.constants import (
    SHADOW_STATUS_COMPLETED,
)
from stock_platform.operation.upbit_opportunity_shadow.entities import (
    UpbitOpportunityShadowEntity,
)
from stock_platform.operation.upbit_opportunity_shadow.ma_exit_forward_shadow.summary import (
    summarize_forward_shadow,
)

MARKET_ALL = "ALL"

STAGE_STATUS_KO = {
    "DONE": "완료",
    "IN_PROGRESS": "진행 중",
    "WAITING": "대기",
    "INSUFFICIENT": "표본 부족",
    "NA": "해당 없음",
}

PROGRESS_GATE_LABELS = {
    "collection": "0~29: 수집 중",
    "diagnostic": "30~99: 조기 진단",
    "primary": "100~499: 본 평가",
    "promotion": "500+: 승격 검토 가능 (자동 승격 없음)",
}

TEACHER_ERROR_CATEGORIES = frozenset(
    {
        "BAD_ENTRY",
        "EARLY_DUMP",
        "MISSED_WINNER",
        "FEE_CHURN",
        "TREND_REVERSAL",
        "GOOD_AVOIDANCE",
        "PARSE_ERROR",
        "LOW_CONFIDENCE",
        "UNKNOWN",
    }
)


def _row_market(row: UpbitLlmContextAnalysisEntity) -> str:
    inp = row.input_json if isinstance(row.input_json, dict) else {}
    out = row.output_json if isinstance(row.output_json, dict) else {}
    return market_of_payload(inp) or market_of_payload(out) or MARKET_UPBIT


def _filter_rows(
    session: Session,
    *,
    market: str,
    limit: int = 500,
) -> list[UpbitLlmContextAnalysisEntity]:
    rows = list(
        session.scalars(
            select(UpbitLlmContextAnalysisEntity)
            .order_by(desc(UpbitLlmContextAnalysisEntity.created_at))
            .limit(limit * 3 if market != MARKET_ALL else limit * 4)
        )
    )
    if market == MARKET_ALL:
        return rows[:limit]
    out: list[UpbitLlmContextAnalysisEntity] = []
    for r in rows:
        m = _row_market(r)
        if market == MARKET_UPBIT and m == MARKET_UPBIT:
            out.append(r)
        elif market == MARKET_KIWOOM and m == MARKET_KIWOOM:
            out.append(r)
        if len(out) >= limit:
            break
    return out


def _upbit_clean_count(session: Session) -> int:
    completed = list(
        session.scalars(
            select(UpbitOpportunityShadowEntity).where(
                UpbitOpportunityShadowEntity.deleted_at.is_(None),
                UpbitOpportunityShadowEntity.status == SHADOW_STATUS_COMPLETED,
            )
        )
    )
    return len(assign_clean_forward_obs(completed))


def _scan_dual_rows(
    rows: list[UpbitLlmContextAnalysisEntity],
    *,
    market: str,
) -> dict[str, Any]:
    """Dual LLM row scan — market isolated."""

    dual_n = predictions = outcomes = 0
    gold = silver = excluded = 0
    rag_hits = rag_with_ex = retrieval_count = 0
    teacher_reviews = 0
    feedback_rows: list[dict[str, Any]] = []
    parse_errors = 0
    rec_allow = rec_hold = rec_reduce = 0
    correct = wrong = unknown = 0

    for r in rows:
        m = _row_market(r)
        if market != MARKET_ALL and m != market:
            continue
        out = r.output_json if isinstance(r.output_json, dict) else {}
        if not is_dual_llm_schema(out.get("schema_version")):
            continue
        dual_n += 1
        trading = (
            out.get("trading_llm_shadow")
            if isinstance(out.get("trading_llm_shadow"), dict)
            else {}
        )
        if trading:
            predictions += 1
            rec = str(trading.get("recommendation") or "").upper()
            if rec == "ALLOW":
                rec_allow += 1
            elif rec == "HOLD":
                rec_hold += 1
            elif rec == "REDUCE":
                rec_reduce += 1
            if trading.get("parse_error") or trading.get("ok") is False:
                parse_errors += 1

        fb = out.get("feedback") if isinstance(out.get("feedback"), dict) else {}
        if fb:
            feedback_rows.append({"feedback": fb, "shadow_id": r.shadow_id})
            ao = fb.get("actual_outcome") if isinstance(fb.get("actual_outcome"), dict) else {}
            if ao.get("status") in {"COMPLETE", "CLOSED"} or ao.get("label"):
                outcomes += 1
            verd = str(fb.get("prediction_verdict") or "")
            if any(x in verd for x in ("SUCCESS", "AVOIDED", "AVOID")):
                correct += 1
            elif any(x in verd for x in ("DUMP", "MISS", "HARM", "NEUTRAL")):
                if "AVOID" in verd or "SUCCESS" in verd:
                    correct += 1
                elif verd:
                    wrong += 1
                else:
                    unknown += 1
            elif verd:
                unknown += 1

        rag = out.get("rag") if isinstance(out.get("rag"), dict) else {}
        retrieval_count += 1
        if rag.get("cache_hit"):
            rag_hits += 1
        ex = rag.get("examples")
        if isinstance(ex, list) and ex:
            rag_with_ex += 1

        teacher = out.get("teacher_review") if isinstance(out.get("teacher_review"), dict) else {}
        if teacher.get("ok"):
            teacher_reviews += 1

        tier = str(out.get("dataset_tier") or "")
        if tier == "GOLD":
            gold += 1
        elif tier == "SILVER":
            silver += 1
        elif tier == "EXCLUDED":
            excluded += 1

    clean_n = 0  # filled by _scan_dual_rows_with_session

    fb_metrics = aggregate_feedback_metrics(feedback_rows)
    corpus_size = gold + silver + excluded

    return {
        "dual_rows": dual_n,
        "clean": clean_n,
        "predictions": predictions,
        "outcomes": outcomes,
        "gold": gold,
        "silver": silver,
        "excluded": excluded,
        "corpus_size": corpus_size,
        "rag_retrieval_count": retrieval_count,
        "rag_hit": rag_hits,
        "rag_miss": max(retrieval_count - rag_hits, 0),
        "rag_with_examples": rag_with_ex,
        "teacher_reviews": teacher_reviews,
        "feedback_rows": feedback_rows,
        "feedback_metrics": fb_metrics,
        "parse_errors": parse_errors,
        "recommendation_distribution": {
            "ALLOW": rec_allow,
            "HOLD": rec_hold,
            "REDUCE": rec_reduce,
        },
        "outcome_linkage": {
            "correct_helpful": correct,
            "wrong_harmful": wrong,
            "unknown": unknown,
        },
    }


def _scan_dual_rows_with_session(
    session: Session,
    rows: list[UpbitLlmContextAnalysisEntity],
    *,
    market: str,
) -> dict[str, Any]:
    result = _scan_dual_rows(rows, market=market)
    if market == MARKET_KIWOOM:
        clean_n = 0
        for r in rows:
            inp = r.input_json if isinstance(r.input_json, dict) else {}
            out = r.output_json if isinstance(r.output_json, dict) else {}
            cls = classify_kiwoom_research_row(input_json=inp, output_json=out)
            if cls.get("clean"):
                clean_n += 1
        result["clean"] = clean_n
    elif market == MARKET_UPBIT:
        result["clean"] = _upbit_clean_count(session)
    elif market == MARKET_ALL:
        upbit_clean = _upbit_clean_count(session)
        kiwoom_clean = 0
        for r in rows:
            if _row_market(r) != MARKET_KIWOOM:
                continue
            inp = r.input_json if isinstance(r.input_json, dict) else {}
            out = r.output_json if isinstance(r.output_json, dict) else {}
            cls = classify_kiwoom_research_row(input_json=inp, output_json=out)
            if cls.get("clean"):
                kiwoom_clean += 1
        result["clean"] = upbit_clean + kiwoom_clean
        result["clean_by_market"] = {
            MARKET_UPBIT: upbit_clean,
            MARKET_KIWOOM: kiwoom_clean,
        }
    return result


def _progress_gate(clean_n: int) -> dict[str, Any]:
    n = int(clean_n or 0)
    if n < 30:
        gate = "collection"
    elif n < 100:
        gate = "diagnostic"
    elif n < 500:
        gate = "primary"
    else:
        gate = "promotion"
    return {
        "clean_sample_count": n,
        "gate": gate,
        "gate_label_ko": PROGRESS_GATE_LABELS[gate],
        "thresholds": {"30": "조기 진단", "100": "본 평가", "500": "승격 검토", "1000": "권장 표본"},
    }


def _safe_num(v: Any, default: int | float = 0) -> int | float:
    if v is None:
        return default
    if isinstance(v, (int, float)) and not (isinstance(v, float) and v != v):
        return v
    return default


def build_learning_stages(
    session: Session,
    *,
    market: str = MARKET_ALL,
) -> dict[str, Any]:
    """10단계 학습 진행 — 시장별."""

    rows = _filter_rows(session, market=market if market != MARKET_ALL else MARKET_ALL, limit=800)
    scan = _scan_dual_rows_with_session(session, rows, market=market)
    clean_n = int(scan.get("clean") or 0)
    forward_n = 0
    if market in {MARKET_UPBIT, MARKET_ALL}:
        fs = summarize_forward_shadow(session)
        forward_n = int((fs.get("baseline") or {}).get("sample_count") or 0)

    def st(count: int, done_at: int, progress_at: int = 1) -> str:
        if count <= 0:
            return STAGE_STATUS_KO["INSUFFICIENT"]
        if count >= done_at:
            return STAGE_STATUS_KO["DONE"]
        if count >= progress_at:
            return STAGE_STATUS_KO["IN_PROGRESS"]
        return STAGE_STATUS_KO["INSUFFICIENT"]

    stages = [
        {
            "id": "DATA_COLLECTION",
            "label_ko": "① 데이터 수집",
            "status_ko": st(clean_n, 30, 1),
        },
        {
            "id": "CLEAN_JUDGMENT",
            "label_ko": "② CLEAN 판정",
            "status_ko": st(clean_n, 1, 1),
        },
        {
            "id": "RAG_USAGE",
            "label_ko": "③ RAG 활용",
            "status_ko": (
                STAGE_STATUS_KO["DONE"]
                if scan.get("rag_with_examples", 0) > 0
                else STAGE_STATUS_KO["IN_PROGRESS"]
                if scan.get("dual_rows", 0) > 0
                else STAGE_STATUS_KO["WAITING"]
            ),
        },
        {
            "id": "FEEDBACK_EVAL",
            "label_ko": "④ Feedback 평가",
            "status_ko": st(int(scan.get("outcomes") or 0), 1, 1),
        },
        {
            "id": "TEACHER_REVIEW",
            "label_ko": "⑤ Teacher 검토",
            "status_ko": st(int(scan.get("teacher_reviews") or 0), 1, 1),
        },
        {
            "id": "FORWARD_SHADOW",
            "label_ko": "⑥ Forward Shadow",
            "status_ko": (
                STAGE_STATUS_KO["NA"]
                if market == MARKET_KIWOOM
                else st(forward_n, 30, 1)
            ),
        },
        {
            "id": "LORA_DATASET",
            "label_ko": "⑦ LoRA Dataset",
            "status_ko": st(int(scan.get("gold") or 0) + int(scan.get("silver") or 0), 1, 1),
        },
        {
            "id": "LORA_TRAINING",
            "label_ko": "⑧ LoRA Training",
            "status_ko": STAGE_STATUS_KO["WAITING"],
            "note": "TRAINING_STARTED=NO · 자동 학습 금지",
        },
        {
            "id": "VALIDATION",
            "label_ko": "⑨ Validation",
            "status_ko": st(clean_n, 500, 100),
        },
        {
            "id": "PROMOTION_REVIEW",
            "label_ko": "⑩ Promotion 검토",
            "status_ko": (
                STAGE_STATUS_KO["IN_PROGRESS"]
                if clean_n >= 500
                else STAGE_STATUS_KO["WAITING"]
            ),
            "note": "자동 승격 없음",
        },
    ]
    return {
        "schema": "llm_learning_stages_v1",
        "market": market,
        "stages": stages,
        "progress_gate": _progress_gate(clean_n),
    }


def build_market_samples(
    session: Session,
    *,
    market: str,
) -> dict[str, Any]:
    m = normalize_market(market) or MARKET_UPBIT
    rows = _filter_rows(session, market=m, limit=500)
    scan = _scan_dual_rows_with_session(session, rows, market=m)
    stage = (
        kiwoom_sample_stage(int(scan["clean"]))
        if m == MARKET_KIWOOM
        else sample_stage(int(scan["clean"]))
    )
    forward_n = 0
    if m == MARKET_UPBIT:
        fs = summarize_forward_shadow(session)
        forward_n = int((fs.get("baseline") or {}).get("sample_count") or 0)

    return {
        "schema": "llm_learning_samples_v1",
        "market": m,
        "CLEAN": int(scan.get("clean") or 0),
        "predictions": int(scan.get("predictions") or 0),
        "outcomes": int(scan.get("outcomes") or 0),
        "gold": int(scan.get("gold") or 0),
        "silver": int(scan.get("silver") or 0),
        "excluded": int(scan.get("excluded") or 0),
        "forward_shadow": forward_n if m == MARKET_UPBIT else None,
        "sample_stage": stage,
        "progress_gate": _progress_gate(int(scan.get("clean") or 0)),
        "CROSS_MARKET_RAG": 0,
    }


def build_quality_panel(
    session: Session,
    *,
    market: str = MARKET_ALL,
) -> dict[str, Any]:
    rows = _filter_rows(session, market=market, limit=500)
    scan = _scan_dual_rows_with_session(session, rows, market=market)
    stats = runtime_stats()
    s = get_settings()
    a_cfg = analysis_config()
    t_cfg = trading_config()
    te_cfg = teacher_config()

    if market == MARKET_KIWOOM:
        prompts = {
            "analysis": ANALYSIS_KIWOOM_PROMPT_V1,
            "trading": TRADING_KIWOOM_PROMPT_V1,
            "teacher": TEACHER_KIWOOM_PROMPT_V1,
        }
    else:
        prompts = {
            "analysis": ANALYSIS_PROMPT_VERSION,
            "trading": TRADING_PROMPT_VERSION,
            "teacher": TEACHER_PROMPT_VERSION,
        }

    sample_n = int(scan.get("dual_rows") or 0)
    fb = scan.get("feedback_metrics") or {}

    return {
        "schema": "llm_learning_quality_v1",
        "market": market,
        "analysis": {
            "model": a_cfg.model,
            "prompt_version": prompts["analysis"],
            "sample_n": sample_n,
            "calls": stats["analysis_calls"],
            "timeouts": stats["analysis_timeout"],
            "parse_errors": stats["analysis_error"],
            "median_latency_ms": stats["analysis_median_latency_ms"],
        },
        "trading": {
            "model": t_cfg.model,
            "prompt_version": prompts["trading"],
            "mode": "SHADOW",
            "sample_n": int(scan.get("predictions") or 0),
            "calls": stats["trading_shadow_calls"],
            "timeouts": stats["trading_shadow_timeout"],
            "parse_errors": int(scan.get("parse_errors") or 0),
            "median_latency_ms": stats["trading_median_latency_ms"],
            "recommendation_distribution": scan.get("recommendation_distribution"),
            "outcome_linkage": scan.get("outcome_linkage"),
            "accuracy_note": "근거 있는 outcome 연결만 집계 — 추정 정확도 없음",
        },
        "teacher": {
            "model": te_cfg.model,
            "prompt_version": prompts["teacher"],
            "sample_n": int(scan.get("teacher_reviews") or 0),
            "calls": stats["teacher_calls"],
            "timeouts": stats["teacher_timeout"],
            "parse_errors": stats["teacher_error"],
            "median_latency_ms": stats["teacher_median_latency_ms"],
            "review_rate": teacher_rate_stats().get("review_rate"),
        },
        "feedback_summary": {
            "total_predictions": fb.get("total_predictions", 0),
            "NET_FILTER_BENEFIT": fb.get("NET_FILTER_BENEFIT"),
        },
        "REAL_GATE": "NO",
        "teacher_enabled": bool(s.teacher_llm_enabled),
    }


def build_summary(
    session: Session,
    *,
    market: str = MARKET_ALL,
) -> dict[str, Any]:
    """Top summary — lazy-friendly aggregate."""

    m = market if market in {MARKET_ALL, MARKET_UPBIT, MARKET_KIWOOM} else MARKET_ALL
    rows = _filter_rows(session, market=m, limit=500)
    scan = _scan_dual_rows_with_session(session, rows, market=m)
    stats = runtime_stats()
    t_rate = teacher_rate_stats()
    s = get_settings()
    a_cfg = analysis_config()
    t_cfg = trading_config()
    te_cfg = teacher_config()
    fb = scan.get("feedback_metrics") or {}

    rag_total = max(rag_cache.hits + rag_cache.misses, 1)
    markets_payload: dict[str, Any] = {}
    if m == MARKET_ALL:
        for mk in (MARKET_UPBIT, MARKET_KIWOOM):
            mk_rows = _filter_rows(session, market=mk, limit=300)
            mk_scan = _scan_dual_rows_with_session(session, mk_rows, market=mk)
            markets_payload[mk] = build_market_samples(session, market=mk)

    lora = build_lora_readiness(session, market=m)

    return {
        "schema": "llm_learning_summary_v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "market": m,
        "CROSS_MARKET_RAG": 0,
        "models": {
            "ANALYSIS": a_cfg.model,
            "TRADING": t_cfg.model,
            "TEACHER": te_cfg.model,
        },
        "analysis": {
            "model": a_cfg.model,
            "calls": stats["analysis_calls"],
            "samples": int(scan.get("dual_rows") or 0),
            "median_latency_ms": stats["analysis_median_latency_ms"],
            "errors": stats["analysis_error"] + stats["analysis_timeout"],
        },
        "trading": {
            "model": t_cfg.model,
            "mode": "SHADOW",
            "predictions": int(scan.get("predictions") or 0),
            "outcomes": int(scan.get("outcomes") or 0),
            "accuracy_benefit": fb.get("NET_FILTER_BENEFIT"),
            "accuracy_note": "outcome 연결 기반 benefit만 — 임의 정확도 없음",
        },
        "teacher": {
            "model": te_cfg.model,
            "reviews": int(scan.get("teacher_reviews") or 0),
            "review_rate": t_rate.get("review_rate"),
            "key_findings_count": int(scan.get("teacher_reviews") or 0),
        },
        "rag": {
            "corpus_size": int(scan.get("corpus_size") or 0),
            "gold": int(scan.get("gold") or 0),
            "silver": int(scan.get("silver") or 0),
            "excluded": int(scan.get("excluded") or 0),
            "retrieval_count": int(scan.get("rag_retrieval_count") or 0),
            "hit": int(scan.get("rag_hit") or 0),
            "miss": int(scan.get("rag_miss") or 0),
            "hit_rate_runtime": round(rag_cache.hits / rag_total, 4),
            "implemented": True,
        },
        "lora": lora.get("summary", {}),
        "learning_stages": build_learning_stages(session, market=m).get("stages"),
        "samples": build_market_samples(session, market=m if m != MARKET_ALL else MARKET_UPBIT),
        "markets": markets_payload if m == MARKET_ALL else None,
        "safety": {
            "REAL_ORDER_MUTATION": 0,
            "REAL_POLICY_MUTATION": 0,
            "LLM_REAL_GATE_MUTATION": 0,
            "LORA_TRAINING_STARTED": False,
            "KIWOOM_REAL_MUTATION": 0,
            "UPBIT_REAL_MUTATION": 0,
            "research_only": True,
            "dual_llm_ollama_enabled": bool(s.dual_llm_ollama_enabled),
            "trading_llm_shadow_enabled": bool(s.trading_llm_shadow_enabled),
        },
    }


def _map_teacher_category(
    *,
    teacher: dict[str, Any],
    feedback: dict[str, Any],
    trading: dict[str, Any],
) -> str:
    codes = teacher.get("reason_codes") or []
    if isinstance(codes, list):
        for c in codes:
            cu = str(c).upper()
            if cu in TEACHER_ERROR_CATEGORIES:
                return cu
    verd = str(feedback.get("prediction_verdict") or "").upper()
    if "EARLY_DUMP" in verd or "DUMP" in verd:
        return "EARLY_DUMP"
    if "MISSED_WINNER" in verd:
        return "MISSED_WINNER"
    if "FEE" in verd or "CHURN" in verd:
        return "FEE_CHURN"
    if "AVOID" in verd:
        return "GOOD_AVOIDANCE"
    if trading.get("ok") is False or trading.get("parse_error"):
        return "PARSE_ERROR"
    conf = trading.get("confidence")
    if conf is not None and float(conf) < 0.4:
        return "LOW_CONFIDENCE"
    return "UNKNOWN"


def build_teacher_findings(
    session: Session,
    *,
    market: str = MARKET_ALL,
    limit: int = 50,
    offset: int = 0,
) -> dict[str, Any]:
    rows = _filter_rows(session, market=market, limit=400)
    items: list[dict[str, Any]] = []
    for r in rows:
        out = r.output_json if isinstance(r.output_json, dict) else {}
        teacher = out.get("teacher_review") if isinstance(out.get("teacher_review"), dict) else {}
        if not teacher.get("ok"):
            continue
        analysis = out.get("analysis_llm") if isinstance(out.get("analysis_llm"), dict) else {}
        trading = (
            out.get("trading_llm_shadow")
            if isinstance(out.get("trading_llm_shadow"), dict)
            else {}
        )
        fb = out.get("feedback") if isinstance(out.get("feedback"), dict) else {}
        ao = fb.get("actual_outcome") if isinstance(fb.get("actual_outcome"), dict) else {}
        items.append(
            {
                "analysis_id": int(r.analysis_id),
                "symbol": r.symbol,
                "market": _row_market(r),
                "time": r.created_at.isoformat() if r.created_at else None,
                "analysis_result": {
                    "recommendation": analysis.get("recommendation"),
                    "summary": analysis.get("market_summary"),
                    "model": analysis.get("model"),
                    "prompt_version": analysis.get("prompt_version"),
                },
                "trading_result": {
                    "recommendation": trading.get("recommendation"),
                    "confidence": trading.get("confidence"),
                    "model": trading.get("model"),
                    "prompt_version": trading.get("prompt_version"),
                },
                "actual_outcome": ao,
                "teacher_comment": {
                    "analysis_quality": teacher.get("analysis_quality"),
                    "trading_decision_quality": teacher.get("trading_decision_quality"),
                    "preferred_recommendation": teacher.get("preferred_recommendation"),
                    "missed_risk_flags": teacher.get("missed_risk_flags"),
                    "reason_codes": teacher.get("reason_codes"),
                    "model": teacher.get("model"),
                },
                "error_category": _map_teacher_category(
                    teacher=teacher, feedback=fb, trading=trading
                ),
            }
        )
    total = len(items)
    page = items[offset : offset + limit]
    return {
        "schema": "llm_learning_teacher_reviews_v1",
        "market": market,
        "items": page,
        "total": total,
        "offset": offset,
        "limit": limit,
    }


def build_forward_shadow_panel(session: Session) -> dict[str, Any]:
    summary = summarize_forward_shadow(session)
    return {
        "schema": "llm_learning_forward_shadow_v1",
        "market": MARKET_UPBIT,
        "research_only": True,
        "REAL_APPLIED": False,
        "rule": "MA_DEAD_CROSS_CONFIRM2",
        "rule_version": "ma_dead_cross_confirm2_v1",
        "summary": summary,
        "disclaimer_ko": "연구용 / REAL 미적용",
    }


def build_lora_readiness(
    session: Session,
    *,
    market: str = MARKET_ALL,
) -> dict[str, Any]:
    """LoRA dataset readiness — export only, training forbidden."""

    def _role_ready(mk: str) -> dict[str, Any]:
        rows = _filter_rows(session, market=mk, limit=1000)
        scan = _scan_dual_rows_with_session(session, rows, market=mk)
        clean_n = int(scan.get("clean") or 0)
        examples: list[dict[str, Any]] = []
        for r in rows:
            out = r.output_json if isinstance(r.output_json, dict) else {}
            le = out.get("learning_example")
            if isinstance(le, dict):
                examples.append(le)
        analysis_export = export_jsonl_rows(examples, kind="analysis", clean_n=clean_n)
        trading_export = export_jsonl_rows(examples, kind="trading", clean_n=clean_n)
        ready = clean_n >= 500 and int(scan.get("gold") or 0) >= 10
        return {
            "market": mk,
            "clean_n": clean_n,
            "gold": int(scan.get("gold") or 0),
            "silver": int(scan.get("silver") or 0),
            "excluded": int(scan.get("excluded") or 0),
            "analysis": {
                "dataset_n": analysis_export.get("line_count", 0),
                "gold": int(scan.get("gold") or 0),
                "silver": int(scan.get("silver") or 0),
                "excluded": int(scan.get("excluded") or 0),
                "ready": ready,
                "export_mode": analysis_export.get("export_mode"),
            },
            "trading": {
                "dataset_n": trading_export.get("line_count", 0),
                "gold": int(scan.get("gold") or 0),
                "silver": int(scan.get("silver") or 0),
                "excluded": int(scan.get("excluded") or 0),
                "ready": ready,
                "export_mode": trading_export.get("export_mode"),
            },
            "export_urls": {
                "analysis": f"/api/v1/admin/{mk.lower()}/dual-llm/export/analysis",
                "trading": f"/api/v1/admin/{mk.lower()}/dual-llm/export/trading",
            },
        }

    mk_list = [MARKET_UPBIT, MARKET_KIWOOM] if market == MARKET_ALL else [market]
    by_market = {mk: _role_ready(mk) for mk in mk_list}
    return {
        "schema": "llm_learning_lora_readiness_v1",
        "market": market,
        "LORA_TRAINING_STARTED": False,
        "training_button_enabled": False,
        "auto_training_forbidden": True,
        "by_market": by_market,
        "summary": {
            "ready_any": any(v["analysis"]["ready"] or v["trading"]["ready"] for v in by_market.values()),
            "LORA_TRAINING_STARTED": False,
        },
    }


__all__ = [
    "MARKET_ALL",
    "MARKET_UPBIT",
    "MARKET_KIWOOM",
    "build_summary",
    "build_market_samples",
    "build_teacher_findings",
    "build_forward_shadow_panel",
    "build_lora_readiness",
    "build_learning_stages",
    "build_quality_panel",
]
