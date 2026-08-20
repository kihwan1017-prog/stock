"""STEP 8-8 — 체결 후 Broker/DB 잔고 검증 실행기 (STEP 8-8A 재검증 연계)."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.order.post_fill_verifier import (
    PostFillBalanceVerifier,
    PostFillVerifyResult,
)


class PostFillVerifyRunner:
    """LIVE 체결 후 Snapshot vs 주문 누적 체결을 비교한다."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._verifier = PostFillBalanceVerifier(session)

    def verify_uba_against_expected(
        self,
        *,
        user_broker_account_id: int,
        user_id: int | None,
        broker_code: str,
        expected_positions: list[dict[str, Any]],
        expected_cash: Decimal | None,
        broker_positions: list[dict[str, Any]] | None = None,
        broker_cash: Decimal | None = None,
        actor: str = "POST_FILL_VERIFY",
        activate_kill_on_mismatch: bool = True,
        allow_live_off_for_submitted: bool = False,
    ) -> PostFillVerifyResult:
        """Broker 잔고(또는 주입값)와 기대 DB 포지션을 비교한다."""

        from stock_platform.broker.account_repository import (
            BrokerAccountSnapshotRepository,
        )
        from stock_platform.trading.account_models import UserBrokerAccount

        uba = self._session.get(
            UserBrokerAccount, int(user_broker_account_id)
        )
        if uba is None:
            return PostFillVerifyResult(
                ok=True,
                reason_code="UBA_NOT_FOUND_SKIP",
                detail={"user_broker_account_id": user_broker_account_id},
            )
        # LIVE OFF = 신규 주문 금지. 이미 broker UUID가 있는 주문의
        # READ/reconciliation/post-fill 검증은 허용한다.
        if not bool(getattr(uba, "live_order_enabled", False)):
            if not allow_live_off_for_submitted:
                return PostFillVerifyResult(
                    ok=True,
                    reason_code="LIVE_OFF_SKIP",
                    detail={"user_broker_account_id": user_broker_account_id},
                )

        resolved_broker_positions = broker_positions
        resolved_broker_cash = broker_cash
        if resolved_broker_positions is None or (
            expected_cash is not None and resolved_broker_cash is None
        ):
            account, positions = BrokerAccountSnapshotRepository(
                self._session
            ).get_active_by_uba(int(user_broker_account_id))
            if account is None and resolved_broker_positions is None:
                # STEP 8-8A — 최종 성공 아님 (재검증 대기)
                return PostFillVerifyResult(
                    ok=False,
                    reason_code="SNAPSHOT_MISSING",
                    detail={
                        "user_broker_account_id": user_broker_account_id,
                        "note": "broker snapshot unavailable",
                    },
                )
            if resolved_broker_positions is None and account is not None:
                resolved_broker_positions = [
                    {
                        "symbol": str(p.symbol),
                        "quantity": str(p.quantity),
                    }
                    for p in positions
                ]
            if resolved_broker_cash is None and account is not None:
                resolved_broker_cash = Decimal(
                    str(
                        getattr(account, "available_cash", None)
                        or getattr(account, "available_order_amount", 0)
                        or 0
                    )
                )

        return self._verifier.verify(
            user_broker_account_id=int(user_broker_account_id),
            user_id=user_id,
            broker_code=broker_code,
            broker_positions=resolved_broker_positions,
            broker_cash=resolved_broker_cash,
            db_positions=expected_positions,
            db_cash=expected_cash,
            actor=actor,
            activate_kill_on_mismatch=activate_kill_on_mismatch,
        )

    def build_expected_positions_from_orders(
        self,
        *,
        user_broker_account_id: int,
        symbol: str | None = None,
    ) -> list[dict[str, Any]]:
        """FILLED/PARTIALLY_FILLED 주문 순매수량을 기대 Position으로 집계."""

        from stock_platform.order.entities import TradingOrderEntity

        stmt = select(TradingOrderEntity).where(
            TradingOrderEntity.user_broker_account_id
            == int(user_broker_account_id),
            TradingOrderEntity.status_code.in_(
                ("FILLED", "PARTIALLY_FILLED")
            ),
        )
        if symbol:
            stmt = stmt.where(
                TradingOrderEntity.symbol == str(symbol).upper()
            )
        rows = list(self._session.scalars(stmt))
        nets: dict[str, Decimal] = {}
        for row in rows:
            sym = str(row.symbol).upper()
            filled = Decimal(str(row.filled_quantity or 0))
            side = str(row.side_code or "").upper()
            delta = filled if side == "BUY" else -filled
            nets[sym] = nets.get(sym, Decimal("0")) + delta
        return [
            {"symbol": sym, "quantity": str(qty)}
            for sym, qty in nets.items()
            if qty != 0
        ]

    def verify_after_order_fill(
        self,
        *,
        order: Any,
        execution_id: int | None = None,
        actor: str = "EXECUTION_SYNC",
    ) -> PostFillVerifyResult:
        """주문 체결 직후 — enqueue + 즉시 비교.

        Snapshot stale/missing은 최종 성공이 아니라 WAITING_SNAPSHOT으로
        재검증 스케줄에 등록한다 (STEP 8-8A).
        """

        uba_id = getattr(order, "user_broker_account_id", None)
        if uba_id is None:
            return PostFillVerifyResult(
                ok=True,
                reason_code="NO_UBA_SKIP",
                detail={},
            )

        from stock_platform.order.post_fill_verification_service import (
            PostFillVerificationService,
        )

        symbol = str(getattr(order, "symbol", "") or "").upper()
        expected = self.build_expected_positions_from_orders(
            user_broker_account_id=int(uba_id),
            symbol=symbol or None,
        )
        svc = PostFillVerificationService(self._session)
        row = svc.enqueue_from_order(
            order=order,
            execution_id=execution_id,
            expected_positions=expected,
            actor=actor,
        )

        from stock_platform.broker.account_repository import (
            BrokerAccountSnapshotRepository,
        )

        account, positions = BrokerAccountSnapshotRepository(
            self._session
        ).get_active_by_uba(int(uba_id))
        if account is None:
            result = PostFillVerifyResult(
                ok=False,
                reason_code="SNAPSHOT_MISSING",
                detail={"user_broker_account_id": int(uba_id)},
            )
            if row is not None:
                svc.handle_immediate_result(
                    row=row,
                    reason_code=result.reason_code,
                    detail=result.detail,
                    actor=actor,
                )
            return result

        broker_positions = [
            {"symbol": str(p.symbol), "quantity": str(p.quantity)}
            for p in positions
        ]
        if symbol:
            broker_positions = [
                p
                for p in broker_positions
                if str(p["symbol"]).upper() == symbol
            ]
            if not broker_positions and expected:
                # STEP 8-8A — 성공으로 처리하지 않음
                result = PostFillVerifyResult(
                    ok=False,
                    reason_code="SNAPSHOT_STALE",
                    detail={
                        "symbol": symbol,
                        "expected": expected,
                        "note": "broker snapshot not yet reflecting fill",
                    },
                )
                if row is not None:
                    svc.handle_immediate_result(
                        row=row,
                        reason_code=result.reason_code,
                        detail=result.detail,
                        actor=actor,
                    )
                return result

        # 즉시 경로: Kill 없이 비교. 불일치는 sync-pending + 재시도.
        # (fill 직후 broker snapshot eventual consistency window)
        result = self.verify_uba_against_expected(
            user_broker_account_id=int(uba_id),
            user_id=getattr(order, "user_id", None),
            broker_code=str(getattr(order, "broker_code", "") or "UNKNOWN"),
            expected_positions=expected,
            expected_cash=None,
            broker_positions=broker_positions,
            broker_cash=None,
            actor=actor,
            activate_kill_on_mismatch=False,
            allow_live_off_for_submitted=bool(
                str(getattr(order, "broker_order_id", "") or "").strip()
            ),
        )
        reason = result.reason_code
        detail = dict(result.detail or {})
        if reason == "POSITION_MISMATCH":
            reason = "POSITION_SYNC_PENDING"
            detail["deferred_kill"] = True
            detail["pending_reason"] = "POSITION_MISMATCH"
        elif reason == "CASH_MISMATCH":
            reason = "CASH_SYNC_PENDING"
            detail["deferred_kill"] = True
            detail["pending_reason"] = "CASH_MISMATCH"
        if row is not None:
            svc.handle_immediate_result(
                row=row,
                reason_code=reason,
                detail=detail,
                actor=actor,
                request_sync=True,
            )
        return PostFillVerifyResult(
            ok=result.ok,
            reason_code=reason,
            detail=detail,
        )
