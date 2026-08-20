"""STEP 8-8A — Post-Fill Broker Sync 헬퍼."""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session


class PostFillBrokerSyncError(Exception):
    """Sync 실패 — Broker Down 포함."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def sync_broker_snapshot_for_uba(
    session: Session,
    *,
    user_broker_account_id: int,
    broker_code: str,
) -> dict[str, Any]:
    """UBA별 Broker position/cash Snapshot 갱신.

    Paper는 즉시 가능하면 no-op 성공.
    LIVE Kiwoom/Upbit는 해당 Sync 서비스 호출.
    """

    code = (broker_code or "").strip().upper()
    uba_id = int(user_broker_account_id)

    if code in {"PAPER", "MOCK", "SIM"}:
        return {
            "broker_code": code,
            "synced": True,
            "mode": "PAPER_MOCK_NOOP",
        }

    try:
        if code == "UPBIT":
            return _sync_upbit(session, uba_id=uba_id)
        if code == "KIWOOM":
            return _sync_kiwoom(session, uba_id=uba_id)
    except PostFillBrokerSyncError:
        raise
    except Exception as exc:  # noqa: BLE001
        msg = str(exc)[:300]
        lowered = msg.lower()
        if any(
            x in lowered
            for x in (
                "disconnect",
                "timeout",
                "connection",
                "unavailable",
                "down",
                "network",
            )
        ):
            raise PostFillBrokerSyncError("BROKER_DOWN", msg) from exc
        raise PostFillBrokerSyncError("SYNC_FAILED", msg) from exc

    raise PostFillBrokerSyncError(
        "UNSUPPORTED_BROKER", f"unsupported broker_code={code}"
    )


def _sync_kiwoom(session: Session, *, uba_id: int) -> dict[str, Any]:
    import asyncio

    from stock_platform.broker.credential_adapter_factory import (
        build_kiwoom_account_client_for_uba,
    )
    from stock_platform.broker.credential_vault_service import (
        BrokerCredentialVaultError,
    )
    from stock_platform.broker.kiwoom.account_sync_service import (
        KiwoomAccountSyncService,
    )

    async def _run() -> dict[str, Any]:
        account_client, _account_number = build_kiwoom_account_client_for_uba(
            session, uba_id
        )
        return await KiwoomAccountSyncService(
            session=session,
            account_client=account_client,
            user_broker_account_id=uba_id,
        ).synchronize(user_broker_account_id=uba_id)

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        try:
            result = asyncio.run(_run())
        except BrokerCredentialVaultError as exc:
            raise PostFillBrokerSyncError(exc.code, exc.message) from exc
    else:
        # 이미 이벤트 루프가 있으면 동기 sync가 막히지 않도록 예외 처리
        # 스케줄러 경로는 async worker에서 await 가능한 별도 진입 사용
        raise PostFillBrokerSyncError(
            "ASYNC_CONTEXT",
            "use sync_broker_snapshot_for_uba_async in async context",
        ) from None
    return {"broker_code": "KIWOOM", "synced": True, "result": result}


async def sync_broker_snapshot_for_uba_async(
    session: Session,
    *,
    user_broker_account_id: int,
    broker_code: str,
) -> dict[str, Any]:
    """Async 컨텍스트용 Sync."""

    code = (broker_code or "").strip().upper()
    uba_id = int(user_broker_account_id)

    if code in {"PAPER", "MOCK", "SIM"}:
        return {
            "broker_code": code,
            "synced": True,
            "mode": "PAPER_MOCK_NOOP",
        }

    try:
        if code == "UPBIT":
            from stock_platform.broker.upbit.account_factory import (
                build_upbit_private_client,
            )
            from stock_platform.broker.upbit.account_sync_service import (
                UpbitAccountSyncService,
            )

            result = await UpbitAccountSyncService(
                session=session,
                private_client=build_upbit_private_client(),
                user_broker_account_id=uba_id,
            ).synchronize(user_broker_account_id=uba_id)
            return {"broker_code": "UPBIT", "synced": True, "result": result}

        if code == "KIWOOM":
            from stock_platform.broker.credential_adapter_factory import (
                build_kiwoom_account_client_for_uba,
            )
            from stock_platform.broker.credential_vault_service import (
                BrokerCredentialVaultError,
            )
            from stock_platform.broker.kiwoom.account_sync_service import (
                KiwoomAccountSyncService,
            )

            try:
                account_client, _account_number = (
                    build_kiwoom_account_client_for_uba(session, uba_id)
                )
            except BrokerCredentialVaultError as exc:
                raise PostFillBrokerSyncError(exc.code, exc.message) from exc

            result = await KiwoomAccountSyncService(
                session=session,
                account_client=account_client,
                user_broker_account_id=uba_id,
            ).synchronize(user_broker_account_id=uba_id)
            return {
                "broker_code": "KIWOOM",
                "synced": True,
                "result": result,
            }
    except Exception as exc:  # noqa: BLE001
        msg = str(exc)[:300]
        lowered = msg.lower()
        if any(
            x in lowered
            for x in (
                "disconnect",
                "timeout",
                "connection",
                "unavailable",
                "down",
                "network",
            )
        ):
            raise PostFillBrokerSyncError("BROKER_DOWN", msg) from exc
        raise PostFillBrokerSyncError("SYNC_FAILED", msg) from exc

    raise PostFillBrokerSyncError(
        "UNSUPPORTED_BROKER", f"unsupported broker_code={code}"
    )


def _sync_upbit(session: Session, *, uba_id: int) -> dict[str, Any]:
    import asyncio

    async def _run() -> dict[str, Any]:
        from stock_platform.broker.upbit.account_factory import (
            build_upbit_private_client,
        )
        from stock_platform.broker.upbit.account_sync_service import (
            UpbitAccountSyncService,
        )

        return await UpbitAccountSyncService(
            session=session,
            private_client=build_upbit_private_client(),
            user_broker_account_id=uba_id,
        ).synchronize(user_broker_account_id=uba_id)

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        result = asyncio.run(_run())
        return {"broker_code": "UPBIT", "synced": True, "result": result}
    raise PostFillBrokerSyncError(
        "ASYNC_CONTEXT",
        "use sync_broker_snapshot_for_uba_async in async context",
    )
