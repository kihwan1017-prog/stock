"""credential resolve hang 회귀: last_used touch lock / feed touch=False."""

from __future__ import annotations

import ast
import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from stock_platform.broker.credential_adapter_factory import resolve_uba_credential
from stock_platform.broker.credential_vault_service import (
    BrokerCredentialVaultService,
)
from stock_platform.realtime.kiwoom_market_realtime_runtime import (
    KiwoomMarketRealtimeRuntime,
)


def test_modules_compile_credential_hang_fix() -> None:
    root = Path(__file__).resolve().parents[1] / "src" / "stock_platform"
    for rel in (
        "broker/credential_vault_service.py",
        "broker/credential_adapter_factory.py",
        "realtime/kiwoom_market_realtime_runtime.py",
    ):
        path = root / rel
        ast.parse(path.read_text(encoding="utf-8"))


def test_resolve_uba_credential_forwards_touch_last_used_false() -> None:
    session = MagicMock()
    with patch(
        "stock_platform.broker.credential_adapter_factory.BrokerCredentialVaultService"
    ) as vault_cls:
        svc = vault_cls.return_value
        svc.resolve_for_runtime.return_value = MagicMock()
        resolve_uba_credential(
            session,
            1381,
            expected_broker="KIWOOM",
            touch_last_used=False,
        )
        kwargs = svc.resolve_for_runtime.call_args.kwargs
        assert kwargs["touch_last_used"] is False
        assert kwargs["expected_broker"] == "KIWOOM"


def test_touch_last_used_uses_separate_session_with_lock_timeout() -> None:
    """호출자 세션 flush 대신 별도 short txn + lock_timeout."""

    caller = MagicMock()
    bind = MagicMock()
    caller.get_bind.return_value = bind
    touch = MagicMock()

    with patch(
        "stock_platform.broker.credential_vault_service.Session",
        return_value=touch,
    ) as session_ctor:
        svc = BrokerCredentialVaultService(caller)
        svc._touch_last_used_best_effort(42)

    session_ctor.assert_called_once_with(bind=bind)
    executed_sql = [
        str(call.args[0])
        for call in touch.execute.call_args_list
        if call.args
    ]
    assert any("lock_timeout" in sql for sql in executed_sql)
    touch.commit.assert_called_once()
    touch.close.assert_called_once()
    # 호출자 세션에는 flush/commit 없음
    caller.flush.assert_not_called()


def test_touch_last_used_lock_timeout_is_swallowed() -> None:
    caller = MagicMock()
    caller.get_bind.return_value = MagicMock()
    touch = MagicMock()
    touch.execute.side_effect = Exception("lock timeout")

    with patch(
        "stock_platform.broker.credential_vault_service.Session",
        return_value=touch,
    ):
        BrokerCredentialVaultService(caller)._touch_last_used_best_effort(7)

    touch.rollback.assert_called_once()
    touch.close.assert_called_once()


@pytest.mark.asyncio
async def test_feed_start_resolves_without_touch_last_used() -> None:
    """시세 feed start는 credential row write-lock을 잡지 않는다."""

    runtime = KiwoomMarketRealtimeRuntime()
    session = MagicMock()
    factory = MagicMock(return_value=session)
    order_cfg = SimpleNamespace(use_mock=False)
    fake_client = MagicMock()
    fake_client.subscribe_symbols = MagicMock()
    fake_client.run_forever = AsyncMock(side_effect=asyncio.Event().wait)
    fake_client.shutdown = AsyncMock()
    fake_client.status = MagicMock(
        return_value={
            "connected": True,
            "event_count": 1,
            "last_event_at": "2026-08-25T02:00:00+00:00",
            "environment": "REAL",
        }
    )
    resolve_mock = MagicMock(
        return_value=SimpleNamespace(
            credential_id=1,
            broker_code="KIWOOM",
            payload={},
        )
    )

    with (
        patch(
            "stock_platform.realtime.kiwoom_market_realtime_runtime.get_settings",
            return_value=SimpleNamespace(
                kiwoom_market_data_is_mock=False,
                kiwoom_market_data_use_mock=False,
                kiwoom_use_mock=True,
                kiwoom_market_realtime_auto_start=False,
            ),
        ),
        patch(
            "stock_platform.database.session.get_session_factory",
            return_value=factory,
        ),
        patch(
            "stock_platform.broker.credential_adapter_factory.resolve_uba_credential",
            resolve_mock,
        ),
        patch(
            "stock_platform.broker.credential_adapter_factory.build_kiwoom_order_config_from_vault",
            return_value=order_cfg,
        ),
        patch("stock_platform.broker.kiwoom.token_client.KiwoomTokenClient"),
        patch("stock_platform.broker.kiwoom.token_cache.KiwoomTokenCache"),
        patch(
            "stock_platform.realtime.kiwoom_market_realtime_runtime.KiwoomMarketRealtimeClient",
            return_value=fake_client,
        ),
    ):
        out = await runtime.start(
            user_broker_account_id=1381,
            symbols=["034310"],
            require_real=True,
        )
        assert out["started"] is True
        assert resolve_mock.call_args.kwargs.get("touch_last_used") is False
        await runtime.stop()
