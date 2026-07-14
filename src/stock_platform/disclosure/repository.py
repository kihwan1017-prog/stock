from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from stock_platform.disclosure.models import DartDisclosure


class DartDisclosureRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def upsert_many(self, rows: list[dict]) -> int:
        if not rows:
            return 0

        stmt = insert(DartDisclosure).values(rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=[DartDisclosure.receipt_no],
            set_={
                "corp_code": stmt.excluded.corp_code,
                "corp_name": stmt.excluded.corp_name,
                "stock_code": stmt.excluded.stock_code,
                "report_name": stmt.excluded.report_name,
                "filer_name": stmt.excluded.filer_name,
                "receipt_date": stmt.excluded.receipt_date,
                "remark": stmt.excluded.remark,
                "raw_data": stmt.excluded.raw_data,
            },
        )

        result = self._session.execute(stmt)
        self._session.commit()
        return result.rowcount or len(rows)

    def list_context(
        self,
        *,
        stock_code: str,
        start_date: date | None = None,
        end_date: date | None = None,
        limit: int = 20,
    ) -> list[DartDisclosure]:
        stmt = select(DartDisclosure).where(
            DartDisclosure.stock_code == stock_code
        )

        if start_date is not None:
            stmt = stmt.where(
                DartDisclosure.receipt_date >= start_date
            )

        if end_date is not None:
            stmt = stmt.where(
                DartDisclosure.receipt_date <= end_date
            )

        stmt = stmt.order_by(
            DartDisclosure.receipt_date.desc(),
            DartDisclosure.disclosure_id.desc(),
        ).limit(limit)

        return list(self._session.scalars(stmt))
