"""회원 관심종목 공시 서비스 — STEP69."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from stock_platform.disclosure.models import DartDisclosure
from stock_platform.disclosure.repository import DartDisclosureRepository
from stock_platform.trading.watchlist_repository import WatchlistRepository


DART_VIEWER_BASE = "https://dart.fss.or.kr/dsaf001/main.do"


class UserDisclosureError(ValueError):
    pass


class UserDisclosureService:
    def __init__(self, session: Session) -> None:
        self._session = session
        self._repo = DartDisclosureRepository(session)
        self._watchlist = WatchlistRepository(session)

    def _watchlist_pairs(
        self,
        user_id: int,
        *,
        market_code: str | None = None,
        symbol: str | None = None,
        watchlist_id: int | None = None,
    ) -> list[tuple[str, str, str]]:
        """(market, symbol, symbol_name) — disclosure_enabled만."""

        rows = self._watchlist.list_for_user(user_id)
        result: list[tuple[str, str, str]] = []
        for row in rows:
            if not row.disclosure_enabled:
                continue
            if watchlist_id is not None and int(row.watchlist_id) != int(
                watchlist_id
            ):
                continue
            if market_code and row.market.upper() != market_code.upper():
                continue
            if symbol and row.symbol.upper() != symbol.upper():
                continue
            # DART는 KRX 종목코드 기준 — UPBIT 등은 조회에서 제외
            if row.market.upper() not in {"KRX", "KOSPI", "KOSDAQ"}:
                continue
            result.append(
                (row.market.upper(), row.symbol.upper(), row.symbol_name)
            )
        return result

    def list_disclosures(
        self,
        user_id: int,
        *,
        market_code: str | None = None,
        symbol: str | None = None,
        watchlist_id: int | None = None,
        disclosure_type: str | None = None,
        report_name: str | None = None,
        keyword: str | None = None,
        from_date: date | None = None,
        to_date: date | None = None,
        read_status: str | None = None,
        bookmarked: bool | None = None,
        has_ai_summary: bool | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict[str, Any]:
        all_enabled = self._watchlist_pairs(user_id)
        if not all_enabled:
            return {
                "items": [],
                "page": page,
                "page_size": page_size,
                "total_count": 0,
                "has_next": False,
                "watchlist_empty": True,
                "message": "관심종목을 먼저 등록해 주세요.",
            }

        if symbol and not any(
            p[1] == symbol.upper()
            and (
                not market_code or p[0] == market_code.upper()
            )
            for p in all_enabled
        ):
            raise UserDisclosureError(
                "해당 종목은 관심종목에 없거나 공시 수집이 비활성입니다."
            )

        pairs = self._watchlist_pairs(
            user_id,
            market_code=market_code,
            symbol=symbol,
            watchlist_id=watchlist_id,
        )
        if not pairs:
            return {
                "items": [],
                "page": max(1, page),
                "page_size": max(1, min(page_size, 100)),
                "total_count": 0,
                "has_next": False,
                "watchlist_empty": False,
            }

        name_map = {s: n for _, s, n in pairs}
        stock_codes = list({s for _, s, _ in pairs})
        page = max(1, page)
        page_size = max(1, min(page_size, 100))

        needs_state_filter = (
            read_status in ("read", "unread")
            or bookmarked is not None
            or has_ai_summary is not None
        )

        if needs_state_filter:
            rows = self._repo.list_for_stock_codes(
                stock_codes=stock_codes,
                limit=500,
                offset=0,
                keyword=keyword,
                category_code=disclosure_type,
                report_name=report_name,
                date_from=from_date,
                date_to=to_date,
            )
            states = self._repo.list_user_states(
                user_id=user_id,
                disclosure_ids=[int(r.disclosure_id) for r in rows],
            )
            summaries = self._repo.list_latest_summaries(
                [int(r.disclosure_id) for r in rows]
            )
            filtered: list[DartDisclosure] = []
            for row in rows:
                state = states.get(int(row.disclosure_id))
                if state and state.hidden_at is not None:
                    continue
                is_read = bool(state.is_read) if state else False
                is_bookmarked = bool(state.is_bookmarked) if state else False
                summary = summaries.get(int(row.disclosure_id))
                completed = (
                    summary is not None and summary.status == "COMPLETED"
                )
                if read_status == "read" and not is_read:
                    continue
                if read_status == "unread" and is_read:
                    continue
                if bookmarked is True and not is_bookmarked:
                    continue
                if bookmarked is False and is_bookmarked:
                    continue
                if has_ai_summary is True and not completed:
                    continue
                if has_ai_summary is False and completed:
                    continue
                filtered.append(row)
            total = len(filtered)
            start = (page - 1) * page_size
            page_items = filtered[start : start + page_size]
            page_states = states
            page_summaries = summaries
        else:
            total = self._repo.count_for_stock_codes(
                stock_codes=stock_codes,
                keyword=keyword,
                category_code=disclosure_type,
                report_name=report_name,
                date_from=from_date,
                date_to=to_date,
            )
            offset = (page - 1) * page_size
            page_items = self._repo.list_for_stock_codes(
                stock_codes=stock_codes,
                limit=page_size,
                offset=offset,
                keyword=keyword,
                category_code=disclosure_type,
                report_name=report_name,
                date_from=from_date,
                date_to=to_date,
            )
            page_states = self._repo.list_user_states(
                user_id=user_id,
                disclosure_ids=[int(r.disclosure_id) for r in page_items],
            )
            page_summaries = self._repo.list_latest_summaries(
                [int(r.disclosure_id) for r in page_items]
            )

        items = [
            self._item_dict(
                row,
                states=page_states,
                summaries=page_summaries,
                name_map=name_map,
            )
            for row in page_items
        ]
        start = (page - 1) * page_size
        return {
            "items": items,
            "page": page,
            "page_size": page_size,
            "total_count": total,
            "has_next": start + page_size < total,
            "watchlist_empty": False,
        }

    def get_detail(self, user_id: int, disclosure_id: int) -> dict[str, Any]:
        row = self._repo.get_disclosure(disclosure_id)
        if row is None:
            raise UserDisclosureError("공시를 찾을 수 없습니다.")
        pairs = self._watchlist_pairs(user_id)
        name_map = {s: n for _, s, n in pairs}
        allowed = {s for _, s, _ in pairs}
        stock = (row.stock_code or "").upper()
        if not stock or stock not in allowed:
            raise UserDisclosureError(
                "관심종목과 연결되지 않은 공시입니다."
            )
        states = self._repo.list_user_states(
            user_id=user_id, disclosure_ids=[disclosure_id]
        )
        summaries = self._repo.list_latest_summaries([disclosure_id])
        payload = self._item_dict(
            row,
            states=states,
            summaries=summaries,
            name_map=name_map,
            include_detail=True,
        )
        summary = summaries.get(disclosure_id)
        if summary is not None and summary.status == "COMPLETED":
            payload["ai_summary"] = self._summary_dict(summary)
        elif summary is not None:
            payload["ai_summary"] = {
                "disclosure_id": disclosure_id,
                "status": summary.status,
                "error_code": summary.error_code,
                "is_stale": summary.status == "STALE",
            }
        else:
            payload["ai_summary"] = {
                "disclosure_id": disclosure_id,
                "status": "NOT_REQUESTED",
                "is_stale": False,
            }
        return payload

    def mark_read(
        self, user_id: int, disclosure_id: int, *, read: bool = True
    ) -> dict[str, Any]:
        self.get_detail(user_id, disclosure_id)
        state = self._repo.get_or_create_user_state(
            user_id=user_id, disclosure_id=disclosure_id
        )
        state.is_read = read
        state.read_at = datetime.now(timezone.utc) if read else None
        self._session.commit()
        self._session.refresh(state)
        return {
            "disclosure_id": disclosure_id,
            "is_read": state.is_read,
            "read_at": state.read_at,
        }

    def mark_bookmark(
        self,
        user_id: int,
        disclosure_id: int,
        *,
        bookmarked: bool = True,
    ) -> dict[str, Any]:
        self.get_detail(user_id, disclosure_id)
        state = self._repo.get_or_create_user_state(
            user_id=user_id, disclosure_id=disclosure_id
        )
        state.is_bookmarked = bookmarked
        state.bookmarked_at = (
            datetime.now(timezone.utc) if bookmarked else None
        )
        self._session.commit()
        self._session.refresh(state)
        return {
            "disclosure_id": disclosure_id,
            "is_bookmarked": state.is_bookmarked,
            "bookmarked_at": state.bookmarked_at,
        }

    def read_all(
        self,
        user_id: int,
        *,
        market_code: str | None = None,
        symbol: str | None = None,
    ) -> dict[str, Any]:
        updated = 0
        for _ in range(50):
            listed = self.list_disclosures(
                user_id,
                market_code=market_code,
                symbol=symbol,
                read_status="unread",
                page=1,
                page_size=100,
            )
            items = listed.get("items") or []
            if not items:
                break
            for item in items:
                self.mark_read(
                    user_id, int(item["disclosure_id"]), read=True
                )
                updated += 1
        return {"updated_count": updated, "scope": "watchlist_unread"}

    def unread_count(self, user_id: int) -> dict[str, Any]:
        listed = self.list_disclosures(
            user_id, read_status="unread", page=1, page_size=500
        )
        by_symbol: dict[str, int] = {}
        total = int(listed.get("total_count") or 0)
        for item in listed.get("items") or []:
            sym = str(item.get("symbol") or "")
            if sym:
                by_symbol[sym] = by_symbol.get(sym, 0) + 1
        return {
            "unread_count": total,
            "total": total,
            "by_symbol": [
                {"symbol": s, "count": c}
                for s, c in sorted(by_symbol.items())
            ],
        }

    def recent_ai_summaries(
        self, user_id: int, *, limit: int = 10
    ) -> dict[str, Any]:
        pairs = self._watchlist_pairs(user_id)
        stock_codes = list({s for _, s, _ in pairs})
        name_map = {s: n for _, s, n in pairs}
        rows = self._repo.list_completed_summaries_for_stocks(
            stock_codes=stock_codes,
            limit=max(1, min(limit, 50)),
        )
        items = []
        for disclosure, summary in rows:
            items.append(
                {
                    "disclosure_id": disclosure.disclosure_id,
                    "receipt_no": disclosure.receipt_no,
                    "symbol": (disclosure.stock_code or "").upper(),
                    "symbol_name": name_map.get(
                        (disclosure.stock_code or "").upper(),
                        disclosure.corp_name,
                    ),
                    "report_name": disclosure.report_name,
                    "status": summary.status,
                    "summary": summary.summary_text,
                    "generated_at": summary.generated_at,
                    "model_name": summary.model_name,
                }
            )
        return {"items": items, "total": len(items)}

    def _item_dict(
        self,
        row: DartDisclosure,
        *,
        states: dict,
        summaries: dict,
        name_map: dict[str, str],
        include_detail: bool = False,
    ) -> dict[str, Any]:
        state = states.get(int(row.disclosure_id))
        summary = summaries.get(int(row.disclosure_id))
        stock = (row.stock_code or "").upper()
        status = summary.status if summary else "NOT_REQUESTED"
        payload: dict[str, Any] = {
            "disclosure_id": row.disclosure_id,
            "receipt_no": row.receipt_no,
            "corp_code": row.corp_code,
            "market_code": "KRX",
            "symbol": stock,
            "symbol_name": name_map.get(stock, row.corp_name),
            "corp_name": row.corp_name,
            "report_name": row.report_name,
            "disclosure_type": row.category_code,
            "submitted_at": (
                datetime.combine(
                    row.receipt_date, datetime.min.time(), tzinfo=timezone.utc
                ).isoformat()
                if row.receipt_date
                else None
            ),
            "original_url": f"{DART_VIEWER_BASE}?rcpNo={row.receipt_no}",
            "is_correction": bool(row.is_correction),
            "related_receipt_no": row.related_receipt_no,
            "is_read": bool(state.is_read) if state else False,
            "is_bookmarked": bool(state.is_bookmarked) if state else False,
            "ai_summary_status": status,
            "has_ai_summary": status == "COMPLETED",
        }
        if include_detail:
            payload["filer_name"] = row.filer_name
            payload["remark"] = row.remark
            payload["importance_score"] = float(row.importance_score)
            # 원문 HTML 미저장 — 메타 텍스트만 제공
            payload["body_text"] = self._build_source_text(row)
            payload["body_note"] = (
                "공시 본문 HTML은 저장하지 않습니다. "
                "원문 링크로 확인해 주세요."
            )
        return payload

    @staticmethod
    def _build_source_text(row: DartDisclosure) -> str:
        parts = [
            f"회사명: {row.corp_name}",
            f"종목코드: {row.stock_code or ''}",
            f"법인코드: {row.corp_code}",
            f"보고서명: {row.report_name}",
            f"공시유형: {row.category_code}",
            f"접수일: {row.receipt_date}",
            f"접수번호: {row.receipt_no}",
            f"제출인: {row.filer_name or ''}",
            f"비고: {row.remark or ''}",
            f"정정여부: {'Y' if row.is_correction else 'N'}",
            f"관련접수번호: {row.related_receipt_no or ''}",
        ]
        return "\n".join(parts)

    @staticmethod
    def _summary_dict(summary) -> dict[str, Any]:
        return {
            "disclosure_id": summary.disclosure_id,
            "status": summary.status,
            "summary": summary.summary_text,
            "key_points": summary.key_points_json or [],
            "risk_factors": summary.risk_factors_json or [],
            "financial_impacts": summary.financial_impacts_json or [],
            "important_numbers": summary.important_numbers_json or [],
            "uncertainty_notes": summary.uncertainty_notes_json or [],
            "model_name": summary.model_name,
            "prompt_version": summary.prompt_version,
            "generated_at": summary.generated_at,
            "is_stale": summary.status == "STALE",
            "disclaimer": (
                "AI가 생성한 요약으로 오류나 누락이 있을 수 있습니다. "
                "중요한 판단은 공시 원문을 확인하세요."
            ),
        }
