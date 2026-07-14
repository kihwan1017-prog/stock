from __future__ import annotations

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
