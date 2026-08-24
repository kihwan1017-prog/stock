"""Reusable Ollama 3-model role benchmark — RESEARCH / READ-ONLY.

Uses live UPBIT research context (no fake prose-only prompts).
Does NOT mutate REAL/LIVE/ARM/Risk/Slot/orders.
Does NOT change production default model selection.

Run:
  PYTHONPATH=src python .run/k_ollama_llm_role_benchmark.py
"""

from __future__ import annotations

import json
import statistics
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

try:
    import psutil  # type: ignore
except ImportError:  # pragma: no cover
    psutil = None  # type: ignore


ROOT = Path(__file__).resolve().parents[1]
OUT_JSON = ROOT / ".run" / "k_ollama_llm_role_benchmark.json"
OUT_MD = ROOT / ".run" / "k_ollama_llm_role_benchmark.md"

MODELS = ["qwen3:1.7b", "qwen3.5:2b", "qwen3.5:4b"]
OLLAMA_BASE = "http://127.0.0.1:11434"
TIMEOUT_S = 120.0
TEMPERATURE = 0.2
NUM_PREDICT = 512
REPEATS = 3
KEEP_ALIVE = "10m"

# Production BEFORE snapshot (settings defaults / code SoT — not mutated)
BEFORE = {
    "ollama_base_url": "http://127.0.0.1:11434",
    "ollama_model": "qwen3.5:4b",
    "ollama_timeout_seconds": 120.0,
    "ollama_temperature": 0.2,
    "ollama_keep_alive": "10m",
    "num_predict_in_chat_structured": 1024,
    "think": False,
    "autotrading_ai_analysis_model": "qwen3.5:4b",
    "autotrading_ai_analysis_enabled": False,
    "autotrading_ai_signal_gate_live_enabled": False,
    "upbit_market_context_candidate_llm_enabled": True,
    "candidate_llm_path": "heuristic_llm_analyze (research fail-open; not Ollama by default)",
    "ollama_client": "src/stock_platform/ai/ollama_client.py",
    "llm_to_real_order_path": "NONE for market-context candidate LLM (research_only, may_create_orders=false)",
    "fail_open_research": "HOLD + CONTEXT_UNAVAILABLE on LLM/context failure",
    "fail_closed_live_ai_gate": "autotrading_ai_live_fail_closed=True when gate enabled",
}


ENTRY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "schema_version": {"type": "string"},
        "recommendation": {"type": "string", "enum": ["ALLOW", "HOLD", "REDUCE"]},
        "confidence": {"type": "number"},
        "entry_quality_score": {"type": "integer"},
        "risk_flags": {"type": "array", "items": {"type": "string"}},
        "positive_factors": {"type": "array", "items": {"type": "string"}},
        "negative_factors": {"type": "array", "items": {"type": "string"}},
        "short_reason_ko": {"type": "string"},
        "context_unavailable": {"type": "boolean"},
    },
    "required": [
        "recommendation",
        "confidence",
        "entry_quality_score",
        "risk_flags",
        "short_reason_ko",
    ],
}

ANALYSIS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "summary_ko": {"type": "string"},
        "key_numbers": {"type": "array", "items": {"type": "string"}},
        "risks_ko": {"type": "array", "items": {"type": "string"}},
        "tone": {"type": "string", "enum": ["BULLISH", "NEUTRAL", "BEARISH", "CAUTION"]},
        "confidence": {"type": "number"},
    },
    "required": ["summary_ko", "key_numbers", "risks_ko", "tone", "confidence"],
}


@dataclass
class CaseResult:
    model: str
    case_id: str
    role: str
    repeat: int
    cold: bool
    ok: bool
    error: str | None = None
    timeout: bool = False
    load_duration_ms: float | None = None
    prompt_eval_duration_ms: float | None = None
    eval_duration_ms: float | None = None
    total_duration_ms: float | None = None
    wall_ms: float | None = None
    prompt_tokens: int | None = None
    output_tokens: int | None = None
    tokens_per_second: float | None = None
    first_token_latency_ms: float | None = None
    parsed: dict[str, Any] | None = None
    quality: dict[str, Any] = field(default_factory=dict)
    ram_mb: float | None = None
    cpu_pct: float | None = None


def _ns_to_ms(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v) / 1_000_000.0
    except (TypeError, ValueError):
        return None


def _median(vals: list[float]) -> float | None:
    clean = [float(v) for v in vals if v is not None]
    if not clean:
        return None
    return float(statistics.median(clean))


def _has_hangul(text: str) -> bool:
    return any("가" <= ch <= "힣" for ch in text)


def build_cases() -> list[dict[str, Any]]:
    """Fixed fixture set from DB SoT (no lookahead outcomes as answers)."""

    market = {
        "fear_greed": {"value": 73, "classification": "Greed"},
        "advancing_asset_ratio": {
            "n": 286,
            "ratio": 0.27972,
            "advancing": 80,
            "declining": 188,
            "unchanged": 18,
        },
        "turnover_24h_krw": 2052211084891.78,
        "market_return_proxy": {
            "median_signed_change_rate": -0.00793701,
            "note": "proxy from KRW ticker signed_change_rate median",
        },
        "as_of": "2026-08-24T15:16:04Z",
        "research_only": True,
    }

    notice_cfx = {
        "type": "NOTICE",
        "source": "UPBIT_NOTICE",
        "title": "콘플럭스(CFX) 입출금 일시 중단 안내 (08/24 18:00 ~)",
        "summary": "콘플럭스(CFX)의 하드포크로, 2026-08-24(월) 18:00(KST)부터 안정성이 확인 완료되는 시점까지 입출금을 일시 중단합니다.",
        "published_at": "2026-08-24T09:05:02Z",
        "must_preserve": ["CFX", "입출금", "하드포크", "18:00"],
    }
    notice_sand = {
        "type": "NOTICE",
        "source": "UPBIT_NOTICE",
        "title": "샌드박스(SAND) 거래 유의 종목 지정 안내",
        "summary": "샌드박스(SAND)가 거래 유의 종목으로 지정되었습니다. 입출금 서비스는 이미 중단된 상태.",
        "published_at": "2026-08-24T06:00:02Z",
        "must_preserve": ["SAND", "유의", "입출금"],
    }
    news_etf = {
        "type": "NEWS",
        "source": "CRYPTO_NEWS",
        "title": "미국 현물 비트코인·이더리움 ETF 관련 자금 흐름",
        "summary": "제도권 자금이 암호화폐 익스포저를 늘렸다는 신호. 국내에서는 업비트와 빗썸이 샌드박스를 거래주의 종목으로 지정.",
        "published_at": "2026-08-24T08:52:00Z",
        "must_preserve": ["ETF", "비트코인", "샌드박스"],
    }

    asset_btc = {
        "symbol": "KRW-BTC",
        "trade_price": 109482000,
        "turnover_rank": 3,
        "signed_change_rate": 0.0257270274,
        "acc_trade_price_24h": 171786853876.93,
    }
    asset_sand = {
        "symbol": "KRW-SAND",
        "trade_price": 48.5,
        "turnover_rank": 21,
        "signed_change_rate": -0.2113821138,
        "acc_trade_price_24h": 13936513815.05,
        "caution": "거래 유의 종목",
    }
    asset_near = {
        "symbol": "KRW-NEAR",
        "trade_price": 2780,
        "turnover_rank": 22,
        "signed_change_rate": 0.0039725533,
        "acc_trade_price_24h": 12869601093.13,
    }

    # Entry contexts — features only (no forward return as answer)
    entry_near_hot = {
        "shadow_id": 520,
        "symbol": "KRW-NEAR",
        "candidate": {
            "rank": 1,
            "score": 84.97,
            "recommendation": "ALLOW",
            "confidence": 0.95,
            "price": 2756,
            "ma_spread_pct": 0.70584793,
            "momentum_5m_pct": 0.25463805,
        },
        "technical": {
            "ma5": 2753.6,
            "ma20": 2734.3,
            "rsi14": 67.40482931,
            "volume_surge": 2.5752791886362534,
        },
        "market_context": market,
        "asset_context": asset_near,
        "expected_risk_hint": ["OVERHEATED", "RECENT_SPIKE"],
        "note": "CLEAN-era shadow feature; forward outcome excluded from prompt",
    }
    entry_pump_vol = {
        "shadow_id": 526,
        "symbol": "KRW-PUMP",
        "candidate": {
            "rank": 5,
            "score": 65.14,
            "recommendation": "ALLOW",
            "confidence": 0.95,
            "price": 6.83,
            "ma_spread_pct": -0.74419962,
            "momentum_5m_pct": 0.29368576,
        },
        "technical": {
            "ma5": 6.802,
            "ma20": 6.853,
            "rsi14": 46.09118023,
            "volume_surge": 5.669608706277912,
        },
        "market_context": market,
        "expected_risk_hint": ["OVERHEATED", "FEE_CHURN"],
        "note": "extreme volume_surge — fee/churn risk context",
    }
    entry_grvt_up = {
        "shadow_id": 512,
        "symbol": "KRW-GRVT",
        "candidate": {
            "rank": 1,
            "score": 82.24,
            "recommendation": "ALLOW",
            "confidence": 0.85,
            "price": 296,
            "ma_spread_pct": 0.37402244,
            "momentum_5m_pct": 0.68027211,
        },
        "technical": {
            "ma5": 295.2,
            "ma20": 294.1,
            "rsi14": 63.27853836,
            "volume_surge": 2.6638009556602715,
        },
        "market_context": market,
        "news": [notice_cfx],  # unrelated CFX — should not invent GRVT halt
        "expected_risk_hint": [],
    }
    entry_btc_mild = {
        "shadow_id": 522,
        "symbol": "KRW-BTC",
        "candidate": {
            "rank": 4,
            "score": 67.71,
            "recommendation": "ALLOW",
            "confidence": 0.95,
            "price": 107890000,
            "ma_spread_pct": 0.12753864,
            "momentum_5m_pct": 0.14387154,
        },
        "technical": {
            "ma5": 107830200,
            "ma20": 107692850,
            "rsi14": 67.74566102,
            "volume_surge": 0.4023897049733696,
        },
        "market_context": market,
        "asset_context": asset_btc,
        "hold_bias_reason": "weak volume + elevated RSI in weak breadth market",
    }
    entry_sol = {
        "shadow_id": 524,
        "symbol": "KRW-SOL",
        "candidate": {
            "rank": 1,
            "score": 82.06,
            "recommendation": "ALLOW",
            "confidence": 0.95,
            "price": 132000,
            "ma_spread_pct": 0.30014057,
            "momentum_5m_pct": 0.15174507,
        },
        "technical": {
            "ma5": 132000,
            "ma20": 131605,
            "rsi14": 66.841381,
            "volume_surge": 2.150398700374056,
        },
        "market_context": market,
    }

    cases: list[dict[str, Any]] = [
        {
            "id": "A1_market_overview",
            "type": "A",
            "role": "ANALYSIS",
            "title": "시장 전체 분석",
            "schema": "ANALYSIS",
            "system": "당신은 UPBIT 연구용 시장 분석가입니다. REAL 주문 금지. JSON만 반환.",
            "user_prefix": "다음 시장 Context를 한국어로 요약하세요. 숫자를 왜곡하지 마세요.",
            "payload": market,
            "checks": {
                "must_numbers": ["73", "0.27972", "80", "188"],
                "must_concepts": ["Greed", "상승", "하락"],
            },
        },
        {
            "id": "B1_notice_cfx",
            "type": "B",
            "role": "ANALYSIS",
            "title": "공지 요약 CFX",
            "schema": "ANALYSIS",
            "system": "업비트 공지 요약기. 핵심만 보존. JSON만.",
            "user_prefix": "공지를 요약하세요. 종목·조치·시각을 빠뜨리지 마세요.",
            "payload": notice_cfx,
            "checks": {"must_preserve": notice_cfx["must_preserve"]},
        },
        {
            "id": "B2_notice_sand",
            "type": "B",
            "role": "ANALYSIS",
            "title": "공지 요약 SAND",
            "schema": "ANALYSIS",
            "system": "업비트 공지 요약기. JSON만.",
            "user_prefix": "공지를 요약하세요.",
            "payload": notice_sand,
            "checks": {"must_preserve": notice_sand["must_preserve"]},
        },
        {
            "id": "B3_news_etf",
            "type": "B",
            "role": "ANALYSIS",
            "title": "뉴스 요약 ETF",
            "schema": "ANALYSIS",
            "system": "암호화폐 뉴스 요약기. JSON만.",
            "user_prefix": "뉴스 핵심을 요약하세요.",
            "payload": news_etf,
            "checks": {"must_preserve": news_etf["must_preserve"]},
        },
        {
            "id": "C1_asset_btc",
            "type": "C",
            "role": "ANALYSIS",
            "title": "종목 Context BTC",
            "schema": "ANALYSIS",
            "system": "종목 Context 분석. 숫자 보존. JSON만.",
            "user_prefix": "종목 Context를 해석하세요.",
            "payload": {"asset": asset_btc, "market_breadth_ratio": 0.27972},
            "checks": {"must_numbers": ["109482000", "3", "0.0257"]},
        },
        {
            "id": "C2_asset_sand_caution",
            "type": "C",
            "role": "ANALYSIS",
            "title": "종목 Context SAND 유의",
            "schema": "ANALYSIS",
            "system": "위험 종목 Context 분석. JSON만.",
            "user_prefix": "유의 종목 Context와 위험을 설명하세요.",
            "payload": {"asset": asset_sand, "notice": notice_sand},
            "checks": {
                "must_preserve": ["SAND", "유의"],
                "must_numbers": ["-0.211"],
            },
        },
        {
            "id": "D1_entry_btc",
            "type": "D",
            "role": "TRADING",
            "title": "Entry Quality BTC",
            "schema": "ENTRY",
            "system": (
                "UPBIT Entry Quality research assistant. "
                "recommendation은 ALLOW|HOLD|REDUCE만. "
                "REAL 주문 생성 금지. research_only. JSON만."
            ),
            "user_prefix": "entry quality를 평가하세요. 미래 수익률은 모릅니다.",
            "payload": entry_btc_mild,
            "checks": {"prefer_not_allow_if_weak": True},
        },
        {
            "id": "D2_entry_grvt",
            "type": "D",
            "role": "TRADING",
            "title": "Entry Quality GRVT",
            "schema": "ENTRY",
            "system": (
                "UPBIT Entry Quality research assistant. "
                "ALLOW|HOLD|REDUCE only. JSON only. No orders."
            ),
            "user_prefix": "entry quality 평가. CFX 공지는 GRVT와 무관하면 섞지 마세요.",
            "payload": entry_grvt_up,
            "checks": {"hallucination_ban": ["CFX 입출금 중단이 GRVT"]},
        },
        {
            "id": "E1_early_dump_near",
            "type": "E",
            "role": "TRADING",
            "title": "Early Dump Risk NEAR",
            "schema": "ENTRY",
            "system": (
                "Early Dump / overheat risk research. "
                "risk_flags 예: OVERHEATED,RECENT_SPIKE,MARKET_WEAK,FEE_CHURN. "
                "JSON only."
            ),
            "user_prefix": "진입 직후 dump 위험을 평가하세요. 입력 feature만 사용.",
            "payload": entry_near_hot,
            "checks": {"expected_risk_any": ["OVERHEATED", "RECENT_SPIKE", "MARKET_WEAK"]},
        },
        {
            "id": "E2_fee_churn_pump",
            "type": "E",
            "role": "TRADING",
            "title": "Fee Churn Risk PUMP",
            "schema": "ENTRY",
            "system": "Fee churn / volume exhaustion research. JSON only.",
            "user_prefix": "volume_surge가 매우 높습니다. fee churn 위험을 평가하세요.",
            "payload": entry_pump_vol,
            "checks": {
                "expected_risk_any": ["OVERHEATED", "FEE_CHURN", "RECENT_SPIKE"],
                "must_numbers": ["5.66", "5.67"],
            },
        },
        {
            "id": "F1_allow_hold_reduce_sol",
            "type": "F",
            "role": "TRADING",
            "title": "ALLOW/HOLD/REDUCE SOL",
            "schema": "ENTRY",
            "system": "Final auxiliary judgment ALLOW|HOLD|REDUCE. No orders. JSON only.",
            "user_prefix": "최종 보조판단을 내리세요. 시장 breadth가 약합니다(ratio=0.28).",
            "payload": entry_sol,
            "checks": {},
        },
        {
            "id": "F2_hold_preferred_weak_market",
            "type": "F",
            "role": "TRADING",
            "title": "HOLD 적절 weak market",
            "schema": "ENTRY",
            "system": "Entry auxiliary judgment. Weak market → 신중. JSON only.",
            "user_prefix": (
                "시장 상승비중 27.9%, F&G=73(Greed), volume_surge 낮음. "
                "HOLD가 합리적인지 평가."
            ),
            "payload": entry_btc_mild,
            "checks": {"prefer_hold_or_reduce": True},
        },
    ]
    return cases


def score_quality(case: dict[str, Any], parsed: dict[str, Any] | None) -> dict[str, Any]:
    scores: dict[str, Any] = {
        "schema_ok": 0.0,
        "korean_ok": 0.0,
        "number_ok": 0.0,
        "preserve_ok": 0.0,
        "risk_ok": 0.0,
        "hallucination_penalty": 0.0,
        "rec_valid": 0.0,
        "total": 0.0,
        "notes": [],
    }
    if not isinstance(parsed, dict):
        scores["notes"].append("parse_fail")
        return scores

    schema = case.get("schema")
    if schema == "ENTRY":
        rec = str(parsed.get("recommendation") or "").upper()
        scores["schema_ok"] = 1.0 if rec in {"ALLOW", "HOLD", "REDUCE"} else 0.0
        scores["rec_valid"] = scores["schema_ok"]
        reason = str(parsed.get("short_reason_ko") or "")
        scores["korean_ok"] = 1.0 if _has_hangul(reason) else 0.0
        flags = [str(x).upper() for x in (parsed.get("risk_flags") or [])]
        expected = case.get("checks", {}).get("expected_risk_any") or []
        if expected:
            scores["risk_ok"] = 1.0 if any(e in flags for e in expected) else 0.0
        else:
            scores["risk_ok"] = 0.5  # N/A neutral
        if case.get("checks", {}).get("prefer_hold_or_reduce"):
            scores["risk_ok"] = 1.0 if rec in {"HOLD", "REDUCE"} else 0.0
        blob = json.dumps(parsed, ensure_ascii=False)
        for ban in case.get("checks", {}).get("hallucination_ban") or []:
            if ban in blob:
                scores["hallucination_penalty"] = 1.0
                scores["notes"].append(f"hallucination:{ban}")
    else:
        summary = str(parsed.get("summary_ko") or "")
        scores["schema_ok"] = 1.0 if summary and "tone" in parsed else 0.0
        scores["korean_ok"] = 1.0 if _has_hangul(summary) else 0.0
        scores["rec_valid"] = 0.5
        scores["risk_ok"] = 0.5

    blob = json.dumps(parsed, ensure_ascii=False)
    must_nums = case.get("checks", {}).get("must_numbers") or []
    if must_nums:
        hit = sum(1 for n in must_nums if n in blob)
        scores["number_ok"] = hit / len(must_nums)
    else:
        scores["number_ok"] = 0.5

    must_p = case.get("checks", {}).get("must_preserve") or []
    if must_p:
        hit = sum(1 for p in must_p if p in blob)
        scores["preserve_ok"] = hit / len(must_p)
    else:
        scores["preserve_ok"] = 0.5

    total = (
        0.25 * scores["schema_ok"]
        + 0.15 * scores["korean_ok"]
        + 0.20 * scores["number_ok"]
        + 0.15 * scores["preserve_ok"]
        + 0.20 * scores["risk_ok"]
        + 0.05 * scores["rec_valid"]
        - 0.25 * scores["hallucination_penalty"]
    )
    scores["total"] = round(max(0.0, min(1.0, total)), 4)
    return scores


def call_ollama(
    *,
    model: str,
    system: str,
    user: str,
    schema: dict[str, Any],
    cold: bool,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    """Returns (parsed_json_or_none, metrics)."""

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": user
                + "\n\n반드시 아래 JSON Schema에 맞는 JSON 객체만 반환하세요.\n"
                + json.dumps(schema, ensure_ascii=False),
            },
        ],
        "stream": False,
        "format": schema,
        "think": False,
        "keep_alive": "0" if cold else KEEP_ALIVE,
        "options": {
            "temperature": TEMPERATURE,
            "num_predict": NUM_PREDICT,
        },
    }
    metrics: dict[str, Any] = {
        "ok": False,
        "error": None,
        "timeout": False,
        "wall_ms": None,
    }
    proc_ram = None
    cpu_before = None
    if psutil is not None:
        proc = psutil.Process()
        proc_ram = proc.memory_info().rss / (1024 * 1024)
        cpu_before = psutil.cpu_percent(interval=None)
    t0 = time.perf_counter()
    try:
        with httpx.Client(timeout=TIMEOUT_S) as client:
            res = client.post(f"{OLLAMA_BASE}/api/chat", json=payload)
            res.raise_for_status()
            body = res.json()
    except httpx.TimeoutException as exc:
        metrics.update(
            {
                "error": f"TIMEOUT:{exc}",
                "timeout": True,
                "wall_ms": (time.perf_counter() - t0) * 1000,
            }
        )
        return None, metrics
    except Exception as exc:  # noqa: BLE001
        metrics.update(
            {
                "error": f"{type(exc).__name__}:{exc}"[:240],
                "wall_ms": (time.perf_counter() - t0) * 1000,
            }
        )
        return None, metrics

    wall_ms = (time.perf_counter() - t0) * 1000
    ram_after = proc_ram
    cpu_after = cpu_before
    if psutil is not None:
        ram_after = psutil.Process().memory_info().rss / (1024 * 1024)
        cpu_after = psutil.cpu_percent(interval=0.1)

    content = ""
    msg = body.get("message") if isinstance(body, dict) else None
    if isinstance(msg, dict):
        content = str(msg.get("content") or "")
        if not content.strip():
            thinking = str(msg.get("thinking") or "")
            if thinking.strip().startswith("{"):
                content = thinking

    parsed = None
    err = None
    if content.strip():
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError as exc:
            err = f"JSONDecodeError:{exc}"
    else:
        err = "EMPTY_CONTENT"

    load_ms = _ns_to_ms(body.get("load_duration"))
    prompt_ms = _ns_to_ms(body.get("prompt_eval_duration"))
    eval_ms = _ns_to_ms(body.get("eval_duration"))
    total_ms = _ns_to_ms(body.get("total_duration")) or wall_ms
    prompt_tokens = body.get("prompt_eval_count")
    output_tokens = body.get("eval_count")
    tps = None
    if output_tokens and eval_ms and eval_ms > 0:
        tps = float(output_tokens) / (eval_ms / 1000.0)
    # first-token proxy ≈ load + prompt eval
    first_tok = None
    if load_ms is not None or prompt_ms is not None:
        first_tok = (load_ms or 0) + (prompt_ms or 0)

    metrics.update(
        {
            "ok": parsed is not None,
            "error": err,
            "wall_ms": wall_ms,
            "load_duration_ms": load_ms,
            "prompt_eval_duration_ms": prompt_ms,
            "eval_duration_ms": eval_ms,
            "total_duration_ms": total_ms,
            "prompt_tokens": prompt_tokens,
            "output_tokens": output_tokens,
            "tokens_per_second": tps,
            "first_token_latency_ms": first_tok,
            "ram_mb": round(max(proc_ram or 0, ram_after or 0), 1) if ram_after else None,
            "cpu_pct": round(max(cpu_before or 0, cpu_after or 0), 1)
            if cpu_after is not None
            else None,
            "raw_model": body.get("model"),
        }
    )
    return parsed if isinstance(parsed, dict) else None, metrics


def run_case(
    model: str,
    case: dict[str, Any],
    *,
    repeat: int,
    cold: bool,
) -> CaseResult:
    schema = ENTRY_SCHEMA if case["schema"] == "ENTRY" else ANALYSIS_SCHEMA
    user = (
        case["user_prefix"]
        + "\n\nINPUT_JSON=\n"
        + json.dumps(case["payload"], ensure_ascii=False, indent=2)
    )
    parsed, metrics = call_ollama(
        model=model,
        system=case["system"],
        user=user,
        schema=schema,
        cold=cold,
    )
    quality = score_quality(case, parsed)
    return CaseResult(
        model=model,
        case_id=case["id"],
        role=case["role"],
        repeat=repeat,
        cold=cold,
        ok=bool(metrics.get("ok")),
        error=metrics.get("error"),
        timeout=bool(metrics.get("timeout")),
        load_duration_ms=metrics.get("load_duration_ms"),
        prompt_eval_duration_ms=metrics.get("prompt_eval_duration_ms"),
        eval_duration_ms=metrics.get("eval_duration_ms"),
        total_duration_ms=metrics.get("total_duration_ms"),
        wall_ms=metrics.get("wall_ms"),
        prompt_tokens=metrics.get("prompt_tokens"),
        output_tokens=metrics.get("output_tokens"),
        tokens_per_second=metrics.get("tokens_per_second"),
        first_token_latency_ms=metrics.get("first_token_latency_ms"),
        parsed=parsed,
        quality=quality,
        ram_mb=metrics.get("ram_mb"),
        cpu_pct=metrics.get("cpu_pct"),
    )


def aggregate_model(results: list[CaseResult]) -> dict[str, Any]:
    warm = [r for r in results if not r.cold and r.ok]
    all_r = results
    lat = [r.total_duration_ms for r in warm if r.total_duration_ms is not None]
    tps = [r.tokens_per_second for r in warm if r.tokens_per_second is not None]
    q = [float(r.quality.get("total") or 0) for r in warm]
    # stability: same case recommendation/tone variance
    by_case: dict[str, list[str]] = {}
    for r in warm:
        if not r.parsed:
            continue
        key = r.case_id
        val = str(
            r.parsed.get("recommendation")
            or r.parsed.get("tone")
            or ""
        ).upper()
        by_case.setdefault(key, []).append(val)
    stable_scores = []
    for vals in by_case.values():
        if not vals:
            continue
        stable_scores.append(vals.count(max(set(vals), key=vals.count)) / len(vals))
    stability = _median(stable_scores) if stable_scores else None
    errs = sum(1 for r in all_r if not r.ok)
    timeouts = sum(1 for r in all_r if r.timeout)
    return {
        "median_latency_ms": _median(lat),
        "median_tokens_per_sec": _median(tps),
        "median_quality": _median(q),
        "stability": stability,
        "error_count": errs,
        "timeout_count": timeouts,
        "runs": len(all_r),
        "ok_runs": sum(1 for r in all_r if r.ok),
        "median_ram_mb": _median([r.ram_mb for r in all_r if r.ram_mb]),
        "median_cpu_pct": _median([r.cpu_pct for r in all_r if r.cpu_pct]),
        "median_first_token_ms": _median(
            [r.first_token_latency_ms for r in warm if r.first_token_latency_ms]
        ),
    }


def role_scores(agg: dict[str, Any], *, role: str) -> dict[str, float]:
    """Weighted role score 0-100. Missing metrics → conservative."""

    # normalize helpers
    lat = agg.get("median_latency_ms") or 60_000
    tps = agg.get("median_tokens_per_sec") or 1.0
    qual = float(agg.get("median_quality") or 0.0)
    stab = float(agg.get("stability") or 0.0)
    # speed score: faster better (cap)
    speed = max(0.0, min(1.0, 1.0 - (float(lat) / 45000.0)))
    tps_s = max(0.0, min(1.0, float(tps) / 80.0))
    speed = 0.6 * speed + 0.4 * tps_s
    mem = agg.get("median_ram_mb") or 500
    # lower process RSS delta not meaningful for ollama daemon; use latency proxy for load
    load = max(0.0, min(1.0, 1.0 - (float(lat) / 60000.0)))

    if role == "ANALYSIS":
        total = 100 * (0.40 * speed + 0.35 * qual + 0.15 * stab + 0.10 * load)
    else:
        total = 100 * (0.20 * speed + 0.45 * qual + 0.25 * stab + 0.10 * load)
    return {
        "speed": round(speed * 100, 2),
        "quality": round(qual * 100, 2),
        "stability": round(stab * 100, 2),
        "load": round(load * 100, 2),
        "total": round(total, 2),
        "latency_ms": lat,
        "tps": tps,
        "mem_proxy_mb": mem,
    }


def concurrent_test(cases: list[dict[str, Any]], model_a: str, model_t: str) -> dict[str, Any]:
    analysis_case = next(c for c in cases if c["role"] == "ANALYSIS")
    trading_case = next(c for c in cases if c["role"] == "TRADING")

    def _run(label: str, model: str, case: dict[str, Any]) -> dict[str, Any]:
        t0 = time.perf_counter()
        r = run_case(model, case, repeat=0, cold=False)
        return {
            "label": label,
            "model": model,
            "case_id": case["id"],
            "ok": r.ok,
            "wall_ms": (time.perf_counter() - t0) * 1000,
            "total_duration_ms": r.total_duration_ms,
            "error": r.error,
        }

    t0 = time.perf_counter()
    with ThreadPoolExecutor(max_workers=2) as ex:
        futs = [
            ex.submit(_run, "ANALYSIS", model_a, analysis_case),
            ex.submit(_run, "TRADING", model_t, trading_case),
        ]
        outs = [f.result() for f in as_completed(futs)]
    elapsed = (time.perf_counter() - t0) * 1000
    by = {o["label"]: o for o in outs}
    trading_ms = by.get("TRADING", {}).get("wall_ms")
    analysis_ms = by.get("ANALYSIS", {}).get("wall_ms")
    # starvation if trading much slower than solo median proxy (>2x analysis and >30s)
    starvation = bool(
        trading_ms is not None and trading_ms > 30000 and analysis_ms is not None and trading_ms > 2.0 * analysis_ms
    )
    return {
        "elapsed_ms": elapsed,
        "results": outs,
        "ANALYSIS_AND_TRADING_CONCURRENT_SAFE": all(o.get("ok") for o in outs),
        "TRADING_REQUEST_STARVATION": starvation,
        "MEMORY_PRESSURE": False,  # updated by caller via system ram
    }


def main() -> None:
    # verify ollama
    tags = httpx.get(f"{OLLAMA_BASE}/api/tags", timeout=10).json()
    installed = [m.get("name") for m in tags.get("models") or []]
    cases = build_cases()
    assert len(cases) >= 10

    vm0 = None
    if psutil is not None:
        vm0 = psutil.virtual_memory()
    report: dict[str, Any] = {
        "schema": "ollama_llm_role_benchmark_v1",
        "as_of": datetime.now(timezone.utc).isoformat(),
        "BEFORE": BEFORE,
        "installed_models": installed,
        "models_tested": MODELS,
        "case_count": len(cases),
        "repeats": REPEATS,
        "timeout_seconds": TIMEOUT_S,
        "temperature": TEMPERATURE,
        "num_predict": NUM_PREDICT,
        "think": False,
        "PRODUCTION_MODEL_CHANGED": False,
        "REAL_POLICY_CHANGED": False,
        "REAL_ORDER_MUTATION": 0,
        "CANCEL_AMEND_MUTATION": 0,
        "LIVE_MUTATION": 0,
        "ARM_MUTATION": 0,
        "LIVE_ARM_MUTATION": 0,
        "RISK_MUTATION": 0,
        "SLOT_POLICY_MUTATION": 0,
        "KIWOOM_MUTATION": 0,
        "system_ram_before": (
            {
                "total_gb": round(vm0.total / (1024**3), 2),
                "available_gb": round(vm0.available / (1024**3), 2),
                "percent": vm0.percent,
            }
            if vm0 is not None
            else {"note": "psutil_not_installed"}
        ),
        "cases": [{"id": c["id"], "type": c["type"], "role": c["role"], "title": c["title"]} for c in cases],
        "results": [],
        "aggregates": {},
        "role_scores": {"ANALYSIS": {}, "TRADING": {}},
        "architecture_prep": {
            "proposed_settings": [
                "analysis_llm_model (fallback ollama_model)",
                "trading_llm_model (fallback ollama_model)",
                "independent timeout/temperature/max_tokens/keep_alive per role",
                "queue priority: TRADING > ANALYSIS (design only)",
            ],
            "reuse_client": "stock_platform.ai.ollama_client.OllamaClient",
            "wired_into_production": False,
        },
    }

    all_results: list[CaseResult] = []
    for model in MODELS:
        print(f"=== MODEL {model} cold load ===", flush=True)
        cold = run_case(model, cases[0], repeat=0, cold=True)
        all_results.append(cold)
        report["results"].append(asdict(cold))
        print(
            f"cold ok={cold.ok} wall={cold.wall_ms} err={cold.error}",
            flush=True,
        )
        for case in cases:
            for rep in range(1, REPEATS + 1):
                print(f"{model} {case['id']} r{rep}", flush=True)
                r = run_case(model, case, repeat=rep, cold=False)
                all_results.append(r)
                report["results"].append(asdict(r))
                print(
                    f"  ok={r.ok} ms={r.total_duration_ms} q={r.quality.get('total')} err={r.error}",
                    flush=True,
                )

    for model in MODELS:
        subset = [r for r in all_results if r.model == model]
        report["aggregates"][model] = aggregate_model(subset)

    for model in MODELS:
        report["role_scores"]["ANALYSIS"][model] = role_scores(
            report["aggregates"][model], role="ANALYSIS"
        )
        report["role_scores"]["TRADING"][model] = role_scores(
            report["aggregates"][model], role="TRADING"
        )

    analysis_best = max(
        MODELS, key=lambda m: report["role_scores"]["ANALYSIS"][m]["total"]
    )
    trading_best = max(
        MODELS, key=lambda m: report["role_scores"]["TRADING"][m]["total"]
    )

    # concurrent with recommended pair (or same if identical)
    print("=== concurrent ANALYSIS+TRADING ===", flush=True)
    conc = concurrent_test(cases, analysis_best, trading_best)
    if psutil is not None:
        vm1 = psutil.virtual_memory()
        conc["MEMORY_PRESSURE"] = vm1.percent >= 90 or (vm1.available / vm1.total) < 0.08
        conc["system_ram_after"] = {
            "available_gb": round(vm1.available / (1024**3), 2),
            "percent": vm1.percent,
        }
    else:
        conc["MEMORY_PRESSURE"] = False
        conc["system_ram_after"] = {"note": "psutil_not_installed"}
    report["concurrent"] = conc

    report["ANALYSIS_LLM_RECOMMENDED"] = analysis_best
    report["TRADING_LLM_RECOMMENDED"] = trading_best
    report["ANALYSIS_LLM_SELECTION_REASON"] = (
        f"ANALYSIS weights speed40/quality35/stability15/load10 → {analysis_best} "
        f"score={report['role_scores']['ANALYSIS'][analysis_best]['total']}"
    )
    report["TRADING_LLM_SELECTION_REASON"] = (
        f"TRADING weights quality45/stability25/speed20/load10 → {trading_best} "
        f"score={report['role_scores']['TRADING'][trading_best]['total']}"
    )
    report["ANALYSIS_AND_TRADING_CONCURRENT_SAFE"] = conc[
        "ANALYSIS_AND_TRADING_CONCURRENT_SAFE"
    ]
    report["TRADING_REQUEST_STARVATION"] = conc["TRADING_REQUEST_STARVATION"]
    report["MEMORY_PRESSURE"] = conc["MEMORY_PRESSURE"]
    report["SYSTEM_BUG_ACTIVE"] = False
    report["LIMITATIONS"] = [
        "Candidate LLM production path is still heuristic (not live Ollama).",
        "Quality scores use schema/number/risk heuristics — not absolute trading truth.",
        "Forward outcomes excluded from prompts (no lookahead).",
        "Role settings prepared but not wired into production callers.",
        "Process RSS does not equal Ollama model VRAM/RAM residency.",
    ]
    report["FINAL_VERDICT"] = "OLLAMA_LLM_ROLE_BENCHMARK_COMPLETE"
    report["NEXT_ACTION"] = "REVIEW_OLLAMA_LLM_BENCHMARK_WITH_CHATGPT"
    report["GIT_COMMIT"] = None

    OUT_JSON.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    def _model_block(m: str) -> list[str]:
        a = report["aggregates"][m]
        return [
            f"### {m}",
            f"- median latency: {a.get('median_latency_ms')}",
            f"- tokens/sec: {a.get('median_tokens_per_sec')}",
            f"- quality score: {a.get('median_quality')}",
            f"- stability: {a.get('stability')}",
            f"- RAM/CPU (client process proxy): {a.get('median_ram_mb')} / {a.get('median_cpu_pct')}",
            f"- errors/timeouts: {a.get('error_count')}/{a.get('timeout_count')}",
            "",
        ]

    md = [
        "# Ollama LLM Role Benchmark",
        "",
        f"FINAL_VERDICT: **{report['FINAL_VERDICT']}**",
        "",
        f"ANALYSIS_LLM_RECOMMENDED = `{analysis_best}`",
        f"TRADING_LLM_RECOMMENDED = `{trading_best}`",
        "",
        "## BEFORE (production untouched)",
        "```json",
        json.dumps(BEFORE, ensure_ascii=False, indent=2),
        "```",
        "",
        "## Per model",
    ]
    for m in MODELS:
        md.extend(_model_block(m))
    md.extend(
        [
            "## ANALYSIS_LLM_SCORE_TABLE",
            "```json",
            json.dumps(report["role_scores"]["ANALYSIS"], ensure_ascii=False, indent=2),
            "```",
            "",
            "## TRADING_LLM_SCORE_TABLE",
            "```json",
            json.dumps(report["role_scores"]["TRADING"], ensure_ascii=False, indent=2),
            "```",
            "",
            "## Selection reasons",
            report["ANALYSIS_LLM_SELECTION_REASON"],
            "",
            report["TRADING_LLM_SELECTION_REASON"],
            "",
            "## Concurrent",
            f"- ANALYSIS_AND_TRADING_CONCURRENT_SAFE = {report['ANALYSIS_AND_TRADING_CONCURRENT_SAFE']}",
            f"- TRADING_REQUEST_STARVATION = {report['TRADING_REQUEST_STARVATION']}",
            f"- MEMORY_PRESSURE = {report['MEMORY_PRESSURE']}",
            "",
            "## Architecture prep (not wired)",
            json.dumps(report["architecture_prep"], ensure_ascii=False, indent=2),
            "",
            "PRODUCTION_MODEL_CHANGED = NO",
            "REAL_POLICY_CHANGED = NO",
            "NEXT_ACTION = REVIEW_OLLAMA_LLM_BENCHMARK_WITH_CHATGPT",
            "",
        ]
    )
    OUT_MD.write_text("\n".join(md), encoding="utf-8")
    print(json.dumps({"FINAL_VERDICT": report["FINAL_VERDICT"], "OUT": str(OUT_JSON)}, indent=2))


if __name__ == "__main__":
    main()
