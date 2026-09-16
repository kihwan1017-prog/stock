"""기술지표 파라미터 — Default + DB 활성 설정 (Fail Closed)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from stock_platform.indicators.parameter_entities import (
    IndicatorParameterConfigEntity,
)


DEFAULT_PARAMETERS: dict[str, dict[str, int]] = {
    "SMA": {"periods": 5},  # 표시용 — 엔진은 ma5/20/60 세트
    "MA_SET": {"ma5": 5, "ma20": 20, "ma60": 60},
    "EMA_SET": {"ema12": 12, "ema26": 26},
    "RSI": {"period": 14},
    "MACD": {"fast": 12, "slow": 26, "signal": 9},
    "BOLLINGER": {"period": 20},
    "ATR": {"period": 14},
}


@dataclass(frozen=True, slots=True)
class IndicatorEngineParams:
    ma5: int = 5
    ma20: int = 20
    ma60: int = 60
    ema12: int = 12
    ema26: int = 26
    rsi_period: int = 14
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9
    bollinger_period: int = 20
    atr_period: int = 14
    source: str = "SYSTEM_DEFAULT"


class IndicatorParameterValidationError(ValueError):
    pass


def validate_parameter_payload(
    indicator_code: str, payload: dict[str, Any]
) -> dict[str, Any]:
    code = indicator_code.strip().upper()
    if not payload or not isinstance(payload, dict):
        raise IndicatorParameterValidationError("parameter_payload required")

    def _pos_int(name: str) -> int:
        if name not in payload:
            raise IndicatorParameterValidationError(f"{name} required")
        try:
            value = int(payload[name])
        except (TypeError, ValueError) as exc:
            raise IndicatorParameterValidationError(
                f"{name} must be positive int"
            ) from exc
        if value <= 0:
            raise IndicatorParameterValidationError(
                f"{name} must be positive int"
            )
        return value

    if code == "MA_SET":
        return {
            "ma5": _pos_int("ma5"),
            "ma20": _pos_int("ma20"),
            "ma60": _pos_int("ma60"),
        }
    if code == "EMA_SET":
        return {"ema12": _pos_int("ema12"), "ema26": _pos_int("ema26")}
    if code == "RSI":
        return {"period": _pos_int("period")}
    if code == "MACD":
        fast = _pos_int("fast")
        slow = _pos_int("slow")
        signal = _pos_int("signal")
        if fast >= slow:
            raise IndicatorParameterValidationError(
                "MACD fast must be < slow"
            )
        return {"fast": fast, "slow": slow, "signal": signal}
    if code == "BOLLINGER":
        return {"period": _pos_int("period")}
    if code == "ATR":
        return {"period": _pos_int("period")}
    if code == "SMA":
        return {"periods": _pos_int("periods")}
    raise IndicatorParameterValidationError(
        f"unsupported indicator_code: {code}"
    )


class IndicatorParameterService:
    def __init__(self, session: Session) -> None:
        self._session = session

    def list_configs(
        self,
        *,
        indicator_code: str | None = None,
        active_only: bool = False,
    ) -> list[IndicatorParameterConfigEntity]:
        stmt = select(IndicatorParameterConfigEntity).order_by(
            IndicatorParameterConfigEntity.indicator_code.asc(),
            IndicatorParameterConfigEntity.version.desc(),
        )
        if indicator_code:
            stmt = stmt.where(
                IndicatorParameterConfigEntity.indicator_code
                == indicator_code.strip().upper()
            )
        if active_only:
            stmt = stmt.where(
                IndicatorParameterConfigEntity.is_active.is_(True)
            )
        return list(self._session.scalars(stmt))

    def get(self, config_id: int) -> IndicatorParameterConfigEntity | None:
        return self._session.get(IndicatorParameterConfigEntity, config_id)

    def create(
        self,
        *,
        indicator_code: str,
        parameter_payload: dict[str, Any],
        market_type: str = "STOCK",
        exchange_code: str | None = None,
        timeframe: str = "1D",
        activate: bool = True,
        created_by: str | None = None,
    ) -> IndicatorParameterConfigEntity:
        code = indicator_code.strip().upper()
        payload = validate_parameter_payload(code, parameter_payload)
        version = self._next_version(code, market_type, timeframe)
        if activate:
            self._deactivate_active(code, market_type, timeframe)
        row = IndicatorParameterConfigEntity(
            indicator_code=code,
            market_type=market_type.strip().upper(),
            exchange_code=(exchange_code or "").strip().upper() or None,
            timeframe=timeframe.strip().upper() or "1D",
            parameter_payload=payload,
            version=version,
            is_active=bool(activate),
            effective_from=datetime.now(timezone.utc),
            created_by=created_by,
        )
        self._session.add(row)
        self._session.flush()
        return row

    def update(
        self,
        config_id: int,
        *,
        parameter_payload: dict[str, Any] | None = None,
        is_active: bool | None = None,
        actor: str | None = None,
    ) -> IndicatorParameterConfigEntity:
        row = self.get(config_id)
        if row is None:
            raise LookupError("indicator parameter config not found")
        if parameter_payload is not None:
            row.parameter_payload = validate_parameter_payload(
                row.indicator_code, parameter_payload
            )
        if is_active is True:
            self._deactivate_active(
                row.indicator_code, row.market_type, row.timeframe
            )
            row.is_active = True
        elif is_active is False:
            row.is_active = False
        row.updated_at = datetime.now(timezone.utc)
        if actor:
            row.created_by = actor
        self._session.flush()
        return row

    def resolve_engine_params(
        self,
        *,
        market_type: str = "STOCK",
        timeframe: str = "1D",
    ) -> IndicatorEngineParams:
        """DB 활성 설정 병합. 실패 시 Fail Closed → SYSTEM_DEFAULT."""

        params = IndicatorEngineParams()
        try:
            active = self.list_configs(active_only=True)
        except Exception:  # noqa: BLE001
            return params

        source_bits: list[str] = []
        values = {
            "ma5": params.ma5,
            "ma20": params.ma20,
            "ma60": params.ma60,
            "ema12": params.ema12,
            "ema26": params.ema26,
            "rsi_period": params.rsi_period,
            "macd_fast": params.macd_fast,
            "macd_slow": params.macd_slow,
            "macd_signal": params.macd_signal,
            "bollinger_period": params.bollinger_period,
            "atr_period": params.atr_period,
        }
        mt = market_type.strip().upper()
        tf = timeframe.strip().upper()
        for row in active:
            if row.market_type.upper() not in {mt, "ALL"}:
                continue
            if row.timeframe.upper() not in {tf, "ALL"}:
                continue
            try:
                payload = validate_parameter_payload(
                    row.indicator_code, dict(row.parameter_payload or {})
                )
            except IndicatorParameterValidationError:
                # Fail Closed — 잘못된 활성 설정은 무시하고 Default 유지
                continue
            code = row.indicator_code.upper()
            if code == "MA_SET":
                values.update(payload)
            elif code == "EMA_SET":
                values["ema12"] = payload["ema12"]
                values["ema26"] = payload["ema26"]
            elif code == "RSI":
                values["rsi_period"] = payload["period"]
            elif code == "MACD":
                values["macd_fast"] = payload["fast"]
                values["macd_slow"] = payload["slow"]
                values["macd_signal"] = payload["signal"]
            elif code == "BOLLINGER":
                values["bollinger_period"] = payload["period"]
            elif code == "ATR":
                values["atr_period"] = payload["period"]
            source_bits.append(f"{code}@v{row.version}")

        # MACD 검증
        if values["macd_fast"] >= values["macd_slow"]:
            return IndicatorEngineParams(source="SYSTEM_DEFAULT_FAIL_CLOSED")

        return IndicatorEngineParams(
            ma5=int(values["ma5"]),
            ma20=int(values["ma20"]),
            ma60=int(values["ma60"]),
            ema12=int(values["ema12"]),
            ema26=int(values["ema26"]),
            rsi_period=int(values["rsi_period"]),
            macd_fast=int(values["macd_fast"]),
            macd_slow=int(values["macd_slow"]),
            macd_signal=int(values["macd_signal"]),
            bollinger_period=int(values["bollinger_period"]),
            atr_period=int(values["atr_period"]),
            source=(
                "DB:" + ",".join(source_bits)
                if source_bits
                else "SYSTEM_DEFAULT"
            ),
        )

    def defaults(self) -> dict[str, Any]:
        return dict(DEFAULT_PARAMETERS)

    def restore_system_defaults(
        self,
        *,
        indicator_code: str | None = None,
        market_type: str | None = None,
        timeframe: str | None = None,
    ) -> int:
        """활성 DB 설정을 비활성화해 SYSTEM_DEFAULT 로 복귀한다 (행 삭제 없음)."""

        stmt = select(IndicatorParameterConfigEntity).where(
            IndicatorParameterConfigEntity.is_active.is_(True)
        )
        if indicator_code:
            stmt = stmt.where(
                IndicatorParameterConfigEntity.indicator_code
                == indicator_code.strip().upper()
            )
        if market_type:
            stmt = stmt.where(
                IndicatorParameterConfigEntity.market_type
                == market_type.strip().upper()
            )
        if timeframe:
            stmt = stmt.where(
                IndicatorParameterConfigEntity.timeframe
                == timeframe.strip().upper()
            )
        rows = list(self._session.scalars(stmt))
        now = datetime.now(timezone.utc)
        for row in rows:
            row.is_active = False
            row.updated_at = now
        self._session.flush()
        return len(rows)

    def preview(self, indicator_code: str, payload: dict[str, Any]) -> dict:
        cleaned = validate_parameter_payload(indicator_code, payload)
        return {
            "indicator_code": indicator_code.strip().upper(),
            "parameter_payload": cleaned,
            "valid": True,
            "system_default": DEFAULT_PARAMETERS.get(
                indicator_code.strip().upper()
            ),
        }

    def _next_version(
        self, indicator_code: str, market_type: str, timeframe: str
    ) -> int:
        current = self._session.scalar(
            select(func.max(IndicatorParameterConfigEntity.version)).where(
                IndicatorParameterConfigEntity.indicator_code
                == indicator_code,
                IndicatorParameterConfigEntity.market_type
                == market_type.strip().upper(),
                IndicatorParameterConfigEntity.timeframe
                == timeframe.strip().upper(),
            )
        )
        return int(current or 0) + 1

    def _deactivate_active(
        self, indicator_code: str, market_type: str, timeframe: str
    ) -> None:
        rows = list(
            self._session.scalars(
                select(IndicatorParameterConfigEntity).where(
                    IndicatorParameterConfigEntity.indicator_code
                    == indicator_code,
                    IndicatorParameterConfigEntity.market_type
                    == market_type.strip().upper(),
                    IndicatorParameterConfigEntity.timeframe
                    == timeframe.strip().upper(),
                    IndicatorParameterConfigEntity.is_active.is_(True),
                )
            )
        )
        for row in rows:
            row.is_active = False
