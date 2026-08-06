"""LIVE Smoke QUEUED — UBA-only 실 DB rollback (PaperAccount 치환 금지).

운영 코드 그대로 account_id=None + user_broker_account_id=UBA 로 INSERT.
실 Upbit 호출·UBA 1380·git push 금지.
"""

from __future__ import annotations

import uuid
from contextlib import ExitStack
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine, select, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

import stock_platform.auth.models  # noqa: F401
from stock_platform.common.settings import get_settings
from stock_platform.order.entities import TradingOrderEntity
from stock_platform.order.execution_service import OrderExecutionService
from stock_platform.order.outbox_entities import OrderOutbox
from stock_platform.risk.persistence_models import (  # noqa: F401
    PositionPlanEntity,
)
from stock_platform.strategy_deployment.definition_entities import (  # noqa: F401
    AccountStrategyLinkEntity,
    StrategyDefinitionEntity,
)
from stock_platform.strategy_deployment.entities import (  # noqa: F401
    StrategyDeploymentEntity,
)
from stock_platform.trading.account_masking import (
    hash_account_ref,
    mask_account_number,
)
from stock_platform.trading.account_models import UserBrokerAccount
from stock_platform.trading.live_validation_entities import LiveValidationRunEntity
from stock_platform.trading.upbit_live_smoke_constants import (
    CONFIRMATION_TEXT,
    LiveValidationRunStatus,
)
from stock_platform.trading.upbit_live_smoke_service import UpbitLiveSmokeService

pytestmark = pytest.mark.integration

_ALIAS_PREFIX = "UBA_OWN_"


def _engine_or_skip():
    engine = create_engine(get_settings().database_url, pool_pre_ping=True)
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
            nullable = conn.execute(
                text(
                    "SELECT is_nullable FROM information_schema.columns "
                    "WHERE table_schema='trading' AND table_name='trading_order' "
                    "AND column_name='account_id'"
                )
            ).scalar()
            if str(nullable).upper() != "YES":
                pytest.skip(
                    "trading_order.account_id 가 아직 NOT NULL — "
                    "j4k5l6m7n8o9 upgrade 필요"
                )
    except OperationalError as exc:
        pytest.skip(f"database unavailable: {exc}")
    return engine


def _preflight(*, user_id: int, uba_id: int) -> SimpleNamespace:
    pf = SimpleNamespace(
        live_execution_ready=True,
        blockers=[],
        live_blockers=[],
        quantity="0.001",
        limit_price="100",
        estimated_amount="5000",
        preflight_id=f"pf-uba-own-{uuid.uuid4().hex[:10]}",
        user_id=user_id,
        request_fingerprint=f"fp-{uuid.uuid4().hex[:12]}",
    )

    def to_dict() -> dict:
        return {
            "preflight_id": pf.preflight_id,
            "quantity": pf.quantity,
            "user_id": user_id,
            "user_broker_account_id": uba_id,
            "market": "KRW-BTC",
            "side": "BUY",
            "estimated_amount": pf.estimated_amount,
            "limit_price": pf.limit_price,
            "request_fingerprint": pf.request_fingerprint,
        }

    pf.to_dict = to_dict  # type: ignore[method-assign]
    return pf


def _enter_mocks(stack: ExitStack, *, pf: SimpleNamespace):
    counters = {"create_order": 0, "http_orders": 0}

    def spy_create_order(*_a, **_k):
        counters["create_order"] += 1
        raise AssertionError("Adapter create_order must not be called")

    def spy_http(*_a, **_k):
        counters["http_orders"] += 1
        raise AssertionError("HTTP /v1/orders must not be called")

    PF = stack.enter_context(
        patch(
            "stock_platform.trading.upbit_live_smoke_service.UpbitLivePreflightService"
        )
    )
    Track = stack.enter_context(
        patch(
            "stock_platform.trading.upbit_live_tracking_service.UpbitLiveTrackingService"
        )
    )
    stack.enter_context(
        patch(
            "stock_platform.trading.upbit_live_smoke_service.emit_live_order_telegram"
        )
    )
    stack.enter_context(
        patch("stock_platform.trading.upbit_live_smoke_service.LiveArmService")
    )
    stack.enter_context(patch.object(UpbitLiveSmokeService, "_pause_uba_scope"))
    stack.enter_context(
        patch.object(
            UpbitLiveSmokeService,
            "_watch_and_maybe_cancel",
            return_value={
                "watch_seconds": 0,
                "auto_cancel": False,
                "internal_status": LiveValidationRunStatus.QUEUED.value,
                "broker_order_status": "NOT_SUBMITTED",
            },
        )
    )
    Safety = stack.enter_context(
        patch(
            "stock_platform.order.live_safety_pipeline.LiveOrderSafetyPipeline"
        )
    )
    stack.enter_context(
        patch(
            "stock_platform.operation.live_health_gate.assert_live_orders_allowed"
        )
    )
    KS = stack.enter_context(
        patch(
            "stock_platform.order.execution_service.PersistentKillSwitchGuard"
        )
    )
    Lock = stack.enter_context(
        patch(
            "stock_platform.broker.recovery_lock.RecoveryAccountLockService"
        )
    )
    Vault = stack.enter_context(
        patch(
            "stock_platform.broker.credential_vault_service.BrokerCredentialVaultService"
        )
    )
    Risk = stack.enter_context(
        patch(
            "stock_platform.order.execution_service.DatabaseBackedRiskOrderGuard"
        )
    )
    stack.enter_context(
        patch(
            "stock_platform.order.live_dry_run.is_live_dry_run_mode",
            return_value=False,
        )
    )
    stack.enter_context(
        patch(
            "stock_platform.order.live_shadow.is_live_shadow_mode",
            return_value=False,
        )
    )
    stack.enter_context(
        patch(
            "stock_platform.broker.upbit.order_client.UpbitOrderRestClient.create_order",
            side_effect=spy_create_order,
        )
    )
    stack.enter_context(
        patch(
            "stock_platform.broker.upbit.adapter.UpbitBrokerAdapter.submit_order",
            side_effect=spy_http,
        )
    )

    PF.return_value.run.return_value = pf
    Track.return_value.blocks_new_order.return_value = False
    Track.return_value.attach_after_execution = MagicMock()
    Safety.return_value.evaluate.return_value = SimpleNamespace(
        allowed=True, reason_code="LIVE_SAFETY_PASS"
    )
    Safety.return_value.notify_submitted = MagicMock()
    KS.return_value.require_order_allowed = MagicMock()
    Lock.return_value.is_trading_paused.return_value = False
    Vault.return_value.assert_live_order_allowed = MagicMock()
    Risk.return_value.check.return_value = SimpleNamespace(
        allowed=True, blocked_reason=None
    )
    return counters


@pytest.mark.integration
def test_live_smoke_uba_only_queue_insert_rollback() -> None:
    engine = _engine_or_skip()
    connection = engine.connect()
    outer = connection.begin()
    session: Session = sessionmaker(
        bind=connection,
        autoflush=False,
        autocommit=False,
        join_transaction_mode="create_savepoint",
    )()

    marker = uuid.uuid4().hex[:12]
    alias = f"{_ALIAS_PREFIX}{marker}"
    account_number = f"9{uuid.uuid4().hex[:11]}"
    created_run_id = None
    created_order_id = None
    created_outbox_id = None

    try:
        user_id = session.execute(
            text("SELECT user_id FROM auth.user ORDER BY user_id LIMIT 1")
        ).scalar()
        if user_id is None:
            pytest.skip("auth.user 없음")
        user_id = int(user_id)

        # PaperAccount 생성하지 않음 — UBA fixture 만
        uba = UserBrokerAccount(
            user_id=user_id,
            broker_code="UPBIT",
            account_alias=alias,
            account_ref_hash=hash_account_ref(account_number),
            masked_account_number=mask_account_number(account_number),
            currency_code="KRW",
            is_default=False,
            is_active=True,
            live_order_enabled=True,
            live_armed=True,
            connection_status="CONNECTED",
        )
        session.add(uba)
        session.flush()
        uba_id = int(uba.user_broker_account_id)
        assert uba_id != 1380

        pf = _preflight(user_id=user_id, uba_id=uba_id)

        with ExitStack() as stack:
            counters = _enter_mocks(stack, pf=pf)
            # monkeypatch 로 account_id 치환 금지 — 실 OES.submit 사용
            result = UpbitLiveSmokeService(session).execute(
                user_broker_account_id=uba_id,
                market="KRW-BTC",
                side="BUY",
                amount=Decimal("5000"),
                limit_price=Decimal("100"),
                actor="uba-ownership-test",
                arm_token="tok-uba-own",
                execute_live=True,
                confirmation_text=CONFIRMATION_TEXT,
                skip_live_network=True,
            )

            assert result["status"] == LiveValidationRunStatus.QUEUED.value
            assert result["reason_code"] == "QUEUED"
            created_run_id = str(result["run_id"])
            created_order_id = int(result["order_id"])
            created_outbox_id = int(result["outbox_id"])

            run_row = session.scalar(
                select(LiveValidationRunEntity).where(
                    LiveValidationRunEntity.run_id == created_run_id
                )
            )
            assert run_row is not None
            assert int(run_row.user_broker_account_id) == uba_id
            assert run_row.status_code == LiveValidationRunStatus.QUEUED.value

            order_row = session.get(TradingOrderEntity, created_order_id)
            assert order_row is not None
            assert order_row.account_id is None
            assert int(order_row.user_broker_account_id or 0) == uba_id

            outbox_row = session.get(OrderOutbox, created_outbox_id)
            assert outbox_row is not None
            assert int(outbox_row.order_id) == created_order_id
            assert int(outbox_row.user_broker_account_id or 0) == uba_id
            payload = outbox_row.payload_json or {}
            assert payload.get("account_id") in (None, "")
            assert int(payload.get("user_broker_account_id") or 0) == uba_id

            assert counters["create_order"] == 0
            assert counters["http_orders"] == 0
            session.execute(text("SELECT 1")).scalar()
    finally:
        session.close()
        outer.rollback()
        connection.close()

    with engine.connect() as verify:
        assert (
            int(
                verify.execute(
                    text(
                        "SELECT COUNT(*) FROM trading.live_validation_run "
                        "WHERE run_id=:r"
                    ),
                    {"r": created_run_id},
                ).scalar()
                or 0
            )
            == 0
        )
        assert (
            int(
                verify.execute(
                    text(
                        "SELECT COUNT(*) FROM trading.trading_order "
                        "WHERE order_id=:o"
                    ),
                    {"o": created_order_id},
                ).scalar()
                or 0
            )
            == 0
        )
        assert (
            int(
                verify.execute(
                    text(
                        "SELECT COUNT(*) FROM trading.order_outbox "
                        "WHERE outbox_id=:x"
                    ),
                    {"x": created_outbox_id},
                ).scalar()
                or 0
            )
            == 0
        )
        assert (
            int(
                verify.execute(
                    text(
                        "SELECT COUNT(*) FROM trading.user_broker_account "
                        "WHERE account_alias=:a"
                    ),
                    {"a": alias},
                ).scalar()
                or 0
            )
            == 0
        )


def test_resolve_account_ownership_xor() -> None:
    resolve = OrderExecutionService._resolve_account_ownership
    assert resolve(account_id=10, user_broker_account_id=None) == (10, None)
    assert resolve(account_id=999, user_broker_account_id=55) == (None, 55)
    assert resolve(account_id=None, user_broker_account_id=55) == (None, 55)
    with pytest.raises(ValueError, match="PAPER_ACCOUNT_REQUIRED"):
        resolve(account_id=None, user_broker_account_id=None)
