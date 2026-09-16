"""STEP 8-5-16 — Settlement Job Runner (다계좌 집계)."""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.settlement.constants import (
    SettlementStatus,
    SettlementType,
)
from stock_platform.settlement.service import AccountDailySettlementService
from stock_platform.trading.account_models import (
    PaperAccount,
    UserBrokerAccount,
)

logger = logging.getLogger(__name__)


def run_krx_eod_settlement(
    session: Session,
    *,
    market_date: date,
    calendar_revision: int | None = None,
    actor: str = "KRX_SETTLEMENT_JOB",
) -> dict[str, Any]:
    """KRX EOD: Kiwoom LIVE UBA + Stock Paper 계좌 정산."""

    svc = AccountDailySettlementService(session)
    results: list[dict[str, Any]] = []

    # Stock Paper
    papers = list(session.scalars(select(PaperAccount)))
    for paper in papers:
        if getattr(paper, "deleted_at", None) is not None:
            continue
        # CRYPTO paper는 KRX EOD에서 제외 (currency/exchange 휴리스틱)
        name = str(getattr(paper, "account_name", "") or "").upper()
        if "CRYPTO" in name or "UPBIT" in name:
            continue
        try:
            row = svc.settle_paper_account(
                paper_account_id=int(paper.account_id),
                market_date=market_date,
                settlement_type=SettlementType.PAPER_STOCK_EOD.value,
                calendar_revision=calendar_revision,
                actor=actor,
            )
            session.commit()
            results.append(
                {
                    "paper_account_id": int(paper.account_id),
                    "status": row.status_code,
                    "settlement_id": int(row.settlement_id),
                }
            )
        except Exception as exc:  # noqa: BLE001
            session.rollback()
            logger.exception("krx_settlement_paper_failed")
            results.append(
                {
                    "paper_account_id": int(paper.account_id),
                    "status": SettlementStatus.FAILED.value,
                    "error": str(exc)[:200],
                }
            )

    # Kiwoom LIVE UBA
    # STEP 2-5-1 — 삭제(soft-deleted)/비활성 계좌는 정산 배치 대상에서 제외
    ubas = list(
        session.scalars(
            select(UserBrokerAccount).where(
                UserBrokerAccount.broker_code == "KIWOOM",
                UserBrokerAccount.is_active.is_(True),
            )
        )
    )
    for uba in ubas:
        try:
            row = svc.settle_uba(
                user_broker_account_id=int(uba.user_broker_account_id),
                broker_code="KIWOOM",
                market_date=market_date,
                settlement_type=SettlementType.KRX_EOD.value,
                calendar_revision=calendar_revision,
                actor=actor,
            )
            session.commit()
            results.append(
                {
                    "user_broker_account_id": int(
                        uba.user_broker_account_id
                    ),
                    "status": row.status_code,
                    "settlement_id": int(row.settlement_id),
                }
            )
        except Exception as exc:  # noqa: BLE001
            session.rollback()
            logger.exception("krx_settlement_uba_failed")
            results.append(
                {
                    "user_broker_account_id": int(
                        uba.user_broker_account_id
                    ),
                    "status": SettlementStatus.FAILED.value,
                    "error": str(exc)[:200],
                }
            )

    return _aggregate(results)


def run_upbit_daily_settlement(
    session: Session,
    *,
    market_date: date,
    actor: str = "UPBIT_DAILY_SETTLEMENT",
) -> dict[str, Any]:
    """Upbit LIVE + Crypto Paper — KRX Calendar와 분리."""

    svc = AccountDailySettlementService(session)
    results: list[dict[str, Any]] = []

    papers = list(session.scalars(select(PaperAccount)))
    for paper in papers:
        if getattr(paper, "deleted_at", None) is not None:
            continue
        name = str(getattr(paper, "account_name", "") or "").upper()
        if "CRYPTO" not in name and "UPBIT" not in name:
            # 기본 Paper는 Stock — Upbit Daily에서 제외
            # currency KRW only stock papers skipped
            continue
        try:
            row = svc.settle_paper_account(
                paper_account_id=int(paper.account_id),
                market_date=market_date,
                settlement_type=SettlementType.PAPER_CRYPTO_DAILY.value,
                actor=actor,
            )
            session.commit()
            results.append(
                {
                    "paper_account_id": int(paper.account_id),
                    "status": row.status_code,
                    "settlement_id": int(row.settlement_id),
                }
            )
        except Exception as exc:  # noqa: BLE001
            session.rollback()
            results.append(
                {
                    "paper_account_id": int(paper.account_id),
                    "status": SettlementStatus.FAILED.value,
                    "error": str(exc)[:200],
                }
            )

    # STEP 2-5-1 — 삭제(soft-deleted)/비활성 계좌는 정산 배치 대상에서 제외
    ubas = list(
        session.scalars(
            select(UserBrokerAccount).where(
                UserBrokerAccount.broker_code == "UPBIT",
                UserBrokerAccount.is_active.is_(True),
            )
        )
    )
    for uba in ubas:
        try:
            row = svc.settle_uba(
                user_broker_account_id=int(uba.user_broker_account_id),
                broker_code="UPBIT",
                market_date=market_date,
                settlement_type=SettlementType.UPBIT_DAILY.value,
                actor=actor,
            )
            session.commit()
            results.append(
                {
                    "user_broker_account_id": int(
                        uba.user_broker_account_id
                    ),
                    "status": row.status_code,
                    "settlement_id": int(row.settlement_id),
                }
            )
        except Exception as exc:  # noqa: BLE001
            session.rollback()
            results.append(
                {
                    "user_broker_account_id": int(
                        uba.user_broker_account_id
                    ),
                    "status": SettlementStatus.FAILED.value,
                    "error": str(exc)[:200],
                }
            )

    return _aggregate(results)


def _aggregate(results: list[dict[str, Any]]) -> dict[str, Any]:
    counts = {
        "total": len(results),
        "succeeded": 0,
        "warnings": 0,
        "manual_review": 0,
        "retry": 0,
        "failed": 0,
        "skipped": 0,
    }
    for r in results:
        st = str(r.get("status") or "")
        if st == SettlementStatus.SUCCEEDED.value:
            counts["succeeded"] += 1
        elif st == SettlementStatus.SUCCEEDED_WITH_WARNINGS.value:
            counts["warnings"] += 1
        elif st == SettlementStatus.MANUAL_REVIEW_REQUIRED.value:
            counts["manual_review"] += 1
        elif st == SettlementStatus.RETRY_PENDING.value:
            counts["retry"] += 1
        elif st == SettlementStatus.SKIPPED.value:
            counts["skipped"] += 1
        else:
            counts["failed"] += 1
    return {"counts": counts, "results": results}
