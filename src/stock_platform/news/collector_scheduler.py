"""STEP N2 — News/Notice Collector Scheduler (기본 OFF, failure isolated)."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger

from dataclasses import asdict

from stock_platform.common.logger import logger
from stock_platform.common.settings import get_settings
from stock_platform.database.session import get_session_factory
from stock_platform.news.collector_constants import (
    SOURCE_CODE_CRYPTO_NEWS,
    SOURCE_CODE_UPBIT_NOTICE,
)
from stock_platform.news.crypto_news_collector import (
    CryptoNewsCollector,
    resolve_crypto_news_provider,
)
from stock_platform.news.upbit_notice_collector import UpbitNoticeCollector


class UpbitNewsNoticeCollectorScheduler:
    """Scanner/Shadow/AI 스케줄러와 완전 분리."""

    NOTICE_JOB_ID = "upbit_notice_collection"
    CRYPTO_JOB_ID = "crypto_news_collection"

    def __init__(self) -> None:
        settings = get_settings()
        self._scheduler = AsyncIOScheduler(
            timezone=settings.scheduler_timezone
        )
        self._configured = False
        self._started = False
        self._tick_in_progress = False
        self._last_run_at: datetime | None = None
        self._last_success_at: datetime | None = None
        self._last_failure_at: datetime | None = None
        self._last_error: str | None = None
        self._last_result: dict[str, Any] | None = None
        self._last_duration_ms: int | None = None
        self._run_count = 0
        self._success_count = 0
        self._failure_count = 0
        self._overlap_skip_count = 0

    def notice_enabled(self) -> bool:
        return bool(
            getattr(get_settings(), "upbit_notice_collection_enabled", False)
        )

    def crypto_enabled(self) -> bool:
        return bool(
            getattr(get_settings(), "crypto_news_collection_enabled", False)
        )

    def configure(self, *, force: bool = False) -> None:
        if self._configured and not force:
            return
        settings = get_settings()

        try:
            self._scheduler.remove_job(self.NOTICE_JOB_ID)
        except Exception:  # noqa: BLE001
            pass
        try:
            self._scheduler.remove_job(self.CRYPTO_JOB_ID)
        except Exception:  # noqa: BLE001
            pass

        if self.notice_enabled():
            interval = max(
                60,
                int(
                    getattr(
                        settings,
                        "upbit_notice_collection_interval_seconds",
                        300,
                    )
                ),
            )

            async def _notice_tick() -> None:
                await self._run_tick(sources=("notice",))

            self._scheduler.add_job(
                _notice_tick,
                IntervalTrigger(seconds=interval),
                id=self.NOTICE_JOB_ID,
                replace_existing=True,
                max_instances=1,
                coalesce=True,
                misfire_grace_time=max(interval, 60),
            )

        if self.crypto_enabled():
            interval = max(
                60,
                int(
                    getattr(
                        settings,
                        "crypto_news_collection_interval_seconds",
                        900,
                    )
                ),
            )

            async def _crypto_tick() -> None:
                await self._run_tick(sources=("crypto",))

            self._scheduler.add_job(
                _crypto_tick,
                IntervalTrigger(seconds=interval),
                id=self.CRYPTO_JOB_ID,
                replace_existing=True,
                max_instances=1,
                coalesce=True,
                misfire_grace_time=max(interval, 60),
            )

        self._configured = True

    def start(self) -> None:
        """enabled=false 이면 Job 미등록 — 자동 ON 금지."""

        if not self.notice_enabled() and not self.crypto_enabled():
            logger.info(
                "upbit_news_notice_collector_skipped",
                reason="ALL_COLLECTION_DISABLED",
            )
            self._configured = True
            return

        self.configure(force=True)
        if not self._scheduler.running:
            self._scheduler.start()
            self._started = True
            logger.info(
                "upbit_news_notice_collector_started",
                notice_enabled=self.notice_enabled(),
                crypto_enabled=self.crypto_enabled(),
            )

    async def shutdown(self) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)
        self._started = False

    def status(self) -> dict[str, Any]:
        settings = get_settings()
        provider = resolve_crypto_news_provider(settings)
        next_notice = None
        next_crypto = None
        try:
            job = self._scheduler.get_job(self.NOTICE_JOB_ID)
            if job and job.next_run_time is not None:
                next_notice = job.next_run_time.isoformat()
        except Exception:  # noqa: BLE001
            pass
        try:
            job = self._scheduler.get_job(self.CRYPTO_JOB_ID)
            if job and job.next_run_time is not None:
                next_crypto = job.next_run_time.isoformat()
        except Exception:  # noqa: BLE001
            pass

        last = self._last_result or {}
        # LAST_CHECK / LAST_SUCCESS / LAST_NEW_ITEM 분리
        # — 새 기사 없어도 check/success면 STALE/BROKEN 오판 금지
        last_new_item_at = self._extract_last_new_item_at(last)
        freshness = {
            "last_check_at": (
                self._last_run_at.isoformat() if self._last_run_at else None
            ),
            "last_success_at": (
                self._last_success_at.isoformat()
                if self._last_success_at
                else None
            ),
            "last_new_item_at": last_new_item_at,
            "had_new_items": bool(last.get("had_new_items")),
            "semantics": (
                "LAST_CHECK=tick 시도, LAST_SUCCESS=실패 없는 tick, "
                "LAST_NEW_ITEM=실제 insert된 최신 기사. "
                "duplicates-only success ≠ STALE/BROKEN"
            ),
        }
        return {
            "enabled": self.notice_enabled() or self.crypto_enabled(),
            "running": bool(self._started and self._scheduler.running),
            "tick_in_progress": self._tick_in_progress,
            "sources": {
                "UPBIT_NOTICE": {
                    "enabled": self.notice_enabled(),
                    "interval_seconds": int(
                        getattr(
                            settings,
                            "upbit_notice_collection_interval_seconds",
                            300,
                        )
                    ),
                    "next_run": next_notice,
                    "api_base_url": getattr(
                        settings,
                        "upbit_notice_api_base_url",
                        "",
                    ),
                },
                "CRYPTO_NEWS": {
                    "enabled": self.crypto_enabled(),
                    "interval_seconds": int(
                        getattr(
                            settings,
                            "crypto_news_collection_interval_seconds",
                            900,
                        )
                    ),
                    "next_run": next_crypto,
                    "provider": provider.provider,
                    "provider_available": provider.available,
                    "provider_reason": provider.reason,
                },
            },
            "last_run": (
                self._last_run_at.isoformat() if self._last_run_at else None
            ),
            "last_success": (
                self._last_success_at.isoformat()
                if self._last_success_at
                else None
            ),
            "last_check_at": freshness["last_check_at"],
            "last_success_at": freshness["last_success_at"],
            "last_new_item_at": freshness["last_new_item_at"],
            "freshness": freshness,
            "next_run": next_notice or next_crypto,
            "fetched_count": int(last.get("fetched_count") or 0),
            "inserted_count": int(last.get("inserted_count") or 0),
            "duplicate_count": int(last.get("duplicate_count") or 0),
            "updated_count": int(last.get("updated_count") or 0),
            "failure_count": self._failure_count,
            "last_error": self._last_error,
            "last_duration_ms": self._last_duration_ms,
            "run_count": self._run_count,
            "success_count": self._success_count,
            "overlap_skip_count": self._overlap_skip_count,
            "last_result": self._last_result,
            "isolation": {
                "scanner": "unaffected",
                "shadow": "unaffected",
                "ai_scheduler": "unaffected",
                "market_feed": "unaffected",
            },
        }

    @staticmethod
    def _extract_last_new_item_at(last: dict[str, Any]) -> str | None:
        """source별 last_new_article_at 중 최신값 (없으면 None)."""

        sources = last.get("sources") if isinstance(last, dict) else None
        if not isinstance(sources, dict):
            return None
        best: str | None = None
        for payload in sources.values():
            if not isinstance(payload, dict):
                continue
            if not payload.get("had_new_items"):
                continue
            ts = payload.get("last_new_article_at") or payload.get(
                "published_at_after"
            )
            if isinstance(ts, str) and ts:
                if best is None or ts > best:
                    best = ts
        return best

    async def run_once_now(
        self,
        *,
        include_notice: bool = True,
        include_crypto: bool = True,
    ) -> dict[str, Any]:
        sources: list[str] = []
        if include_notice:
            sources.append("notice")
        if include_crypto:
            sources.append("crypto")
        return await self._run_tick(sources=tuple(sources), force=True)

    async def _run_tick(
        self,
        *,
        sources: tuple[str, ...],
        force: bool = False,
    ) -> dict[str, Any]:
        if self._tick_in_progress:
            self._overlap_skip_count += 1
            return {
                "skipped": True,
                "reason": "TICK_IN_PROGRESS",
            }

        self._tick_in_progress = True
        started = time.perf_counter()
        self._last_run_at = datetime.now(timezone.utc)
        self._run_count += 1
        aggregate: dict[str, Any] = {
            "fetched_count": 0,
            "normalized_count": 0,
            "inserted_count": 0,
            "duplicate_count": 0,
            "updated_count": 0,
            "parse_failure_count": 0,
            "failure_count": 0,
            "sources": {},
            "samples": [],
        }

        session_factory = get_session_factory()
        try:
            if "notice" in sources:
                session = session_factory()
                try:
                    collector = UpbitNoticeCollector(session)
                    notice_result = await collector.collect()
                    aggregate["sources"][SOURCE_CODE_UPBIT_NOTICE] = asdict(
                        notice_result
                    )
                    self._merge_counts(aggregate, asdict(notice_result))
                    aggregate["samples"].extend(notice_result.samples[:5])
                finally:
                    session.close()

            if "crypto" in sources:
                session = session_factory()
                try:
                    collector = CryptoNewsCollector(session)
                    crypto_result = await collector.collect()
                    aggregate["sources"][SOURCE_CODE_CRYPTO_NEWS] = asdict(
                        crypto_result
                    )
                    self._merge_counts(aggregate, asdict(crypto_result))
                    # provider unavailable 는 failure 로 치지 않음
                    if crypto_result.last_error == "NEWS_PROVIDER_NOT_AVAILABLE":
                        aggregate["crypto_provider"] = (
                            "NEWS_PROVIDER_NOT_AVAILABLE"
                        )
                    else:
                        aggregate["samples"].extend(crypto_result.samples[:3])
                finally:
                    session.close()

            # N8: collect 후 N3/N3.1 mapping — 별도 architecture 없이
            # 기존 collector tick에 fail-isolated glue (Scanner 무영향)
            if int(aggregate.get("inserted_count") or 0) > 0 or force:
                map_session = session_factory()
                try:
                    aggregate["symbol_mapping"] = self._run_post_collect_mapping(
                        map_session,
                        sources=sources,
                    )
                except Exception as map_exc:  # noqa: BLE001
                    # mapping 실패가 collect 성공을 뒤집지 않음
                    aggregate["symbol_mapping"] = {
                        "ok": False,
                        "error": f"{type(map_exc).__name__}: {map_exc}"[:300],
                    }
                    logger.warning(
                        "upbit_news_post_collect_mapping_failed",
                        error=aggregate["symbol_mapping"]["error"],
                    )
                finally:
                    map_session.close()

            # source별 had_new_items 집계 (새 기사 없어도 success 가능)
            had_any_new = False
            for payload in aggregate["sources"].values():
                if isinstance(payload, dict) and payload.get("had_new_items"):
                    had_any_new = True
                    break
            aggregate["had_new_items"] = had_any_new

            if aggregate["failure_count"] > 0:
                self._failure_count += 1
                self._last_failure_at = datetime.now(timezone.utc)
                # source별 last_error 수집
                errors = []
                for payload in aggregate["sources"].values():
                    if isinstance(payload, dict) and payload.get("last_error"):
                        errors.append(str(payload["last_error"]))
                self._last_error = "; ".join(errors)[:500] or "collect_failed"
            else:
                self._success_count += 1
                self._last_success_at = datetime.now(timezone.utc)
                self._last_error = None

            # collect 성공 후 critical notice → shadow/telegram (fail-isolated)
            try:
                from stock_platform.news.intelligence.pipeline_hooks import (
                    after_upbit_collect_tick,
                )

                aggregate["intelligence"] = after_upbit_collect_tick(
                    aggregate
                )
            except Exception as hook_exc:  # noqa: BLE001
                aggregate["intelligence"] = {
                    "ok": False,
                    "error": f"{type(hook_exc).__name__}: {hook_exc}"[:300],
                }
                logger.warning(
                    "upbit_news_intelligence_hook_failed",
                    error=aggregate["intelligence"]["error"],
                )

            self._last_result = aggregate
            return aggregate
        except Exception as exc:  # noqa: BLE001 — never break other schedulers
            self._failure_count += 1
            self._last_failure_at = datetime.now(timezone.utc)
            self._last_error = f"{type(exc).__name__}: {exc}"[:500]
            logger.warning(
                "upbit_news_notice_collector_tick_failed",
                error=self._last_error,
            )
            aggregate["failure_count"] += 1
            aggregate["last_error"] = self._last_error
            self._last_result = aggregate
            return aggregate
        finally:
            self._last_duration_ms = int(
                (time.perf_counter() - started) * 1000
            )
            self._tick_in_progress = False

    @staticmethod
    def _merge_counts(aggregate: dict[str, Any], payload: dict[str, Any]) -> None:
        for key in (
            "fetched_count",
            "normalized_count",
            "inserted_count",
            "duplicate_count",
            "updated_count",
            "parse_failure_count",
            "failure_count",
        ):
            aggregate[key] = int(aggregate.get(key) or 0) + int(
                payload.get(key) or 0
            )

    @staticmethod
    def _run_post_collect_mapping(
        session: Any,
        *,
        sources: tuple[str, ...],
    ) -> dict[str, Any]:
        """최근 article에 대해 N3/N3.1 mapping (TRUSTED quality 포함)."""

        from dataclasses import asdict

        from stock_platform.news.collector_constants import (
            SOURCE_CODE_CRYPTO_NEWS,
            SOURCE_CODE_UPBIT_NOTICE,
        )
        from stock_platform.news.symbol_mapper import NewsSymbolMapper

        codes: list[str] = []
        if "notice" in sources:
            codes.append(SOURCE_CODE_UPBIT_NOTICE)
        if "crypto" in sources:
            codes.append(SOURCE_CODE_CRYPTO_NEWS)
        if not codes:
            return {"ok": True, "skipped": True, "reason": "NO_SOURCE"}

        mapper = NewsSymbolMapper(session)
        # 신규 위주 — 전체 재분석 금지, 최근 50건만
        stats = mapper.run_backfill(source_codes=codes, limit=50)
        session.commit()
        return {"ok": True, "stats": asdict(stats)}


upbit_news_notice_collector_scheduler = UpbitNewsNoticeCollectorScheduler()
