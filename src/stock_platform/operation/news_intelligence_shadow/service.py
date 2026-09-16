"""News Intelligence Shadow service — provenance only, REAL gate 비연동."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from stock_platform.common.logger import logger
from stock_platform.common.settings import get_settings
from stock_platform.operation.news_intelligence_shadow.entities import (
    NewsIntelligenceShadowDecisionEntity,
)
from stock_platform.operation.news_intelligence_shadow.policy import (
    DECISION_ALERT,
    DECISION_OBSERVE,
    MARKET_KIWOOM,
    MARKET_UPBIT,
    PIPELINE_VERSION,
    SHADOW_POLICY_VERSION,
    SOURCE_DART,
    SOURCE_UPBIT_NOTICE,
    UPBIT_CRITICAL_NOTICE_CATEGORIES,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


class NewsIntelligenceShadowService:
    def __init__(self, session: Session) -> None:
        self._session = session

    def enabled(self) -> bool:
        return bool(
            getattr(get_settings(), "news_intelligence_shadow_enabled", True)
        )

    def upsert_decision(
        self,
        *,
        market_code: str,
        source_kind: str,
        event_key: str,
        decision: str,
        category: str | None = None,
        symbol: str | None = None,
        title: str | None = None,
        severity: str = "INFO",
        provenance: dict[str, Any] | None = None,
        effective_start_at: datetime | None = None,
    ) -> tuple[NewsIntelligenceShadowDecisionEntity, bool]:
        """returns (row, created)."""

        existing = self._session.scalar(
            select(NewsIntelligenceShadowDecisionEntity).where(
                NewsIntelligenceShadowDecisionEntity.market_code
                == market_code.upper(),
                NewsIntelligenceShadowDecisionEntity.event_key == event_key,
            )
        )
        if existing is not None:
            return existing, False

        row = NewsIntelligenceShadowDecisionEntity(
            pipeline_version=PIPELINE_VERSION,
            market_code=market_code.upper(),
            source_kind=source_kind,
            symbol=(symbol.upper() if symbol else None),
            event_key=event_key,
            decision=decision,
            category=category,
            title=(title[:500] if title else None),
            severity=severity,
            provenance={
                "shadow_policy_version": SHADOW_POLICY_VERSION,
                "real_gate_coupled": False,
                **(provenance or {}),
            },
            effective_start_at=effective_start_at or _now(),
        )
        self._session.add(row)
        self._session.flush()
        return row, True

    def mark_notified(self, row: NewsIntelligenceShadowDecisionEntity) -> None:
        row.notified_at = _now()
        self._session.flush()

    def status_snapshot(self) -> dict[str, Any]:
        enabled = self.enabled()
        upbit_n = int(
            self._session.scalar(
                select(func.count())
                .select_from(NewsIntelligenceShadowDecisionEntity)
                .where(
                    NewsIntelligenceShadowDecisionEntity.market_code
                    == MARKET_UPBIT
                )
            )
            or 0
        )
        kiwoom_n = int(
            self._session.scalar(
                select(func.count())
                .select_from(NewsIntelligenceShadowDecisionEntity)
                .where(
                    NewsIntelligenceShadowDecisionEntity.market_code
                    == MARKET_KIWOOM
                )
            )
            or 0
        )
        first_upbit = self._session.scalar(
            select(NewsIntelligenceShadowDecisionEntity.effective_start_at)
            .where(
                NewsIntelligenceShadowDecisionEntity.market_code == MARKET_UPBIT
            )
            .order_by(
                NewsIntelligenceShadowDecisionEntity.effective_start_at.asc()
            )
            .limit(1)
        )
        first_kiwoom = self._session.scalar(
            select(NewsIntelligenceShadowDecisionEntity.effective_start_at)
            .where(
                NewsIntelligenceShadowDecisionEntity.market_code
                == MARKET_KIWOOM
            )
            .order_by(
                NewsIntelligenceShadowDecisionEntity.effective_start_at.asc()
            )
            .limit(1)
        )
        return {
            "enabled": enabled,
            "pipeline_version": PIPELINE_VERSION,
            "shadow_policy_version": SHADOW_POLICY_VERSION,
            "real_gate_coupled": False,
            "upbit": {
                "active": enabled,
                "n": upbit_n,
                "effective_start_at": (
                    first_upbit.isoformat() if first_upbit else None
                ),
            },
            "kiwoom": {
                "active": enabled,
                "n": kiwoom_n,
                "effective_start_at": (
                    first_kiwoom.isoformat() if first_kiwoom else None
                ),
            },
        }

    def ingest_upbit_notices(
        self,
        articles: list[dict[str, Any]],
    ) -> dict[str, Any]:
        created = 0
        alerted = 0
        for item in articles:
            category = str(item.get("category") or "").upper()
            external_id = str(item.get("external_id") or item.get("article_id") or "")
            if not external_id:
                continue
            event_key = f"UPBIT_NOTICE:{external_id}"
            decision = (
                DECISION_ALERT
                if category in UPBIT_CRITICAL_NOTICE_CATEGORIES
                else DECISION_OBSERVE
            )
            severity = (
                "CRITICAL"
                if category in UPBIT_CRITICAL_NOTICE_CATEGORIES
                else "INFO"
            )
            row, was_created = self.upsert_decision(
                market_code=MARKET_UPBIT,
                source_kind=SOURCE_UPBIT_NOTICE,
                event_key=event_key,
                decision=decision,
                category=category or None,
                symbol=None,
                title=str(item.get("title") or "")[:500] or None,
                severity=severity,
                provenance={
                    "article_id": item.get("article_id"),
                    "url": item.get("url"),
                    "published_at": item.get("published_at"),
                    "scanner_apply": False,
                    "real_buy_block": False,
                },
            )
            if was_created:
                created += 1
            if decision == DECISION_ALERT and was_created:
                alerted += 1
                try:
                    from stock_platform.news.intelligence.telegram_alerts import (
                        emit_upbit_important_notice,
                    )

                    if emit_upbit_important_notice(
                        self._session,
                        row=row,
                        detail=item,
                    ):
                        self.mark_notified(row)
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "upbit_important_notice_notify_failed",
                        error=str(exc)[:200],
                    )
        self._session.commit()
        return {"created": created, "alert_candidates": alerted}

    def ingest_kiwoom_major_disclosures(
        self,
        items: list[dict[str, Any]],
    ) -> dict[str, Any]:
        created = 0
        alerted = 0
        for item in items:
            receipt_no = str(item.get("receipt_no") or "").strip()
            symbol = str(item.get("symbol") or "").strip().upper()
            if not receipt_no:
                continue
            event_key = f"KIWOOM_DART:{symbol}:{receipt_no}"
            row, was_created = self.upsert_decision(
                market_code=MARKET_KIWOOM,
                source_kind=SOURCE_DART,
                event_key=event_key,
                decision=DECISION_ALERT,
                category="MAJOR",
                symbol=symbol or None,
                title=str(item.get("report_name") or "")[:500] or None,
                severity="CRITICAL",
                provenance={
                    "receipt_no": receipt_no,
                    "receipt_date": item.get("receipt_date"),
                    "importance_score": item.get("importance_score"),
                    "real_fresh_golden_cross_block": False,
                    "scanner_apply": False,
                },
            )
            if was_created:
                created += 1
                alerted += 1
                try:
                    from stock_platform.news.intelligence.telegram_alerts import (
                        emit_kiwoom_important_disclosure,
                    )

                    if emit_kiwoom_important_disclosure(
                        self._session,
                        row=row,
                        detail=item,
                    ):
                        self.mark_notified(row)
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "kiwoom_important_disclosure_notify_failed",
                        error=str(exc)[:200],
                    )
        self._session.commit()
        return {"created": created, "alert_candidates": alerted}
