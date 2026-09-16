"""장후 포트폴리오 스냅샷 Job — STEP66."""

from __future__ import annotations

from datetime import date
from typing import Any

from sqlalchemy.orm import Session

from stock_platform.trading.portfolio_snapshot_service import (
    PortfolioSnapshotService,
)


class PortfolioEquitySnapshotJob:
    """활성 Paper 계좌 일별 자산 스냅샷 (PAPER/LIVE 모드 태그)."""

    def __init__(self, session: Session) -> None:
        self._service = PortfolioSnapshotService(session)

    def execute(self, payload: dict[str, Any]) -> dict[str, Any]:
        raw_date = payload.get("snapshot_date") or date.today().isoformat()
        mode = str(payload.get("mode_code") or "PAPER").upper()
        # LIVE도 동일 평가 파이프라인 — 모드 태그만 구분
        if mode not in {"PAPER", "LIVE"}:
            mode = "PAPER"
        paper_result = self._service.capture_all_active(
            snapshot_date=date.fromisoformat(str(raw_date)),
            mode_code="PAPER",
        )
        live_result = None
        if payload.get("include_live", True):
            live_result = self._service.capture_all_active(
                snapshot_date=date.fromisoformat(str(raw_date)),
                mode_code="LIVE",
            )
        return {
            "job": "portfolio_equity_snapshot",
            "paper": paper_result,
            "live": live_result,
            "note": (
                "LIVE는 동일 Paper 평가 로직에 mode_code=LIVE 태그를 남깁니다. "
                "브로커 NAV 전용 스냅샷은 후속 STEP에서 확장합니다."
            ),
        }
