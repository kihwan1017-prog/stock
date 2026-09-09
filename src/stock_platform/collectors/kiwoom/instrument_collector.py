"""키움 종목정보 리스트[ka10099] collector.

공식 샘플(Kiwoom-Securities/Kiwoom-REST-API
examples/국내주식/종목정보/list_domestic_stocks.py)만 사용한다.
미문서 TR ID는 추측하지 않는다.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Final

import structlog

from stock_platform.broker.kiwoom.market.client import KiwoomRestClient
from stock_platform.collectors.kiwoom.pagination import ContinuationState


logger = structlog.get_logger(__name__)


class KiwoomInstrumentCollectionError(RuntimeError):
    """키움 종목 마스터 수집 실패."""


# 공식 샘플 Args: mrkt_tp
DOCUMENTED_MARKET_TYPES: Final[dict[str, str]] = {
    "0": "KOSPI",
    "10": "KOSDAQ",
    "30": "K-OTC",
    "50": "KONEX",
    "60": "ETN",
    "70": "LOSS_LIMIT_ETN",
    "80": "GOLD_SPOT",
    "90": "VOLATILITY_ETN",
    "2": "INFRA_FUND",
    "3": "ELW",
    "4": "MUTUAL_FUND",
    "5": "SUBSCRIPTION_WARRANT",
    "6": "REIT",
    "7": "SUBSCRIPTION_WARRANT_CERT",
    "8": "ETF",
    "9": "HIGH_YIELD_FUND",
}

# Candidate universe에 쓰는 기본 시장 (공식 mrkt_tp만)
DEFAULT_MARKET_TYPES: Final[tuple[str, ...]] = ("0", "10", "8", "60")

# 공식 샘플 TABLE_KEYS / COLUMNS
LIST_KEYS: Final[tuple[str, ...]] = ("list",)
OFFICIAL_FIELD_KEYS: Final[tuple[str, ...]] = (
    "code",
    "name",
    "listCount",
    "auditInfo",
    "regDay",
    "lastPrice",
    "state",
    "marketCode",
    "marketName",
    "upName",
    "upSizeName",
    "orderWarning",
    "companyClassName",
    "nxtEnable",
)


@dataclass(frozen=True, slots=True)
class KiwoomInstrumentDTO:
    """collector 표준 출력."""

    symbol: str
    name: str
    exchange_code: str
    asset_type: str
    is_active: bool
    market_segment: str
    trading_status: str
    is_etf: bool
    is_etn: bool
    listed_date: date | None
    extra_data: dict[str, Any]


class KiwoomInstrumentCollector:
    """키움 REST ka10099 종목 마스터 수집기."""

    API_ID: Final[str] = "ka10099"
    ENDPOINT: Final[str] = "/api/dostk/stkinfo"

    def __init__(
        self,
        client: KiwoomRestClient,
        *,
        page_delay_seconds: float = 0.2,
    ) -> None:
        self._client = client
        self._page_delay_seconds = max(0.0, float(page_delay_seconds))

    async def collect(
        self,
        *,
        market_types: tuple[str, ...] | list[str] | None = None,
        max_pages: int = 100,
    ) -> list[KiwoomInstrumentDTO]:
        """시장구분별 종목 리스트를 연속조회한다."""

        if max_pages <= 0:
            raise ValueError("max_pages must be greater than zero")

        requested = tuple(
            str(item).strip()
            for item in (market_types or DEFAULT_MARKET_TYPES)
            if str(item).strip()
        )
        if not requested:
            raise ValueError("market_types is required")

        unknown = [item for item in requested if item not in DOCUMENTED_MARKET_TYPES]
        if unknown:
            raise ValueError(
                f"undocumented mrkt_tp: {unknown}; "
                f"allowed={sorted(DOCUMENTED_MARKET_TYPES)}"
            )

        collected: list[KiwoomInstrumentDTO] = []
        for index, mrkt_tp in enumerate(requested):
            page_rows = await self._collect_market(
                mrkt_tp=mrkt_tp,
                max_pages=max_pages,
            )
            collected.extend(page_rows)
            if index + 1 < len(requested) and self._page_delay_seconds:
                await asyncio.sleep(self._page_delay_seconds)

        return collected

    async def _collect_market(
        self,
        *,
        mrkt_tp: str,
        max_pages: int,
    ) -> list[KiwoomInstrumentDTO]:
        continuation = ContinuationState()
        rows: list[KiwoomInstrumentDTO] = []
        request_body = {"mrkt_tp": mrkt_tp}

        for page_number in range(1, max_pages + 1):
            response = await self._client.request(
                api_id=self.API_ID,
                endpoint=self.ENDPOINT,
                body=request_body,
                continue_yn=continuation.continue_yn,
                next_key=continuation.next_key,
            )
            parsed = parse_instrument_rows(
                response.body,
                mrkt_tp=mrkt_tp,
            )
            rows.extend(parsed)

            logger.info(
                "kiwoom_instrument_page_collected",
                mrkt_tp=mrkt_tp,
                page=page_number,
                row_count=len(parsed),
                has_more=response.has_more,
            )

            continuation = ContinuationState.from_response(
                has_more=response.has_more,
                next_key=response.next_key,
            )
            if not continuation.has_more:
                break

            if self._page_delay_seconds:
                await asyncio.sleep(self._page_delay_seconds)
        else:
            raise KiwoomInstrumentCollectionError(
                f"Exceeded max_pages={max_pages} for mrkt_tp={mrkt_tp}"
            )

        return rows


def parse_instrument_rows(
    response_body: dict[str, Any],
    *,
    mrkt_tp: str,
) -> list[KiwoomInstrumentDTO]:
    """공식 응답 list 배열을 DTO로 변환한다."""

    records = _extract_list_records(response_body)
    parsed: list[KiwoomInstrumentDTO] = []
    seen: set[str] = set()

    for record in records:
        dto = _parse_record(record, mrkt_tp=mrkt_tp)
        if dto is None:
            continue
        if dto.symbol in seen:
            continue
        seen.add(dto.symbol)
        parsed.append(dto)

    return parsed


def _extract_list_records(response_body: dict[str, Any]) -> list[dict[str, Any]]:
    raw = response_body.get("list")
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, dict)]

    # 공식 샘플은 list 키. 빈 배열이면 빈 결과.
    return []


def _parse_record(
    record: dict[str, Any],
    *,
    mrkt_tp: str,
) -> KiwoomInstrumentDTO | None:
    symbol = _normalize_symbol(record.get("code"))
    name = str(record.get("name") or "").strip()
    if not symbol or not name:
        return None

    segment = DOCUMENTED_MARKET_TYPES.get(mrkt_tp, "UNKNOWN")
    is_etf = mrkt_tp == "8" or segment == "ETF"
    is_etn = mrkt_tp in {"60", "70", "90"} or segment.endswith("ETN")
    asset_type = "ETF" if (is_etf or is_etn) else "STOCK"
    trading_status = str(record.get("state") or "").strip()
    is_active = _is_tradable_state(trading_status)

    extra = {
        "mrkt_tp": mrkt_tp,
        "market_segment": segment,
        "list_count": record.get("listCount"),
        "audit_info": record.get("auditInfo"),
        "reg_day": record.get("regDay"),
        "last_price": record.get("lastPrice"),
        "state": trading_status,
        "market_code": record.get("marketCode"),
        "market_name": record.get("marketName"),
        "up_name": record.get("upName"),
        "up_size_name": record.get("upSizeName"),
        "order_warning": record.get("orderWarning"),
        "company_class_name": record.get("companyClassName"),
        "nxt_enable": record.get("nxtEnable"),
        "is_etf": is_etf,
        "is_etn": is_etn,
    }

    return KiwoomInstrumentDTO(
        symbol=symbol,
        name=name,
        exchange_code="KRX",
        asset_type=asset_type,
        is_active=is_active,
        market_segment=segment,
        trading_status=trading_status,
        is_etf=is_etf,
        is_etn=is_etn,
        listed_date=_parse_listed_date(record.get("regDay")),
        extra_data=extra,
    )


def _normalize_symbol(raw: Any) -> str:
    text = str(raw or "").strip().upper()
    if text.startswith("A") and len(text) == 7 and text[1:].isdigit():
        text = text[1:]
    return text


def _parse_listed_date(raw: Any) -> date | None:
    text = str(raw or "").strip().replace("-", "")
    if len(text) != 8 or not text.isdigit():
        return None
    try:
        return datetime.strptime(text, "%Y%m%d").date()
    except ValueError:
        return None


def _is_tradable_state(state: str) -> bool:
    """종목상태 문자열에서 거래 불가 표기를 보수적으로 판정한다."""

    if not state:
        return True
    halted_tokens = ("거래정지", "정지", "퇴출", "정리매매")
    return not any(token in state for token in halted_tokens)
