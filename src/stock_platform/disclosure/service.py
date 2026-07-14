from __future__ import annotations

from datetime import date, datetime

from stock_platform.disclosure.dart_client import DartClient
from stock_platform.disclosure.repository import (
    DartDisclosureRepository,
)


class DartDisclosureService:
    def __init__(
        self,
        client: DartClient,
        repository: DartDisclosureRepository,
    ) -> None:
        self._client = client
        self._repository = repository

    async def sync(
        self,
        *,
        corp_code: str,
        start_date: date,
        end_date: date,
    ) -> int:
        page_no = 1
        all_rows: list[dict] = []

        while True:
            body = await self._client.search_disclosures(
                corp_code=corp_code,
                start_date=start_date,
                end_date=end_date,
                page_no=page_no,
                page_count=100,
            )

            items = body.get("list") or []
            for item in items:
                receipt_date = datetime.strptime(
                    str(item["rcept_dt"]),
                    "%Y%m%d",
                ).date()

                all_rows.append(
                    {
                        "receipt_no": item["rcept_no"],
                        "corp_code": item["corp_code"],
                        "corp_name": item["corp_name"],
                        "stock_code": (
                            item.get("stock_code") or None
                        ),
                        "report_name": item["report_nm"],
                        "filer_name": (
                            item.get("flr_nm") or None
                        ),
                        "receipt_date": receipt_date,
                        "remark": item.get("rm") or None,
                        "raw_data": item,
                    }
                )

            total_page = int(body.get("total_page") or 0)
            if page_no >= total_page:
                break
            page_no += 1

        return self._repository.upsert_many(all_rows)
