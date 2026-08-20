"""전략 parameter_payload의 심볼 정규화. 원본 행 mutate 없음."""

from __future__ import annotations

from typing import Any


def normalize_upbit_symbol(symbol: str) -> str:
    text = str(symbol or "").strip().upper()
    if not text:
        raise ValueError("symbol required")
    if not text.startswith("KRW-"):
        raise ValueError("UPBIT test symbol must be KRW-*")
    if text == "KRW-XRP":
        raise ValueError("KRW-XRP is reserved to strategy 17483")
    return text


def symbols_from_parameter_payload(payload: dict[str, Any] | None) -> list[str]:
    data = dict(payload or {})
    raw = data.get("symbols")
    found: list[str] = []
    if isinstance(raw, list):
        for item in raw:
            code = str(item or "").strip().upper()
            if code and code not in found:
                found.append(code)
    one = str(data.get("symbol") or "").strip().upper()
    if one and one not in found:
        found.insert(0, one)
    return found


def apply_runtime_target_symbol(
    payload: dict[str, Any] | None,
    *,
    symbol: str,
) -> dict[str, Any]:
    """운영용 runtime target 심볼 적용.

    clone용 normalize_upbit_symbol(XRP 예약)과 분리 — FULL_MARKET 동적 target 허용.
    """

    target = str(symbol or "").strip().upper()
    if not target:
        raise ValueError("symbol required")
    if not target.startswith("KRW-"):
        raise ValueError("UPBIT runtime target must be KRW-*")
    cloned = dict(payload or {})
    cloned["symbol"] = target
    cloned["symbols"] = [target]
    cloned["exchange_code"] = "UPBIT"
    return cloned


def apply_symbol_to_parameter_payload(
    payload: dict[str, Any] | None,
    *,
    symbol: str,
) -> dict[str, Any]:
    """새 payload 복사본. 원본 dict를 제자리 수정하지 않는다."""

    target = normalize_upbit_symbol(symbol)
    cloned = dict(payload or {})
    cloned["symbol"] = target
    cloned["symbols"] = [target]
    cloned["exchange_code"] = "UPBIT"
    return cloned


def is_legacy_ma_payload(payload: dict[str, Any] | None) -> bool:
    """STEP12 entry_rule이 없고 MA 교차 비율 필드만 있는 레거시 템플릿."""

    data = dict(payload or {})
    if data.get("entry_rule"):
        return False
    strategy_type = str(data.get("strategy_type") or "").upper()
    return strategy_type in {"MOVING_AVERAGE_CROSS", "MOVING_AVERAGE"} and (
        data.get("short_window") is not None and data.get("long_window") is not None
    )


def _ratio_to_percent(raw: Any) -> float:
    value = float(raw)
    if value < 0:
        raise ValueError("ratio must not be negative")
    if value <= 1:
        return value * 100.0
    return value


def canonical_step12_payload_from_ma_semantics(
    payload: dict[str, Any] | None,
    *,
    symbol: str,
) -> dict[str, Any]:
    """17483 레거시 MA semantics → STEP12 compile payload. 원본 dict 불변."""

    target = normalize_upbit_symbol(symbol)
    data = dict(payload or {})
    if data.get("entry_rule") and data.get("exit_rule") and data.get("timeframe"):
        out = apply_symbol_to_parameter_payload(data, symbol=target)
        if not out.get("source_market_type"):
            out["source_market_type"] = "CRYPTO"
        return out

    if not is_legacy_ma_payload(data):
        raise ValueError("payload is not a MOVING_AVERAGE_CROSS legacy template")

    short_window = int(data["short_window"])
    long_window = int(data["long_window"])
    if short_window <= 0 or long_window <= 0 or short_window >= long_window:
        raise ValueError("invalid MA windows")
    stop_loss_percent = _ratio_to_percent(data["stop_loss_ratio"])
    take_profit_percent = _ratio_to_percent(data["take_profit_ratio"])
    position_ratio = float(data["position_ratio"])
    if not (0 < position_ratio <= 1):
        raise ValueError("position_ratio must be in (0, 1]")

    out = apply_symbol_to_parameter_payload(data, symbol=target)
    out["timeframe"] = "1D"
    out["source_market_type"] = "CRYPTO"
    out["entry_rule"] = [
        {
            "indicator": "SMA",
            "operator": "CROSS_ABOVE",
            "threshold": 0,
            "comparison_target": f"SMA:{long_window}",
            "lookback": short_window,
        }
    ]
    out["exit_rule"] = [
        {
            "indicator": "SMA",
            "operator": "CROSS_BELOW",
            "threshold": 0,
            "comparison_target": f"SMA:{long_window}",
            "lookback": short_window,
        }
    ]
    out["stop_loss_rule"] = {"type": "PERCENT", "value": stop_loss_percent}
    out["take_profit_rule"] = {"type": "PERCENT", "value": take_profit_percent}
    out["position_sizing_rule"] = {
        "method": "FIXED_PERCENT",
        "value": position_ratio,
    }
    out["indicator_configuration"] = {
        "short_window": short_window,
        "long_window": long_window,
        "warmup_bars": long_window,
        "cooldown_bars": 1,
    }
    out["risk_parameters"] = {
        "stop_loss_rate": stop_loss_percent / 100.0,
        "take_profit_rate": take_profit_percent / 100.0,
    }
    return out


def execution_semantics(payload: dict[str, Any] | None) -> dict[str, Any]:
    """심볼을 제외한 실행 로직 비교 키. 레거시는 canonical projection."""

    data = dict(payload or {})
    if is_legacy_ma_payload(data):
        projected = canonical_step12_payload_from_ma_semantics(
            data,
            symbol="KRW-SOL",
        )
        data = projected
    return {
        "timeframe": data.get("timeframe"),
        "source_market_type": data.get("source_market_type"),
        "entry_rule": data.get("entry_rule"),
        "exit_rule": data.get("exit_rule"),
        "stop_loss_rule": data.get("stop_loss_rule"),
        "take_profit_rule": data.get("take_profit_rule"),
        "position_sizing_rule": data.get("position_sizing_rule"),
        "indicator_configuration": dict(data.get("indicator_configuration") or {}),
    }


def signal_symbol_matches_strategy(
    *,
    signal_symbol: str,
    payload: dict[str, Any] | None,
) -> bool:
    allowed = {
        str(item).upper() for item in symbols_from_parameter_payload(payload)
    }
    return str(signal_symbol or "").strip().upper() in allowed
