"""Builtin/DB template placeholder ↔ normalizer contract 감사."""

from __future__ import annotations

from typing import Any

from stock_platform.notification.builtin_templates import BUILTIN_TEMPLATES
from stock_platform.notification.normalizer import normalize_variables
from stock_platform.notification.template_renderer import extract_placeholders

# 이벤트별 대표 production-like sample (존재하지 않는 값 생성 금지 — 계약 검증용)
SAMPLE_PAYLOADS: dict[str, dict[str, Any]] = {
    "ORDER_SUBMITTED": {
        "broker_code": "UPBIT",
        "symbol": "KRW-XRP",
        "side": "BUY",
        "amount_krw": 10000,
        "price": 1600,
        "quantity": 6,
    },
    "ORDER_FILLED": {
        "broker_code": "UPBIT",
        "symbol": "KRW-ETH",
        "side": "BUY",
        "amount_krw": 24000,
        "avg_price": 5320000,
        "filled_qty": 0.00451,
        "strategy_name": "전체시장 포트폴리오",
        "position_status": "OPEN",
    },
    "ORDER_PARTIAL_FILLED": {
        "broker_code": "UPBIT",
        "symbol": "KRW-BTC",
        "side": "BUY",
        "avg_price": 150000000,
        "filled_qty": 0.0001,
        "amount_krw": 15000,
    },
    "ORDER_CANCELLED": {
        "broker_code": "UPBIT",
        "symbol": "KRW-XRP",
        "side": "SELL",
        "reason": "사용자 취소",
    },
    "ORDER_REJECTED": {
        "broker_code": "UPBIT",
        "symbol": "KRW-XRP",
        "side": "BUY",
        "reason": "잔고 부족",
    },
    "TAKE_PROFIT": {
        "broker_code": "UPBIT",
        "symbol": "KRW-XRP",
        "side": "SELL",
        "avg_price": 1700,
        "filled_qty": 10,
    },
    "STOP_LOSS": {
        "broker_code": "UPBIT",
        "symbol": "KRW-XRP",
        "side": "SELL",
        "avg_price": 1400,
        "filled_qty": 10,
    },
    "TRAILING_STOP": {
        "broker_code": "UPBIT",
        "symbol": "KRW-XRP",
        "side": "SELL",
        "avg_price": 1650,
        "filled_qty": 10,
    },
    "PORTFOLIO_BULLISH_STATE_ENTRY": {
        "broker_code": "UPBIT",
        "symbol": "KRW-PEPE",
        "side": "BUY",
        "score": 76.97,
        "recommendation": "ALLOW",
        "approved_amount_krw": 10000,
        "rsi14": 58.2,
        "slot_no": 3,
    },
    "AI_GATE_RECOMMENDATION_CHANGED": {
        "symbol": "KRW-XRP",
        "previous_recommendation": "HOLD",
        "new_recommendation": "ALLOW",
        "confidence": 0.95,
    },
    "UPBIT_SCANNER_CANDIDATE": {
        "candidate": {
            "symbol": "KRW-PEPE",
            "rank": 1,
            "score": 76.97345,
            "recommendation": "ALLOW",
            "confidence": 0.95,
        },
        "slot_no": 3,
    },
    "KILL_SWITCH": {
        "broker_code": "KIWOOM",
        "user_broker_account_id": 1381,
        "reason": "포지션 정합성 불일치",
    },
    "DAILY_LOSS": {
        "broker_code": "UPBIT",
        "current_value": "30%",
        "limit_value": "30%",
        "reason": "전체 노출 한도 도달",
    },
    "RECOVERY_STARTED": {"user_broker_account_id": 1380},
    "RECOVERY_FAILED": {
        "user_broker_account_id": 1380,
        "reason": "conflict unresolved",
    },
    "RECOVERY_CONFLICT": {
        "user_broker_account_id": 1380,
        "reason": "REMOTE_WAIT_SELL",
    },
    "RECONCILIATION_MISMATCH": {
        "symbol": "KRW-BTC",
        "broker_code": "UPBIT",
        "user_broker_account_id": 1380,
        "reason": "qty mismatch",
    },
    "SYSTEM_START": {},
    "SYSTEM_STOP": {},
    "RUNTIME_STARTED": {
        "runtime_status": "RUNNING",
        "strategy_id": 1,
        "user_broker_account_id": 1380,
    },
    "RUNTIME_PAUSED": {
        "runtime_status": "PAUSED",
        "reason": "manual",
        "user_broker_account_id": 1380,
    },
    "SCHEDULER_STARTED": {},
    "SCHEDULER_PAUSED": {"reason": "manual"},
    "SCHEDULER_ERROR": {"reason": "worker crash"},
    "BROKER_DISCONNECTED": {"broker_code": "UPBIT"},
    "BROKER_RECONNECTED": {"broker_code": "UPBIT"},
    "DATABASE_ERROR": {"reason": "connection lost"},
    "MONITORING_ALERT": {"reason": "latency high"},
    "TEST_NOTIFICATION": {"message": "ping"},
    "GENERIC": {"message": "hello"},
}

# 의도적으로 optional — 없어도 PASS가 아닌 OPTIONAL
OPTIONAL_PLACEHOLDERS = frozenset(
    {
        "rank",
        "slot_no",
        "candidates_summary",
        "expires_at_kst",
        "created_at_kst",
        "confidence_pct",
        "rsi14",
        "approved_amount_krw",
        "order_id",
        "strategy_id",
        "uba_id",
        "current_value",
        "limit_value",
        "previous_recommendation_ko",
        "new_recommendation_ko",
        "position_status_ko",
        "quantity",
        "filled_qty",
        "price_display",
        "avg_price",
        "amount_krw",
        "strategy_name",
        "reason",
        "reason_ko",
        "runtime_status_ko",
        "title",
        "message",
        "account_display",
        "scanner_score",
        "score",
        "ai_recommendation",
        "ai_recommendation_ko",
        "broker_ko",
        "side_ko",
        "status_ko",
    }
)


def _classify_placeholder(
    name: str,
    variables: dict[str, Any],
) -> str:
    if name not in variables:
        return "INVALID_TEMPLATE_VARIABLE"
    value = variables.get(name)
    if value is None or value == "":
        if name in OPTIONAL_PLACEHOLDERS:
            return "OPTIONAL"
        return "MISSING_MAPPING"
    return "PASS"


def audit_builtin_template_contracts() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for tpl in BUILTIN_TEMPLATES:
        event_type = str(tpl["event_type"]).upper()
        text = "\n".join(
            [
                str(tpl.get("title_template") or ""),
                str(tpl.get("body_template") or ""),
                str(tpl.get("short_body_template") or ""),
            ]
        )
        placeholders = extract_placeholders(text)
        sample = SAMPLE_PAYLOADS.get(event_type, {})
        variables = normalize_variables(
            event_type=event_type,
            title="",
            message="",
            detail=sample,
        )
        known = set(variables.keys())
        for name in placeholders:
            status = _classify_placeholder(name, variables)
            rows.append(
                {
                    "event_type": event_type,
                    "placeholder": name,
                    "status": status,
                    "in_normalizer": name in known,
                    "sample_value": variables.get(name),
                }
            )
    return rows


def summarize_contract_audit(
    rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    data = rows if rows is not None else audit_builtin_template_contracts()
    by_status: dict[str, int] = {}
    for row in data:
        by_status[row["status"]] = by_status.get(row["status"], 0) + 1
    high_priority = {
        "UPBIT_SCANNER_CANDIDATE",
        "AI_GATE_RECOMMENDATION_CHANGED",
        "ORDER_SUBMITTED",
        "ORDER_FILLED",
        "ORDER_PARTIAL_FILLED",
        "ORDER_CANCELLED",
        "ORDER_REJECTED",
        "TAKE_PROFIT",
        "STOP_LOSS",
        "TRAILING_STOP",
        "PORTFOLIO_BULLISH_STATE_ENTRY",
        "KILL_SWITCH",
        "DAILY_LOSS",
        "RECOVERY_STARTED",
        "RECOVERY_FAILED",
        "RECOVERY_CONFLICT",
        "RECONCILIATION_MISMATCH",
        "RUNTIME_STARTED",
        "RUNTIME_PAUSED",
    }
    high_rows = [r for r in data if r["event_type"] in high_priority]
    high_fail = [
        r
        for r in high_rows
        if r["status"] in {"MISSING_MAPPING", "INVALID_TEMPLATE_VARIABLE"}
    ]
    return {
        "total_placeholders": len(data),
        "by_status": by_status,
        "high_priority_fail": high_fail,
        "rows": data,
    }
