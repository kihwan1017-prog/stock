"""Collector tick 이후 fail-isolated intelligence glue."""

from __future__ import annotations

from typing import Any

from stock_platform.common.logger import logger
from stock_platform.database.session import get_session_factory
from stock_platform.news.collector_constants import (
    SOURCE_CODE_UPBIT_NOTICE,
)
from stock_platform.news.repository import NewsRepository
from stock_platform.operation.news_intelligence_shadow.service import (
    NewsIntelligenceShadowService,
)


def after_upbit_collect_tick(aggregate: dict[str, Any]) -> dict[str, Any]:
    """UPBIT collect 성공 후 notice → shadow/telegram.

    REAL AI Gate / scanner_exclude_caution 비수정.
    """

    out: dict[str, Any] = {"ok": True, "shadow": None}
    session_factory = get_session_factory()
    session = session_factory()
    try:
        notice_payload = (aggregate.get("sources") or {}).get(
            SOURCE_CODE_UPBIT_NOTICE
        )
        samples: list[dict[str, Any]] = []
        if isinstance(notice_payload, dict):
            raw_samples = notice_payload.get("samples") or []
            if isinstance(raw_samples, list):
                samples = [s for s in raw_samples if isinstance(s, dict)]

        # sample이 얇으면 최근 notice 보강
        if len(samples) < 3:
            repo = NewsRepository(session)
            recent = repo.list_by_source_codes(
                source_codes=[SOURCE_CODE_UPBIT_NOTICE],
                limit=20,
            )
            for article in recent:
                raw = article.raw_data if isinstance(article.raw_data, dict) else {}
                samples.append(
                    {
                        "article_id": int(article.article_id),
                        "external_id": raw.get("external_id"),
                        "title": article.title,
                        "category": raw.get("category"),
                        "url": article.original_link,
                        "published_at": (
                            article.published_at.isoformat()
                            if article.published_at
                            else None
                        ),
                    }
                )

        svc = NewsIntelligenceShadowService(session)
        if not svc.enabled():
            out["shadow"] = {"skipped": True, "reason": "SHADOW_DISABLED"}
            return out
        out["shadow"] = svc.ingest_upbit_notices(samples)
        return out
    except Exception as exc:  # noqa: BLE001
        session.rollback()
        logger.warning(
            "after_upbit_collect_tick_failed",
            error=f"{type(exc).__name__}: {exc}"[:300],
        )
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:300]}
    finally:
        session.close()


def after_kiwoom_collect_tick(result: dict[str, Any]) -> dict[str, Any]:
    """KIWOOM TOP10 DART MAJOR → shadow/telegram."""

    out: dict[str, Any] = {"ok": True, "shadow": None}
    session_factory = get_session_factory()
    session = session_factory()
    try:
        svc = NewsIntelligenceShadowService(session)
        if not svc.enabled():
            out["shadow"] = {"skipped": True, "reason": "SHADOW_DISABLED"}
            return out
        majors = result.get("major_disclosures") or []
        if not isinstance(majors, list):
            majors = []
        out["shadow"] = svc.ingest_kiwoom_major_disclosures(
            [m for m in majors if isinstance(m, dict)]
        )
        return out
    except Exception as exc:  # noqa: BLE001
        session.rollback()
        logger.warning(
            "after_kiwoom_collect_tick_failed",
            error=f"{type(exc).__name__}: {exc}"[:300],
        )
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:300]}
    finally:
        session.close()
