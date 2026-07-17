from collections.abc import Callable
from datetime import date, datetime
from decimal import Decimal
import httpx

from stock_platform.market.models import DailyCandle, Quote

class KiwoomMarketClient:
    def __init__(self, base_url: str, token_provider: Callable[[], str],
                 timeout_seconds: float = 20) -> None:
        self.base_url = base_url.rstrip("/")
        self.token_provider = token_provider
        self.timeout_seconds = timeout_seconds

    def _headers(self, api_id: str) -> dict[str, str]:
        return {
            "authorization": f"Bearer {self.token_provider()}",
            "api-id": api_id,
            "content-type": "application/json;charset=UTF-8",
        }

    async def get_quote(self, symbol: str) -> Quote:
        # 실제 endpoint/api-id와 필드명은 프로젝트의 Kiwoom 공식 명세 mapper에 맞춰 조정합니다.
        payload = {"stk_cd": symbol}
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.post(
                f"{self.base_url}/api/dostk/stkinfo",
                headers=self._headers("ka10001"),
                json=payload,
            )
            response.raise_for_status()
        row = response.json()
        price = Decimal(str(row.get("cur_prc", "0")).replace("+", "").replace("-", ""))
        return Quote(
            market="KRX",
            symbol=symbol,
            price=price,
            change=Decimal(str(row.get("pred_pre", "0")).replace("+", "")),
            change_rate=Decimal(str(row.get("flu_rt", "0")).replace("+", "")),
            volume=Decimal(str(row.get("trde_qty", "0"))),
            quoted_at=datetime.now().astimezone(),
        )

    async def get_daily_candles(self, symbol: str, base_date: date,
                                adjusted_price: bool = True) -> list[DailyCandle]:
        payload = {
            "stk_cd": symbol,
            "base_dt": base_date.strftime("%Y%m%d"),
            "upd_stkpc_tp": "1" if adjusted_price else "0",
        }
        async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
            response = await client.post(
                f"{self.base_url}/api/dostk/chart",
                headers=self._headers("ka10081"),
                json=payload,
            )
            response.raise_for_status()
        body = response.json()
        rows = body.get("stk_dt_pole_chart_qry", body.get("output", []))
        result = []
        for row in rows:
            result.append(DailyCandle(
                market="KRX",
                symbol=symbol,
                candle_date=datetime.strptime(str(row["dt"]), "%Y%m%d").date(),
                open_price=Decimal(str(row["open_pric"]).replace("+", "").replace("-", "")),
                high_price=Decimal(str(row["high_pric"]).replace("+", "").replace("-", "")),
                low_price=Decimal(str(row["low_pric"]).replace("+", "").replace("-", "")),
                close_price=Decimal(str(row["cur_prc"]).replace("+", "").replace("-", "")),
                volume=Decimal(str(row.get("trde_qty", "0"))),
                trade_amount=None,
            ))
        return result
