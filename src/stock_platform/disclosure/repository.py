from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from stock_platform.disclosure.models import DartCorp, DartDisclosure


class DartCorpRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def upsert_many(self, rows: list[dict]) -> int:
        if not rows:
            return 0

        stmt = insert(DartCorp).values(rows)
        stmt = stmt.on_conflict_do_update(
            index_elements=[DartCorp.corp_code],
            set_={
                "corp_name": stmt.excluded.corp_name,
                "stock_code": stmt.excluded.stock_code,
                "modify_date": stmt.excluded.modify_date,
                "is_active": stmt.excluded.is_active,
                "raw_data": stmt.excluded.raw_data,
                "updated_at": stmt.excluded.updated_at,
            },
        )
        result = self._session.execute(stmt)
        self._session.commit()
        return result.rowcount or len(rows)

    def find_by_stock_code(self, stock_code: str) -> DartCorp | None:
        stmt = select(DartCorp).where(
            DartCorp.stock_code == stock_code.strip().upper(),
            DartCorp.is_active.is_(True),
        )
        return self._session.scalar(stmt)

    def list_listed(self, *, limit: int = 5000) -> list[DartCorp]:
        stmt = (
            select(DartCorp)
            .where(
                DartCorp.is_active.is_(True),
                DartCorp.stock_code.is_not(None),
                DartCorp.stock_code != "",
            )
            .order_by(DartCorp.stock_code.asc())
            .limit(limit)
        )
        return list(self._session.scalars(stmt))


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
                "category_code": stmt.excluded.category_code,
                "importance_score": stmt.excluded.importance_score,
                "is_correction": stmt.excluded.is_correction,
                "related_receipt_no": stmt.excluded.related_receipt_no,
                "raw_data": stmt.excluded.raw_data,
            },
        )

        result = self._session.execute(stmt)
        self._session.commit()
        return result.rowcount or len(rows)

    def latest_receipt_date(self, corp_code: str) -> date | None:
        stmt = select(func.max(DartDisclosure.receipt_date)).where(
            DartDisclosure.corp_code == corp_code
        )
        return self._session.scalar(stmt)

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
            DartDisclosure.importance_score.desc(),
            DartDisclosure.receipt_date.desc(),
            DartDisclosure.disclosure_id.desc(),
        ).limit(limit)

        return list(self._session.scalars(stmt))
