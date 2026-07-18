from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import structlog
from sqlalchemy.orm import Session

from stock_platform.broker.kiwoom.account_sync_service import (
    KiwoomAccountSyncService,
)
from stock_platform.broker.kiwoom.pending_service import (
    KiwoomPendingOrderService,
)

logger = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class AccountStateSyncResult:
    account: dict[str, Any]
    pending_orders: dict[str, Any]
    fields: dict[str, str]


class KiwoomAccountStateSyncService:
    """
    계좌 스냅샷(예수금·주문가능·보유·평가손익)과
    미체결을 한 번에 동기화한다.
    """

    FIELD_MAP = {
        "deposit_amount": "예수금",
        "available_order_amount": "주문가능금액",
        "quantity": "보유수량",
        "average_purchase_price": "평균단가",
        "profit_loss": "평가손익(종목)",
        "total_profit_loss": "평가손익(계좌합계)",
        "realized_profit_loss": "실현손익(미제공시 null)",
        "pending_orders": "미체결",
    }

    def __init__(
        self,
        *,
        session: Session,
        account_sync_service: KiwoomAccountSyncService,
        pending_order_service: KiwoomPendingOrderService,
    ) -> None:
        self._account_sync = account_sync_service
        self._pending_sync = pending_order_service

    async def synchronize(self) -> AccountStateSyncResult:
        account = await self._account_sync.synchronize()
        account_number = str(account["account_number"])

        # 미체결 실패해도 예수금/잔고 스냅샷은 유지 (Day-1/부분실패 허용)
        try:
            pending = await self._pending_sync.synchronize(
                account_number
            )
        except Exception as exc:
            logger.warning(
                "kiwoom_pending_sync_failed",
                account_number=account_number,
                error=str(exc),
            )
            pending = {
                "account_number": account_number,
                "count": 0,
                "items": [],
                "error": str(exc),
                "partial": True,
            }

        # 키움 잔고 응답의 total_profit_loss는 평가손익 성격
        account = {
            **account,
            "evaluation_profit_loss": account.get(
                "total_profit_loss"
            ),
            "realized_profit_loss": None,
            "realized_profit_loss_supported": False,
        }
        return AccountStateSyncResult(
            account=account,
            pending_orders=pending,
            fields=dict(self.FIELD_MAP),
        )
