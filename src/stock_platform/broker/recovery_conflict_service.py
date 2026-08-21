"""STEP 8-5-4 — Upbit Remote-only Conflict Service.

승인 Import는 외부 주문 API를 호출하지 않고 내부 DB 복구만 수행한다.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from stock_platform.broker.credential_adapter_factory import (
    build_upbit_settings_from_vault,
)
from stock_platform.broker.credential_vault_service import (
    BrokerCredentialVaultError,
    BrokerCredentialVaultService,
)
from stock_platform.broker.recovery_conflict_constants import (
    ACTIVE_REVIEW_STATUSES,
    ORDER_ORIGIN_RECOVERY_IMPORT,
    PAUSE_REASON_REMOTE_ONLY,
    REVIEW_COMPLETE_STATUSES,
    TERMINAL_REVIEW_STATUSES,
    RecoveryConflictResolution,
    RecoveryConflictReviewStatus,
    RecoveryConflictType,
)
from stock_platform.broker.recovery_conflict_entities import (
    BrokerRecoveryConflictEntity,
)
from stock_platform.broker.recovery_account_state import (
    BrokerRecoveryAccountStateEntity,
)
from stock_platform.broker.recovery_lock import RecoveryAccountLockService
from stock_platform.common.json_safe import to_jsonable
from stock_platform.operation.audit_repository import AuditEventRepository
from stock_platform.broker.upbit.order_client import UpbitOrderRestClient
from stock_platform.broker.upbit.order_reconcile_service import (
    mask_external_uuid,
    sanitize_upbit_order_snapshot,
)
from stock_platform.order.models import (
    CreateOrderCommand,
    OrderSide,
    OrderStatus,
    OrderTimeInForce,
    OrderType,
)
from stock_platform.order.id_generator import ClientOrderIdGenerator
from stock_platform.order.repository import TradingOrderRepository
from stock_platform.order.service import TradingOrderService
from stock_platform.trading.account_models import UserBrokerAccount
from stock_platform.trading.execution_entities import TradingExecution


class RecoveryConflictError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        detail: dict | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.detail = detail or {}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _dec(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    return Decimal(str(value))


def _parse_side(remote: dict[str, Any]) -> str:
    side = str(remote.get("side") or "").lower()
    if side in {"bid", "buy"}:
        return OrderSide.BUY.value
    if side in {"ask", "sell"}:
        return OrderSide.SELL.value
    return side.upper() or "BUY"


def _parse_order_type(remote: dict[str, Any]) -> OrderType:
    raw = str(remote.get("ord_type") or "limit").lower()
    if raw in {"market", "price", "best"}:
        return OrderType.MARKET
    return OrderType.LIMIT


def _map_remote_status(remote: dict[str, Any]) -> OrderStatus:
    from stock_platform.broker.upbit.order_status import (
        normalize_upbit_order_status,
    )

    mapped = normalize_upbit_order_status(remote)
    return mapped if mapped is not None else OrderStatus.ACCEPTED


class BrokerRecoveryConflictService:
    def __init__(self, session: Session) -> None:
        self._session = session

    def find_active(
        self,
        *,
        broker_code: str,
        external_order_id: str,
        user_broker_account_id: int | None,
    ) -> BrokerRecoveryConflictEntity | None:
        stmt = select(BrokerRecoveryConflictEntity).where(
            BrokerRecoveryConflictEntity.broker_code
            == broker_code.upper(),
            BrokerRecoveryConflictEntity.external_order_id
            == external_order_id,
            BrokerRecoveryConflictEntity.review_status.in_(
                list(ACTIVE_REVIEW_STATUSES)
            ),
        )
        if user_broker_account_id is None:
            stmt = stmt.where(
                BrokerRecoveryConflictEntity.user_broker_account_id.is_(
                    None
                )
            )
        else:
            stmt = stmt.where(
                BrokerRecoveryConflictEntity.user_broker_account_id
                == int(user_broker_account_id)
            )
        return self._session.scalar(stmt.limit(1))

    def upsert_remote_only(
        self,
        *,
        remote: dict[str, Any],
        user_id: int | None,
        user_broker_account_id: int | None,
        recovery_run_id: int | None,
        broker_code: str = "UPBIT",
    ) -> BrokerRecoveryConflictEntity | None:
        uuid = str(remote.get("uuid") or "").strip()
        if not uuid:
            return None

        # 이미 내부 주문 있으면 Conflict 미생성
        existing_order = TradingOrderRepository(
            self._session
        ).get_by_broker_order_id(
            broker_code=broker_code,
            broker_order_id=uuid,
            user_broker_account_id=user_broker_account_id,
        )
        if existing_order is not None:
            return None

        # 이미 승인·무시된 UUID는 재생성하지 않음 (스냅샷만 선택 갱신)
        terminal = self._session.scalar(
            select(BrokerRecoveryConflictEntity)
            .where(
                BrokerRecoveryConflictEntity.broker_code
                == broker_code.upper(),
                BrokerRecoveryConflictEntity.external_order_id == uuid,
                BrokerRecoveryConflictEntity.review_status.in_(
                    list(TERMINAL_REVIEW_STATUSES)
                ),
            )
            .order_by(
                BrokerRecoveryConflictEntity.updated_at.desc()
            )
            .limit(1)
        )
        if terminal is not None and user_broker_account_id == (
            terminal.user_broker_account_id
        ):
            terminal.last_remote_checked_at = _utcnow()
            terminal.remote_snapshot = sanitize_upbit_order_snapshot(
                remote
            )
            terminal.updated_at = _utcnow()
            self._session.flush()
            return None

        snapshot = sanitize_upbit_order_snapshot(remote)
        volume = _dec(remote.get("volume"))
        executed = _dec(remote.get("executed_volume")) or Decimal("0")
        remaining = _dec(remote.get("remaining_volume"))
        if remaining is None and volume is not None:
            remaining = volume - executed

        row = self.find_active(
            broker_code=broker_code,
            external_order_id=uuid,
            user_broker_account_id=user_broker_account_id,
        )
        now = _utcnow()
        created_new = False
        remote_state = str(remote.get("state") or "").strip().lower()
        # 종료(done/cancel) remote-only는 잔고 sync SoT로 이미 반영된다.
        # wait/watch가 아닌데 HIGH PENDING Conflict를 반복 생성하면
        # Recovery가 MANUAL_REVIEW에 고착된다 → 신규 생성만 억제.
        # 이미 ACTIVE인 Conflict는 스냅샷 갱신·운영자 해소 경로를 유지한다.
        if row is None and remote_state in {
            "done",
            "cancel",
            "cancelled",
            "canceled",
        }:
            return None
        if row is None:
            created_new = True
            row = BrokerRecoveryConflictEntity(
                broker_recovery_run_id=recovery_run_id,
                user_id=user_id,
                user_broker_account_id=user_broker_account_id,
                broker_code=broker_code.upper(),
                conflict_type=(
                    RecoveryConflictType.REMOTE_ORDER_NOT_FOUND_LOCALLY
                ),
                external_order_id=uuid,
                external_order_id_masked=mask_external_uuid(uuid),
                review_status=RecoveryConflictReviewStatus.PENDING_REVIEW,
                risk_level="HIGH",
                pause_reason=PAUSE_REASON_REMOTE_ONLY,
                detected_at=now,
            )
            self._session.add(row)

        row.market_code = str(remote.get("market") or "") or None
        row.side_code = _parse_side(remote)
        row.order_type_code = _parse_order_type(remote).value
        row.external_status = str(remote.get("state") or "") or None
        row.requested_quantity = volume
        row.executed_quantity = executed
        row.remaining_quantity = remaining
        row.order_price = _dec(remote.get("price"))
        row.average_execution_price = _dec(remote.get("avg_price"))
        row.paid_fee = _dec(remote.get("paid_fee"))
        created = remote.get("created_at")
        if created:
            try:
                row.external_created_at = datetime.fromisoformat(
                    str(created).replace("Z", "+00:00")
                )
            except ValueError:
                row.external_created_at = None
        row.last_remote_checked_at = now
        row.remote_snapshot = snapshot
        row.broker_recovery_run_id = (
            recovery_run_id or row.broker_recovery_run_id
        )
        row.updated_at = now
        self._session.flush()

        if created_new:
            AuditEventRepository(self._session).create(
                event_type="RECOVERY_CONFLICT_CREATED",
                actor="system:recovery",
                request_id=None,
                run_id=(
                    str(recovery_run_id) if recovery_run_id else None
                ),
                strategy_id=None,
                account_hash=None,
                order_id=None,
                client_order_id=None,
                symbol=row.market_code,
                detail={
                    "conflict_id": int(row.broker_recovery_conflict_id),
                    "user_id": user_id,
                    "user_broker_account_id": user_broker_account_id,
                    "broker_code": broker_code.upper(),
                    "external_order_id_masked": row.external_order_id_masked,
                    "conflict_type": row.conflict_type,
                    "review_status": row.review_status,
                },
                created_at=now,
            )
        return row

    def pause_account_for_conflicts(
        self,
        *,
        user_broker_account_id: int | None,
        user_id: int | None,
        broker_code: str = "UPBIT",
    ) -> None:
        if user_broker_account_id is None:
            return
        stmt = select(BrokerRecoveryAccountStateEntity).where(
            BrokerRecoveryAccountStateEntity.broker_code
            == broker_code.upper(),
            BrokerRecoveryAccountStateEntity.user_broker_account_id
            == int(user_broker_account_id),
        )
        row = self._session.scalar(stmt.limit(1))
        now = _utcnow()
        if row is None:
            row = BrokerRecoveryAccountStateEntity(
                broker_code=broker_code.upper(),
                user_id=user_id,
                user_broker_account_id=int(user_broker_account_id),
            )
            self._session.add(row)
        row.trading_paused = True
        row.recovery_status = "MANUAL_REVIEW"
        row.last_error_code = "manual_review_required"
        row.last_error_summary = PAUSE_REASON_REMOTE_ONLY
        row.auto_retry_enabled = False
        row.updated_at = now
        self._session.flush()

    def list_conflicts(
        self,
        *,
        broker_code: str | None = None,
        user_id: int | None = None,
        user_broker_account_id: int | None = None,
        review_status: str | None = None,
        conflict_type: str | None = None,
        market_code: str | None = None,
        resolved: bool | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[BrokerRecoveryConflictEntity]:
        stmt = select(BrokerRecoveryConflictEntity)
        if broker_code:
            stmt = stmt.where(
                BrokerRecoveryConflictEntity.broker_code
                == broker_code.upper()
            )
        if user_id is not None:
            stmt = stmt.where(
                BrokerRecoveryConflictEntity.user_id == int(user_id)
            )
        if user_broker_account_id is not None:
            stmt = stmt.where(
                BrokerRecoveryConflictEntity.user_broker_account_id
                == int(user_broker_account_id)
            )
        if review_status:
            stmt = stmt.where(
                BrokerRecoveryConflictEntity.review_status
                == review_status
            )
        if conflict_type:
            stmt = stmt.where(
                BrokerRecoveryConflictEntity.conflict_type
                == conflict_type
            )
        if market_code:
            stmt = stmt.where(
                BrokerRecoveryConflictEntity.market_code == market_code
            )
        if resolved is True:
            stmt = stmt.where(
                BrokerRecoveryConflictEntity.review_status.notin_(
                    list(ACTIVE_REVIEW_STATUSES)
                )
            )
        elif resolved is False:
            stmt = stmt.where(
                BrokerRecoveryConflictEntity.review_status.in_(
                    list(ACTIVE_REVIEW_STATUSES)
                )
            )
        stmt = (
            stmt.order_by(
                BrokerRecoveryConflictEntity.broker_recovery_conflict_id.desc()
            )
            .offset(max(0, offset))
            .limit(max(1, min(limit, 200)))
        )
        return list(self._session.scalars(stmt))

    def get(self, conflict_id: int) -> BrokerRecoveryConflictEntity:
        row = self._session.get(
            BrokerRecoveryConflictEntity, int(conflict_id)
        )
        if row is None:
            raise RecoveryConflictError(
                "conflict_not_found", "Conflict not found"
            )
        return row

    def as_list_item(
        self, row: BrokerRecoveryConflictEntity
    ) -> dict[str, Any]:
        paused = False
        masked_account = None
        if row.user_broker_account_id is not None:
            paused = RecoveryAccountLockService(
                self._session
            ).is_trading_paused(
                user_broker_account_id=int(row.user_broker_account_id),
                broker_code=row.broker_code,
            )
            uba = self._session.get(
                UserBrokerAccount, int(row.user_broker_account_id)
            )
            if uba is not None:
                masked_account = uba.masked_account_number
        return {
            "conflict_id": int(row.broker_recovery_conflict_id),
            "user_id": row.user_id,
            "user_broker_account_id": row.user_broker_account_id,
            "masked_account": masked_account,
            "broker_code": row.broker_code,
            "conflict_type": row.conflict_type,
            "external_order_id_masked": row.external_order_id_masked,
            "market_code": row.market_code,
            "side_code": row.side_code,
            "order_type_code": row.order_type_code,
            "requested_quantity": (
                str(row.requested_quantity)
                if row.requested_quantity is not None
                else None
            ),
            "executed_quantity": (
                str(row.executed_quantity)
                if row.executed_quantity is not None
                else None
            ),
            "remaining_quantity": (
                str(row.remaining_quantity)
                if row.remaining_quantity is not None
                else None
            ),
            "order_price": (
                str(row.order_price) if row.order_price is not None else None
            ),
            "average_execution_price": (
                str(row.average_execution_price)
                if row.average_execution_price is not None
                else None
            ),
            "paid_fee": (
                str(row.paid_fee) if row.paid_fee is not None else None
            ),
            "external_status": row.external_status,
            "detected_at": (
                row.detected_at.isoformat() if row.detected_at else None
            ),
            "last_remote_checked_at": (
                row.last_remote_checked_at.isoformat()
                if row.last_remote_checked_at
                else None
            ),
            "review_status": row.review_status,
            "review_complete": row.review_status
            in REVIEW_COMPLETE_STATUSES,
            "risk_level": row.risk_level,
            "account_paused": paused,
            "linked_internal_order_id": row.linked_internal_order_id,
            "resolution_type": row.resolution_type,
            "resolution_note": row.resolution_note,
        }

    def as_detail(
        self, row: BrokerRecoveryConflictEntity
    ) -> dict[str, Any]:
        data = self.as_list_item(row)
        # Snapshot은 이미 sanitize됨 — Secret 키 없음; API 응답도 Decimal 안전
        data["remote_snapshot"] = to_jsonable(dict(row.remote_snapshot or {}))
        data["pause_reason"] = row.pause_reason
        data["resolved_by"] = row.resolved_by
        data["resolved_at"] = (
            row.resolved_at.isoformat() if row.resolved_at else None
        )
        # 전체 UUID는 ADMIN 상세에서도 마스킹 유지 (보안)
        data["external_order_id_full_length"] = len(
            row.external_order_id or ""
        )
        return data

    def refresh_from_remote(
        self, conflict_id: int, *, actor: str
    ) -> BrokerRecoveryConflictEntity:
        row = self.get(conflict_id)
        if row.broker_code.upper() != "UPBIT":
            raise RecoveryConflictError(
                "unsupported_broker", "Only UPBIT supported"
            )
        if row.user_broker_account_id is None:
            raise RecoveryConflictError(
                "uba_required", "Conflict missing user_broker_account_id"
            )

        client = self._vault_order_client(int(row.user_broker_account_id))
        try:
            remote = client.get_order(uuid=row.external_order_id)
        except Exception as exc:  # noqa: BLE001
            from stock_platform.broker.upbit.exceptions import (
                UpbitBanOrBlockError,
                UpbitOrderNotFoundError,
                UpbitRateLimitError,
                UpbitTemporaryUnavailableError,
            )

            if isinstance(exc, UpbitOrderNotFoundError) or (
                "not found" in str(exc).lower() or "404" in str(exc)
            ):
                row.review_status = (
                    RecoveryConflictReviewStatus.REMOTE_DISAPPEARED
                )
                row.resolution_type = (
                    RecoveryConflictResolution.REMOTE_ORDER_CANCELLED
                )
                row.resolved_by = actor
                row.resolved_at = _utcnow()
                row.external_status = "not_found"
                row.last_remote_checked_at = _utcnow()
                row.updated_at = _utcnow()
                self._session.flush()
                return row
            if isinstance(exc, UpbitRateLimitError):
                raise RecoveryConflictError(
                    "upbit_rate_limited",
                    "Upbit rate limited — retry later",
                    detail={
                        "retry_after_seconds": exc.retry_after_seconds,
                        "cooldown_until": (
                            exc.cooldown_until.isoformat()
                            if exc.cooldown_until
                            else None
                        ),
                        "http_status": 429,
                    },
                ) from exc
            if isinstance(exc, UpbitBanOrBlockError):
                raise RecoveryConflictError(
                    "upbit_blocked_418",
                    "Upbit account blocked (418) — admin review required",
                    detail={"http_status": 418},
                ) from exc
            if isinstance(exc, UpbitTemporaryUnavailableError):
                raise RecoveryConflictError(
                    "upbit_temporary_unavailable",
                    "Upbit temporarily unavailable",
                    detail={"http_status": exc.http_status},
                ) from exc
            raise RecoveryConflictError(
                "remote_refresh_failed",
                f"Upbit refresh failed: {exc.__class__.__name__}",
            ) from exc

        snapshot = sanitize_upbit_order_snapshot(remote)
        row.remote_snapshot = snapshot
        row.market_code = str(remote.get("market") or row.market_code)
        row.side_code = _parse_side(remote)
        row.order_type_code = _parse_order_type(remote).value
        row.external_status = str(remote.get("state") or "")
        row.requested_quantity = _dec(remote.get("volume"))
        row.executed_quantity = _dec(remote.get("executed_volume"))
        rem = _dec(remote.get("remaining_volume"))
        if rem is None and row.requested_quantity is not None:
            rem = row.requested_quantity - (
                row.executed_quantity or Decimal("0")
            )
        row.remaining_quantity = rem
        row.order_price = _dec(remote.get("price"))
        row.average_execution_price = _dec(remote.get("avg_price"))
        row.paid_fee = _dec(remote.get("paid_fee"))
        row.last_remote_checked_at = _utcnow()
        row.updated_at = _utcnow()
        self._session.flush()
        return row

    def approve_import(
        self, conflict_id: int, *, actor: str, note: str | None = None
    ) -> dict[str, Any]:
        """내부 주문·체결 복구. Upbit 주문 API는 절대 호출하지 않는다."""

        row = self.get(conflict_id)
        if row.review_status not in ACTIVE_REVIEW_STATUSES:
            raise RecoveryConflictError(
                "already_resolved",
                f"Conflict already resolved: {row.review_status}",
            )
        if row.broker_code.upper() != "UPBIT":
            raise RecoveryConflictError(
                "unsupported_broker", "Only UPBIT import supported"
            )
        if row.user_broker_account_id is None:
            raise RecoveryConflictError(
                "uba_required", "UBA required for import"
            )

        uba = self._session.get(
            UserBrokerAccount, int(row.user_broker_account_id)
        )
        if uba is None or not uba.is_active:
            raise RecoveryConflictError(
                "uba_inactive", "User broker account inactive"
            )

        # Credential 사용 가능 여부 (주문 전송 아님)
        try:
            BrokerCredentialVaultService(
                self._session
            ).assert_live_order_allowed(
                int(row.user_broker_account_id),
                broker_code="UPBIT",
            )
        except BrokerCredentialVaultError as exc:
            raise RecoveryConflictError(exc.code, exc.message) from exc

        # 최신 외부 상태 재확인 (조회만 — 주문 생성 API 아님)
        row = self.refresh_from_remote(conflict_id, actor=actor)
        if row.review_status == (
            RecoveryConflictReviewStatus.REMOTE_DISAPPEARED
        ):
            raise RecoveryConflictError(
                "remote_disappeared",
                "Remote order no longer exists",
            )

        remote = dict(row.remote_snapshot or {})
        uuid = row.external_order_id

        # 중복 내부 주문
        dup = TradingOrderRepository(self._session).get_by_broker_order_id(
            broker_code="UPBIT",
            broker_order_id=uuid,
            user_broker_account_id=int(row.user_broker_account_id),
        )
        if dup is not None:
            # rollback 시 상태 유실 방지 — 변경 없이 409만 반환
            raise RecoveryConflictError(
                "duplicate_internal_order",
                f"Internal order already exists: {dup.order_id}",
            )

        qty = row.requested_quantity or Decimal("0")
        if qty <= 0:
            raise RecoveryConflictError(
                "invalid_quantity", "Requested quantity must be > 0"
            )
        executed = row.executed_quantity or Decimal("0")
        if executed > qty:
            raise RecoveryConflictError(
                "invalid_fill", "Executed quantity exceeds order quantity"
            )

        account_id = None  # LIVE — Paper FK unused; UBA only
        side = OrderSide.BUY if row.side_code == "BUY" else OrderSide.SELL
        order_type = (
            OrderType.MARKET
            if (row.order_type_code or "").upper() == "MARKET"
            else OrderType.LIMIT
        )
        price = row.order_price
        if order_type == OrderType.LIMIT and (
            price is None or price <= 0
        ):
            # 시장가/지정가 혼재 — avg로 대체하지 않고 market로 처리
            order_type = OrderType.MARKET
            price = None

        market = row.market_code or "KRW-BTC"
        symbol = market.split("-")[-1] if "-" in market else market

        metadata = {
            "order_origin": ORDER_ORIGIN_RECOVERY_IMPORT,
            "recovery_conflict_id": int(row.broker_recovery_conflict_id),
            "external_order_id": uuid,
            "created_by": actor,
            "broker_submit": False,
            "upbit_market": market,
        }
        command = CreateOrderCommand(
            account_id=account_id,
            broker_code="UPBIT",
            exchange_code="UPBIT",
            symbol=symbol,
            side=side,
            order_type=order_type,
            quantity=qty,
            price=price,
            time_in_force=OrderTimeInForce.DAY,
            user_broker_account_id=int(row.user_broker_account_id),
            client_order_id=ClientOrderIdGenerator.generate(),
            metadata_payload=metadata,
        )
        # DB 생성만 — Outbox/Adapter 주문 전송 없음
        entity = TradingOrderService(self._session).create(
            command,
            actor=actor,
            commit=False,
        )
        status = _map_remote_status(remote)
        entity.broker_order_id = uuid
        entity.status_code = status.value
        entity.filled_quantity = executed
        remaining = row.remaining_quantity
        if remaining is None:
            remaining = qty - executed
        entity.remaining_quantity = (
            remaining if remaining > 0 else Decimal("0")
        )
        if row.average_execution_price is not None:
            entity.average_fill_price = row.average_execution_price
        if row.paid_fee is not None:
            entity.filled_amount = executed * (
                row.average_execution_price or Decimal("0")
            )
        now = _utcnow()
        entity.accepted_at = now
        entity.sent_at = now
        if status == OrderStatus.FILLED:
            entity.filled_at = now
        if status == OrderStatus.CANCELLED:
            entity.cancelled_at = now
        if status == OrderStatus.PARTIALLY_FILLED:
            entity.first_filled_at = now
        self._session.flush()

        # 체결 Import
        trades = remote.get("trades") or []
        imported_fills = 0
        if isinstance(trades, list):
            for trade in trades:
                if not isinstance(trade, dict):
                    continue
                trade_id = str(
                    trade.get("uuid")
                    or trade.get("trade_id")
                    or ""
                ).strip()
                if not trade_id:
                    # UUID 없으면 합성 키 (주문+가격+수량+시각)
                    trade_id = (
                        f"{uuid}-"
                        f"{trade.get('price')}-"
                        f"{trade.get('volume')}-"
                        f"{trade.get('created_at')}"
                    )
                exists = self._session.scalar(
                    select(TradingExecution).where(
                        TradingExecution.broker_code == "UPBIT",
                        TradingExecution.broker_execution_id
                        == trade_id,
                    )
                )
                if exists is not None:
                    continue
                exec_price = _dec(trade.get("price")) or Decimal("0")
                exec_qty = _dec(trade.get("volume")) or Decimal("0")
                if exec_qty <= 0:
                    continue
                executed_at = now
                created = trade.get("created_at")
                if created:
                    try:
                        executed_at = datetime.fromisoformat(
                            str(created).replace("Z", "+00:00")
                        )
                    except ValueError:
                        pass
                self._session.add(
                    TradingExecution(
                        order_id=int(entity.order_id),
                        broker_code="UPBIT",
                        broker_order_id=uuid,
                        broker_execution_id=trade_id[:100],
                        symbol=symbol,
                        side_code=row.side_code,
                        execution_price=exec_price,
                        execution_quantity=exec_qty,
                        executed_at=executed_at,
                        raw_json={
                            k: trade.get(k)
                            for k in (
                                "price",
                                "volume",
                                "funds",
                                "side",
                                "created_at",
                            )
                            if k in trade
                        },
                    )
                )
                imported_fills += 1

        row.review_status = RecoveryConflictReviewStatus.APPROVED_IMPORT
        row.resolution_type = (
            RecoveryConflictResolution.IMPORT_INTERNAL_ORDER
        )
        row.linked_internal_order_id = int(entity.order_id)
        row.resolved_by = actor
        row.resolved_at = now
        row.resolution_note = note
        row.updated_at = now
        self._session.flush()

        return {
            "conflict_id": int(row.broker_recovery_conflict_id),
            "internal_order_id": int(entity.order_id),
            "imported_fills": imported_fills,
            "review_status": row.review_status,
            "broker_submit": False,
        }

    def ignore(
        self, conflict_id: int, *, actor: str, note: str
    ) -> BrokerRecoveryConflictEntity:
        if not (note or "").strip():
            raise RecoveryConflictError(
                "note_required", "Ignore reason is required"
            )
        row = self.get(conflict_id)
        if row.review_status not in ACTIVE_REVIEW_STATUSES:
            raise RecoveryConflictError(
                "already_resolved",
                f"Conflict already resolved: {row.review_status}",
            )
        row.review_status = RecoveryConflictReviewStatus.IGNORED
        row.resolution_type = (
            RecoveryConflictResolution.IGNORE_EXTERNAL_ORDER
        )
        row.resolved_by = actor
        row.resolved_at = _utcnow()
        row.resolution_note = note.strip()[:2000]
        row.updated_at = _utcnow()
        self._session.flush()
        return row

    def preserve_history(
        self, conflict_id: int, *, actor: str, note: str
    ) -> BrokerRecoveryConflictEntity:
        """HISTORY_PRESERVE — Import/Ignore 없이 검토 완료·이력 보존.

        Position/Balance/Risk는 변경하지 않는다. Conflict 행·remote_snapshot 유지.
        """

        if not (note or "").strip():
            raise RecoveryConflictError(
                "note_required", "Preserve reason is required"
            )
        row = self.get(conflict_id)
        if row.review_status == (
            RecoveryConflictReviewStatus.HISTORICAL_PRESERVED
        ):
            # idempotent
            return row
        if row.review_status not in ACTIVE_REVIEW_STATUSES:
            raise RecoveryConflictError(
                "already_resolved",
                f"Conflict already resolved: {row.review_status}",
            )
        row.review_status = (
            RecoveryConflictReviewStatus.HISTORICAL_PRESERVED
        )
        row.resolution_type = RecoveryConflictResolution.PRESERVE_HISTORY
        row.resolved_by = actor
        row.resolved_at = _utcnow()
        row.resolution_note = note.strip()[:2000]
        row.updated_at = _utcnow()
        self._session.flush()
        return row

    def hold(
        self, conflict_id: int, *, actor: str, note: str
    ) -> BrokerRecoveryConflictEntity:
        if not (note or "").strip():
            raise RecoveryConflictError(
                "note_required", "Hold reason is required"
            )
        row = self.get(conflict_id)
        if row.review_status not in {
            RecoveryConflictReviewStatus.PENDING_REVIEW,
            RecoveryConflictReviewStatus.ON_HOLD,
        }:
            raise RecoveryConflictError(
                "invalid_status",
                f"Cannot hold from status: {row.review_status}",
            )
        row.review_status = RecoveryConflictReviewStatus.ON_HOLD
        row.resolution_type = RecoveryConflictResolution.KEEP_PAUSED
        row.resolution_note = note.strip()[:2000]
        row.updated_at = _utcnow()
        # pause 유지
        if row.user_broker_account_id is not None:
            self.pause_account_for_conflicts(
                user_broker_account_id=int(row.user_broker_account_id),
                user_id=row.user_id,
                broker_code=row.broker_code,
            )
        self._session.flush()
        return row

    def count_active_for_uba(self, uba_id: int) -> int:
        """계정 pause/resume 차단용 — SAME_SYMBOL ON_HOLD·INFO MANUAL은 제외."""

        stmt = select(func.count()).select_from(
            BrokerRecoveryConflictEntity
        ).where(
            BrokerRecoveryConflictEntity.user_broker_account_id
            == int(uba_id),
            BrokerRecoveryConflictEntity.review_status.in_(
                list(ACTIVE_REVIEW_STATUSES)
            ),
            BrokerRecoveryConflictEntity.conflict_type
            != "SAME_SYMBOL_MANUAL_AUTO_CONFLICT",
            BrokerRecoveryConflictEntity.risk_level != "INFO",
        )
        return int(self._session.scalar(stmt) or 0)

    def count_blocking_orders_for_uba(self, uba_id: int) -> dict[str, int]:
        """Resume 사전조건 — DB Open / 미확정 / cancel·replace pending 건수."""
        from stock_platform.order.entities import TradingOrderEntity

        open_statuses = {
            OrderStatus.CREATED.value,
            OrderStatus.PENDING.value,
            OrderStatus.SUBMITTING.value,
            OrderStatus.SENT.value,
            OrderStatus.ACCEPTED.value,
            OrderStatus.PARTIALLY_FILLED.value,
            OrderStatus.REMOTE_LOOKUP_PENDING.value,
        }
        submission_unknown = {
            OrderStatus.AMBIGUOUS_SUBMISSION.value,
            OrderStatus.MANUAL_REVIEW_REQUIRED.value,
        }
        cancel_pending = {OrderStatus.CANCEL_REQUESTED.value}
        replace_pending = {OrderStatus.REPLACE_REQUESTED.value}

        def _count(statuses: set[str]) -> int:
            return int(
                self._session.scalar(
                    select(func.count())
                    .select_from(TradingOrderEntity)
                    .where(
                        TradingOrderEntity.user_broker_account_id
                        == int(uba_id),
                        TradingOrderEntity.status_code.in_(list(statuses)),
                    )
                )
                or 0
            )

        return {
            "db_open": _count(open_statuses),
            "submission_unknown": _count(submission_unknown),
            "cancel_pending": _count(cancel_pending),
            "replace_pending": _count(replace_pending),
        }

    def resume_account(
        self,
        uba_id: int,
        *,
        actor: str,
        reason: str,
        correlation_id: str,
        kill_switch_active: bool = False,
    ) -> dict[str, Any]:
        """Admin 전용 Pause 해제. Recovery/Scheduler 경로는 이 함수를 호출하지 않는다."""
        if not (reason or "").strip():
            raise RecoveryConflictError(
                "reason_required", "Resume reason is required"
            )
        if not (correlation_id or "").strip():
            raise RecoveryConflictError(
                "correlation_id_required",
                "correlation_id is required",
            )
        uba = self._session.get(UserBrokerAccount, int(uba_id))
        if uba is None or not uba.is_active:
            raise RecoveryConflictError(
                "uba_inactive", "Account not found or inactive"
            )
        # Resume SoT = UBA entity broker_code (request/env/global 금지)
        broker = str(uba.broker_code or "").strip().upper()
        if broker not in {"UPBIT", "KIWOOM"}:
            raise RecoveryConflictError(
                "unsupported_broker",
                f"Resume not supported for broker={broker or 'UNKNOWN'}",
            )
        active = self.count_active_for_uba(uba_id)
        if active > 0:
            raise RecoveryConflictError(
                "unresolved_conflicts",
                f"Unresolved conflicts remain: {active}",
            )
        blocking = self.count_blocking_orders_for_uba(uba_id)
        if blocking["db_open"] > 0:
            raise RecoveryConflictError(
                "db_open_orders",
                f"DB open orders remain: {blocking['db_open']}",
                detail=blocking,
            )
        if blocking["submission_unknown"] > 0:
            raise RecoveryConflictError(
                "submission_unknown",
                f"Submission unknown remain: {blocking['submission_unknown']}",
                detail=blocking,
            )
        if blocking["cancel_pending"] > 0:
            raise RecoveryConflictError(
                "cancel_pending",
                f"Cancel pending remain: {blocking['cancel_pending']}",
                detail=blocking,
            )
        if blocking["replace_pending"] > 0:
            raise RecoveryConflictError(
                "replace_pending",
                f"Replace pending remain: {blocking['replace_pending']}",
                detail=blocking,
            )
        try:
            BrokerCredentialVaultService(
                self._session
            ).assert_live_order_allowed(uba_id, broker_code=broker)
        except BrokerCredentialVaultError as exc:
            raise RecoveryConflictError(exc.code, exc.message) from exc

        if kill_switch_active:
            raise RecoveryConflictError(
                "kill_switch_active", "Kill switch is active"
            )

        stmt = select(BrokerRecoveryAccountStateEntity).where(
            BrokerRecoveryAccountStateEntity.user_broker_account_id
            == int(uba_id),
            BrokerRecoveryAccountStateEntity.broker_code == broker,
        )
        state = self._session.scalar(stmt.limit(1))
        live_on = bool(getattr(uba, "live_order_enabled", False))
        armed = bool(getattr(uba, "live_armed", False))
        if state is None:
            return {
                "user_broker_account_id": uba_id,
                "broker_code": broker,
                "trading_paused": False,
                "resumed": True,
                "actor": actor,
                "reason": reason.strip()[:2000],
                "correlation_id": correlation_id.strip()[:128],
                "live_order_enabled": live_on,
                "live_armed": armed,
                "live_arm_unchanged": True,
                "scheduler_unchanged": True,
            }
        if state.recovery_status == "RUNNING":
            raise RecoveryConflictError(
                "recovery_running", "Recovery still running"
            )
        # STEP 8-15A — 운영 코드에서 trading_paused=False 는 이 경로만 허용
        before_paused = bool(state.trading_paused)
        if not before_paused:
            # STEP 8-16 — 이미 Resume된 계좌: idempotent (상태 변경·추가 부작용 없음)
            return {
                "user_broker_account_id": uba_id,
                "broker_code": broker,
                "trading_paused": False,
                "resumed": False,
                "already_resumed": True,
                "before_trading_paused": False,
                "actor": actor,
                "reason": reason.strip()[:2000],
                "correlation_id": correlation_id.strip()[:128],
                "blocking_orders": blocking,
                "live_order_enabled": live_on,
                "live_armed": armed,
                "live_arm_unchanged": True,
                "scheduler_unchanged": True,
            }
        state.trading_paused = False
        state.recovery_status = "SUCCESS"
        state.last_error_summary = None
        state.last_error_code = None
        state.auto_retry_enabled = True
        state.updated_at = _utcnow()
        self._session.flush()
        return {
            "user_broker_account_id": uba_id,
            "broker_code": broker,
            "trading_paused": False,
            "resumed": True,
            "already_resumed": False,
            "before_trading_paused": before_paused,
            "actor": actor,
            "reason": reason.strip()[:2000],
            "correlation_id": correlation_id.strip()[:128],
            "blocking_orders": blocking,
            "live_order_enabled": live_on,
            "live_armed": armed,
            "live_arm_unchanged": True,
            "scheduler_unchanged": True,
        }

    def _vault_order_client(
        self, uba_id: int
    ) -> UpbitOrderRestClient:
        resolved = BrokerCredentialVaultService(
            self._session
        ).resolve_for_runtime(
            uba_id,
            expected_broker="UPBIT",
            require_verified=True,
            touch_last_used=True,
        )
        settings = build_upbit_settings_from_vault(resolved)
        return UpbitOrderRestClient(
            settings=settings,
            user_broker_account_id=int(uba_id),
        )

    def _resolve_account_id(self, user_id: int) -> int | None:
        """Legacy helper — LIVE orders do not use paper account_id.

        Call sites pass account_id=None with user_broker_account_id set.
        """

        return None
