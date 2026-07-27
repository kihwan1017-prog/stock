"""STEP 8-4 — Kiwoom Recovery Adapter (STEP 8-5-2 Vault 연동)."""

from __future__ import annotations

from stock_platform.broker.credential_adapter_factory import (
    build_kiwoom_account_client_for_uba,
)
from stock_platform.broker.credential_vault_service import (
    BrokerCredentialVaultError,
)
from stock_platform.broker.kiwoom.account_factory import (
    build_kiwoom_account_client,
)
from stock_platform.broker.kiwoom.account_sync_service import (
    KiwoomAccountSyncService,
)
from stock_platform.broker.kiwoom.pending_client import (
    KiwoomPendingOrderClient,
)
from stock_platform.broker.kiwoom.pending_factory import (
    build_kiwoom_pending_order_client,
)
from stock_platform.broker.kiwoom.pending_service import (
    KiwoomPendingOrderService,
)
from stock_platform.broker.recovery_adapter import (
    AccountRecoveryContext,
    AdapterRecoveryResult,
)
from stock_platform.common.settings import get_settings
from stock_platform.database.session import get_session_factory


class KiwoomRecoveryAdapter:
    broker_code = "KIWOOM"

    def supports(self, context: AccountRecoveryContext) -> bool:
        return context.broker_code.upper() == "KIWOOM"

    async def recover(
        self, context: AccountRecoveryContext
    ) -> AdapterRecoveryResult:
        result = AdapterRecoveryResult(
            status="SUCCESS",
            broker_code=self.broker_code,
            paper_account_id=context.paper_account_id,
            user_broker_account_id=context.user_broker_account_id,
            user_id=context.user_id,
        )
        settings = get_settings()
        session = get_session_factory()()
        account_client = None
        pending_client = None
        account_number = ""

        try:
            if context.user_broker_account_id is not None:
                # UBA Recovery → Vault Credential 필수 (env fallback 금지)
                try:
                    account_client, account_number = (
                        build_kiwoom_account_client_for_uba(
                            session,
                            int(context.user_broker_account_id),
                        )
                    )
                    pending_client = KiwoomPendingOrderClient(
                        account_client._client
                    )
                except BrokerCredentialVaultError as exc:
                    result.status = "FAILED"
                    result.errors.append(exc.code)
                    result.detail["credential_error"] = {
                        "code": exc.code,
                        "message": exc.message,
                    }
                    result.trading_should_remain_paused = True
                    result.retry_required = True
                    return result.finish()
            else:
                # 운영 공용(시스템) 경로만 env 허용
                account_number = (
                    context.account_number_for_broker
                    or settings.kiwoom_account_number.strip()
                )
                if not account_number:
                    result.status = "SKIPPED"
                    result.warnings.append("KIWOOM_ACCOUNT_NUMBER empty")
                    return result.finish()
                account_client = build_kiwoom_account_client()
                pending_client = build_kiwoom_pending_order_client()

            account_detail = await KiwoomAccountSyncService(
                session=session,
                account_client=account_client,
                user_broker_account_id=context.user_broker_account_id,
            ).synchronize(
                user_broker_account_id=context.user_broker_account_id
            )
            result.balances_updated = 1
            result.positions_updated = int(
                account_detail.get("position_count")
                or len(account_detail.get("positions") or [])
                or 0
            )
            result.detail["account_sync"] = {
                k: account_detail.get(k)
                for k in (
                    "broker_account_snapshot_id",
                    "broker_code",
                    "deposit_amount",
                )
                if k in account_detail
            }

            if context.user_broker_account_id is None:
                result.warnings.append(
                    "pending sync skipped: user_broker_account_id required"
                )
            else:
                pending = await KiwoomPendingOrderService(
                    session=session,
                    client=pending_client,
                ).synchronize(
                    user_broker_account_id=int(
                        context.user_broker_account_id
                    ),
                    account_number=account_number,
                )
                result.open_orders_checked = int(
                    pending.get("count")
                    or pending.get("pending_order_count")
                    or pending.get("pending_count")
                    or 0
                )
                result.orders_updated = int(
                    pending.get("pending_order_count")
                    or pending.get("count")
                    or 0
                )
                result.detail["pending"] = {
                    k: pending.get(k)
                    for k in pending
                    if k not in {"items", "orders"}
                }

            try:
                from stock_platform.broker.kiwoom.inquiry_client import (
                    KiwoomOrderInquiryClient,
                )
                from stock_platform.broker.kiwoom.recovery import (
                    KiwoomOrderRecoveryService,
                )

                inquiry = KiwoomOrderInquiryClient(
                    account_client._client
                )
                summary = KiwoomOrderRecoveryService(
                    session=session,
                    inquiry_client=inquiry,
                ).recover_pending_orders(
                    account_number=account_number,
                    actor="KIWOOM_RECOVERY_ADAPTER",
                )
                session.commit()
                result.orders_updated += int(summary.matched_orders)
                result.conflicts_found += int(
                    summary.missing_local_orders
                )
                if summary.missing_local_orders > 0:
                    result.warnings.append(
                        "External pending without local match "
                        "→ manual_review"
                    )
            except Exception as exc:  # noqa: BLE001
                result.warnings.append(
                    f"trading_order recovery skipped: {exc}"
                )

        except BrokerCredentialVaultError as exc:
            session.rollback()
            result.status = "FAILED"
            result.errors.append(exc.code)
            result.detail["credential_error"] = {
                "code": exc.code,
                "message": exc.message,
            }
            result.trading_should_remain_paused = True
            result.retry_required = True
        except Exception as exc:  # noqa: BLE001
            session.rollback()
            result.status = "FAILED"
            result.errors.append(str(exc))
            result.trading_should_remain_paused = True
            result.retry_required = True
        finally:
            session.close()

        if result.conflicts_found > 0 and result.status == "SUCCESS":
            result.status = "PARTIAL"
        return result.finish()
