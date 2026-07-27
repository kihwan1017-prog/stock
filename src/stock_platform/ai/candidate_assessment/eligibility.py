"""STEP 11-9 — Instrument Eligibility (trading/order/screener import 금지)."""

from __future__ import annotations

import hashlib
import re
from typing import Any

from sqlalchemy.orm import Session

from stock_platform.ai.candidate_assessment.constants import (
    ASSESSMENT_TYPES,
    REFERENCE_DISCLAIMER,
)

_KRX_SYMBOL_RE = re.compile(r"^[0-9A-Za-z]{1,12}$")
_UPBIT_SYMBOL_RE = re.compile(r"^KRW-[A-Z0-9]{2,20}$", re.IGNORECASE)


class AICandidateEligibilityService:
    """종목/암호화폐 평가 대상 적격성 검증."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def validate(
        self,
        *,
        market_type: str,
        exchange_code: str,
        symbol: str,
        instrument_id: int | None = None,
    ) -> dict[str, Any]:
        reasons: list[str] = []
        warnings: list[str] = []
        assessment_type: str | None = None
        normalized_exchange = (exchange_code or "").strip().upper()
        normalized_symbol = (symbol or "").strip()

        if market_type not in ASSESSMENT_TYPES:
            reasons.append("INVALID_MARKET_TYPE")
            return self._result(
                allowed=False,
                reasons=reasons,
                warnings=warnings,
                market_type=market_type,
                exchange_code=normalized_exchange,
                symbol=normalized_symbol,
                instrument_id=instrument_id,
            )

        if market_type == "STOCK":
            assessment_type = "STOCK"
            if normalized_exchange != "KRX":
                reasons.append("STOCK_REQUIRES_KRX")
        elif market_type == "CRYPTO":
            assessment_type = "CRYPTO"
            if normalized_exchange != "UPBIT":
                reasons.append("CRYPTO_REQUIRES_UPBIT")

        if not normalized_exchange:
            reasons.append("EXCHANGE_REQUIRED")
        if not normalized_symbol:
            reasons.append("SYMBOL_REQUIRED")

        if normalized_exchange == "KRX" and normalized_symbol:
            if not _KRX_SYMBOL_RE.match(normalized_symbol):
                reasons.append("INVALID_KRX_SYMBOL_FORMAT")
            elif not normalized_symbol.isdigit() and len(normalized_symbol) < 4:
                warnings.append("KRX_SYMBOL_NON_STANDARD")

        if normalized_exchange == "UPBIT" and normalized_symbol:
            if not _UPBIT_SYMBOL_RE.match(normalized_symbol):
                if "-" not in normalized_symbol:
                    warnings.append("UPBIT_SYMBOL_MISSING_KRW_PREFIX")
                    normalized_symbol = f"KRW-{normalized_symbol.upper()}"
                elif not _UPBIT_SYMBOL_RE.match(normalized_symbol):
                    reasons.append("INVALID_UPBIT_SYMBOL_FORMAT")

        instrument_key: str | None = None
        if instrument_id is not None:
            instrument_key = str(instrument_id)
        elif normalized_exchange and normalized_symbol:
            # instrument_id 없을 때 synthetic key (Evidence 참조용)
            raw = f"{normalized_exchange}:{normalized_symbol}"
            instrument_key = hashlib.sha256(raw.encode()).hexdigest()[:32]

        return self._result(
            allowed=len(reasons) == 0,
            reasons=reasons,
            warnings=warnings,
            market_type=market_type,
            exchange_code=normalized_exchange,
            symbol=normalized_symbol,
            instrument_id=instrument_id,
            assessment_type=assessment_type,
            instrument_key=instrument_key,
        )

    @staticmethod
    def _result(
        *,
        allowed: bool,
        reasons: list[str],
        warnings: list[str],
        market_type: str,
        exchange_code: str,
        symbol: str,
        instrument_id: int | None,
        assessment_type: str | None = None,
        instrument_key: str | None = None,
    ) -> dict[str, Any]:
        return {
            "allowed": allowed,
            "reasons": reasons,
            "warnings": warnings,
            "market_type": market_type,
            "exchange_code": exchange_code,
            "symbol": symbol,
            "instrument_id": instrument_id,
            "assessment_type": assessment_type,
            "instrument_key": instrument_key,
            "disclaimer": REFERENCE_DISCLAIMER,
        }
