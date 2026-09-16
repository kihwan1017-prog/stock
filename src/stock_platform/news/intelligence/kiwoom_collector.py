"""KIWOOM TOP10 NAVER news + DART disclosure collector (SHADOW feed only)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Any

from sqlalchemy.orm import Session

from stock_platform.common.logger import logger
from stock_platform.common.settings import Settings, get_settings
from stock_platform.disclosure.classifier import classify_disclosure
from stock_platform.disclosure.dart_client import DartClient, DartError
from stock_platform.disclosure.repository import (
    DartCorpRepository,
    DartDisclosureRepository,
)
from stock_platform.disclosure.service import DartDisclosureService
from stock_platform.news.intelligence.kiwoom_targets import (
    list_kiwoom_top10_targets,
    resolve_default_kiwoom_uba,
)
from stock_platform.news.naver_client import NaverNewsClient, NaverNewsError
from stock_platform.news.repository import NewsRepository
from stock_platform.news.service import NewsService


@dataclass
class KiwoomTop10CollectResult:
    news_targets: list[dict[str, Any]] = field(default_factory=list)
    dart_targets: list[dict[str, Any]] = field(default_factory=list)
    news_synced: int = 0
    news_saved: int = 0
    news_failed: int = 0
    dart_synced: int = 0
    dart_saved: int = 0
    dart_mapping_failed: int = 0
    dart_failed: int = 0
    dart_mapping_rate: float | None = None
    major_disclosures: list[dict[str, Any]] = field(default_factory=list)
    last_error: str | None = None
    had_new_items: bool = False
    published_at_before: str | None = None
    published_at_after: str | None = None
    last_new_article_at: str | None = None


class KiwoomTop10NewsDartCollector:
    """TOP10 종목 뉴스/공시 수집. REAL Fresh Golden Cross 비연동."""

    def __init__(
        self,
        session: Session,
        *,
        settings: Settings | None = None,
    ) -> None:
        self._session = session
        self._settings = settings or get_settings()

    async def collect(
        self,
        *,
        include_news: bool = True,
        include_dart: bool = True,
        user_broker_account_id: int | None = None,
    ) -> KiwoomTop10CollectResult:
        result = KiwoomTop10CollectResult()
        uba = user_broker_account_id or resolve_default_kiwoom_uba(
            self._session
        )
        targets = list_kiwoom_top10_targets(
            self._session,
            user_broker_account_id=uba,
            limit=int(
                getattr(self._settings, "kiwoom_top10_news_target_max", 10)
            ),
        )
        result.news_targets = targets
        result.dart_targets = []
        # dart_targets는 mapping 결과와 함께 _collect_dart에서 채움

        repo = NewsRepository(self._session)
        before = repo.latest_published_at(source_code="NAVER")
        if isinstance(before, datetime):
            if before.tzinfo is None:
                before = before.replace(tzinfo=timezone.utc)
            result.published_at_before = before.isoformat()

        if include_news and targets:
            await self._collect_news(result, targets)
        if include_dart and targets:
            await self._collect_dart(result, targets)

        after = repo.latest_published_at(source_code="NAVER")
        after_dt: datetime | None = None
        if isinstance(after, datetime):
            if after.tzinfo is None:
                after = after.replace(tzinfo=timezone.utc)
            after_dt = after
            result.published_at_after = after.isoformat()

        before_dt = (
            datetime.fromisoformat(result.published_at_before)
            if result.published_at_before
            else None
        )
        if before_dt is None and after_dt is not None:
            result.had_new_items = True
            result.last_new_article_at = result.published_at_after
        elif before_dt is not None and after_dt is not None:
            result.had_new_items = after_dt > before_dt or result.news_saved > 0
            result.last_new_article_at = (
                result.published_at_after
                if result.had_new_items
                else result.published_at_before
            )
        elif result.news_saved > 0 or result.dart_saved > 0:
            result.had_new_items = True
            result.last_new_article_at = (
                result.published_at_after or datetime.now(timezone.utc).isoformat()
            )
        return result

    async def _collect_news(
        self,
        result: KiwoomTop10CollectResult,
        targets: list[dict[str, Any]],
    ) -> None:
        settings = self._settings
        has_naver = bool(
            str(getattr(settings, "naver_client_id", "") or "").strip()
        ) and bool(
            str(getattr(settings, "naver_client_secret", "") or "").strip()
        )
        if not has_naver:
            result.last_error = "NAVER_CREDENTIALS_MISSING"
            return

        display = max(
            1,
            min(
                int(getattr(settings, "kiwoom_top10_news_display", 10)),
                30,
            ),
        )
        naver = NaverNewsClient(settings=settings)
        # summarize 경로 미사용 — Ollama 더미 주입 없이 NewsService.sync만
        from stock_platform.ai.ollama_client import OllamaClient

        ollama = OllamaClient(settings=settings)
        service = NewsService(
            repository=NewsRepository(self._session),
            naver_client=naver,
            ollama_client=ollama,
            model_name=str(getattr(settings, "ollama_model", "") or "unused"),
        )
        try:
            for target in targets:
                symbol = str(target["symbol"])
                query = str(target.get("query") or symbol)
                try:
                    sync = await service.sync_detailed(
                        exchange_code="KRX",
                        symbol=symbol,
                        query=query,
                        display=display,
                    )
                    result.news_synced += 1
                    result.news_saved += int(sync.saved_count)
                except (NaverNewsError, ValueError, Exception) as exc:  # noqa: BLE001
                    result.news_failed += 1
                    logger.info(
                        "kiwoom_top10_news_item_failed",
                        symbol=symbol,
                        error=str(exc)[:200],
                    )
        finally:
            await naver.aclose()
            await ollama.aclose()

    async def _collect_dart(
        self,
        result: KiwoomTop10CollectResult,
        targets: list[dict[str, Any]],
    ) -> None:
        settings = self._settings
        if not str(getattr(settings, "dart_api_key", "") or "").strip():
            if result.last_error:
                result.last_error = f"{result.last_error};DART_API_KEY_MISSING"
            else:
                result.last_error = "DART_API_KEY_MISSING"
            return

        days = max(
            1,
            min(int(getattr(settings, "kiwoom_top10_dart_lookback_days", 7)), 30),
        )
        end_date = date.today()
        start_date = end_date - timedelta(days=days)
        client = DartClient(settings=settings)
        corp_repo = DartCorpRepository(self._session)
        disclosure_repo = DartDisclosureRepository(self._session)
        service = DartDisclosureService(
            client,
            disclosure_repo,
            corp_repository=corp_repo,
        )
        mapped = 0
        try:
            for target in targets:
                symbol = str(target["symbol"])
                corp = corp_repo.find_by_stock_code(symbol)
                result.dart_targets.append(
                    {
                        **target,
                        "corp_code": corp.corp_code if corp else None,
                        "mapped": corp is not None,
                    }
                )
                try:
                    sync = await service.sync_by_stock_code(
                        stock_code=symbol,
                        start_date=start_date,
                        end_date=end_date,
                        resume=True,
                        auto_sync_corps=False,
                    )
                    result.dart_synced += 1
                    result.dart_saved += int(sync.saved_count)
                    mapped += 1
                except LookupError:
                    result.dart_mapping_failed += 1
                except (DartError, Exception) as exc:  # noqa: BLE001
                    result.dart_failed += 1
                    logger.info(
                        "kiwoom_top10_dart_item_failed",
                        symbol=symbol,
                        error=str(exc)[:200],
                    )
            total = len(targets) or 1
            result.dart_mapping_rate = round(
                mapped / float(total),
                4,
            )
            # MAJOR 공시 샘플 (알림/shadow용) — collect lookback보다 넓게 스캔
            major_days = max(days, 30)
            major_start = end_date - timedelta(days=major_days)
            try:
                for target in targets:
                    symbol = str(target["symbol"])
                    rows = disclosure_repo.list_context(
                        stock_code=symbol,
                        start_date=major_start,
                        end_date=end_date,
                        limit=20,
                    )
                    for row in rows:
                        cat = str(getattr(row, "category_code", "") or "")
                        score = getattr(row, "importance_score", 0)
                        if not cat or cat == "OTHER":
                            cat, score, _, _ = classify_disclosure(
                                str(row.report_name or ""),
                                getattr(row, "remark", None),
                            )
                        if cat != "MAJOR":
                            continue
                        result.major_disclosures.append(
                            {
                                "symbol": symbol,
                                "receipt_no": row.receipt_no,
                                "report_name": row.report_name,
                                "receipt_date": (
                                    row.receipt_date.isoformat()
                                    if row.receipt_date
                                    else None
                                ),
                                "category_code": cat,
                                "importance_score": str(score),
                            }
                        )
            except Exception as exc:  # noqa: BLE001
                logger.info(
                    "kiwoom_top10_major_scan_failed",
                    error=str(exc)[:200],
                )
        finally:
            await client.aclose()


def result_as_dict(result: KiwoomTop10CollectResult) -> dict[str, Any]:
    return asdict(result)
