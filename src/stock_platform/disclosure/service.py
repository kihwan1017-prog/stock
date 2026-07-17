from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from stock_platform.disclosure.classifier import classify_disclosure
from stock_platform.disclosure.dart_client import DartClient
from stock_platform.disclosure.repository import (
    DartCorpRepository,
    DartDisclosureRepository,
)


@dataclass(slots=True)
class DartSyncResult:
    corp_code: str
    stock_code: str | None
    start_date: date
    end_date: date
    fetched_count: int
    saved_count: int
    resumed: bool


class DartDisclosureService:
    def __init__(
        self,
        client: DartClient,
        repository: DartDisclosureRepository,
        corp_repository: DartCorpRepository | None = None,
    ) -> None:
        self._client = client
        self._repository = repository
        self._corp_repository = corp_repository

    async def sync_corp_codes(self) -> int:
        if self._corp_repository is None:
            raise RuntimeError("corp_repository is required")

        rows = await self._client.fetch_corp_codes()
        now = datetime.now(timezone.utc)
        for row in rows:
            row["updated_at"] = now
        return self._corp_repository.upsert_many(rows)

    async def sync(
        self,
        *,
        corp_code: str,
        start_date: date,
        end_date: date,
        resume: bool = True,
        stock_code: str | None = None,
    ) -> DartSyncResult:
        normalized_corp = corp_code.strip()
        effective_start = start_date
        resumed = False

        if resume:
            latest = self._repository.latest_receipt_date(
                normalized_corp
            )
            if latest is not None:
                candidate = latest + timedelta(days=1)
                if candidate > effective_start:
                    effective_start = candidate
                    resumed = True

        if effective_start > end_date:
            return DartSyncResult(
                corp_code=normalized_corp,
                stock_code=stock_code,
                start_date=effective_start,
                end_date=end_date,
                fetched_count=0,
                saved_count=0,
                resumed=resumed,
            )

        page_no = 1
        all_rows: list[dict] = []

        while True:
            body = await self._client.search_disclosures(
                corp_code=normalized_corp,
                start_date=effective_start,
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

                report_name = str(item["report_nm"])
                remark = item.get("rm") or None
                category, importance, is_correction, _ = (
                    classify_disclosure(report_name, remark)
                )

                item_stock = (
                    str(item.get("stock_code") or "").strip()
                    or stock_code
                    or None
                )

                all_rows.append(
                    {
                        "receipt_no": item["rcept_no"],
                        "corp_code": item["corp_code"],
                        "corp_name": item["corp_name"],
                        "stock_code": item_stock,
                        "report_name": report_name,
                        "filer_name": item.get("flr_nm") or None,
                        "receipt_date": receipt_date,
                        "remark": remark,
                        "category_code": category,
                        "importance_score": importance,
                        "is_correction": is_correction,
                        "related_receipt_no": None,
                        "raw_data": item,
                    }
                )

            total_page = int(body.get("total_page") or 0)
            if page_no >= total_page:
                break
            page_no += 1

        # 정정공시 → 동일 종목·유사 제목의 최근 원공시 연결 시도
        self._link_corrections(all_rows)

        saved = self._repository.upsert_many(all_rows)
        return DartSyncResult(
            corp_code=normalized_corp,
            stock_code=stock_code,
            start_date=effective_start,
            end_date=end_date,
            fetched_count=len(all_rows),
            saved_count=saved,
            resumed=resumed,
        )

    async def sync_by_stock_code(
        self,
        *,
        stock_code: str,
        start_date: date,
        end_date: date,
        resume: bool = True,
    ) -> DartSyncResult:
        if self._corp_repository is None:
            raise RuntimeError("corp_repository is required")

        corp = self._corp_repository.find_by_stock_code(stock_code)
        if corp is None:
            raise LookupError(
                f"DART corp not found for stock_code={stock_code}"
            )

        return await self.sync(
            corp_code=corp.corp_code,
            start_date=start_date,
            end_date=end_date,
            resume=resume,
            stock_code=corp.stock_code,
        )

    @staticmethod
    def _link_corrections(rows: list[dict]) -> None:
        originals = [
            row for row in rows if not row["is_correction"]
        ]
        for row in rows:
            if not row["is_correction"]:
                continue

            base_name = row["report_name"].replace("정정", "").strip()
            for original in reversed(originals):
                if original["corp_code"] != row["corp_code"]:
                    continue
                if original["receipt_date"] > row["receipt_date"]:
                    continue
                if base_name and base_name in original["report_name"]:
                    row["related_receipt_no"] = original["receipt_no"]
                    break
