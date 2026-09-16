"""STEP 8-5-5 — account_strategy_link 기반 Runtime Bootstrap."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import structlog
from sqlalchemy import select

from stock_platform.broker.credential_vault_service import (
    BrokerCredentialVaultError,
    BrokerCredentialVaultService,
)
from stock_platform.broker.recovery_lock import RecoveryAccountLockService
from stock_platform.database.session import get_session_factory
from stock_platform.operation.audit_repository import AuditEventRepository
from stock_platform.risk_engine.kill_switch_service import KillSwitchService
from stock_platform.strategy_deployment.definition_entities import (
    AccountStrategyLinkEntity,
    StrategyDefinitionEntity,
)
from stock_platform.strategy_deployment.runtime_manager import (
    DynamicStrategyRuntimeManager,
    ScopedRuntimeEntry,
)
from stock_platform.strategy_deployment.runtime_scope import (
    AccountKind,
    RuntimeLifecycleStatus,
    StrategyRuntimeScope,
)
from stock_platform.trading.account_models import (
    PaperAccount,
    UserBrokerAccount,
)

logger = structlog.get_logger(__name__)


async def bootstrap_scoped_runtimes(
    manager: DynamicStrategyRuntimeManager,
) -> dict[str, Any]:
    """활성 계좌-전략 연결만 Scope Runtime으로 생성. 기본 KRX 단일 생성 없음."""

    session = get_session_factory()()
    created = 0
    paused = 0
    failed: list[dict[str, Any]] = []
    try:
        kill_active = False
        try:
            kill_active = bool(KillSwitchService(session).is_active())
        except Exception:  # noqa: BLE001
            kill_active = True

        links = list(
            session.scalars(
                select(AccountStrategyLinkEntity).where(
                    AccountStrategyLinkEntity.is_active.is_(True)
                )
            )
        )
        for link in links:
            try:
                scope, start = _build_scope_for_link(
                    session,
                    link,
                    kill_active=kill_active,
                )
                result = await manager.initialize_scoped(
                    scope, force=True, start=start
                )
                if result.scope_key and not start:
                    await manager.pause_runtime(
                        result.scope_key,
                        reason=_pause_reason_for_link(
                            session, link, kill_active=kill_active
                        ),
                    )
                    paused += 1
                else:
                    created += 1
                AuditEventRepository(session).create(
                    event_type="STRATEGY_RUNTIME_CREATED",
                    actor="system:startup",
                    request_id=None,
                    run_id=None,
                    strategy_id=str(scope.strategy_id),
                    account_hash=None,
                    order_id=None,
                    client_order_id=None,
                    symbol=None,
                    detail={
                        "scope_key": scope.scope_key,
                        **scope.masked_for_log(),
                        "started": start,
                        "deployment_id": result.current_deployment_id,
                    },
                    created_at=datetime.now(timezone.utc),
                )
                session.commit()
            except Exception as exc:  # noqa: BLE001
                session.rollback()
                failed.append(
                    {
                        "link_id": int(link.account_strategy_link_id),
                        "user_id": int(link.user_id),
                        "error": str(exc),
                    }
                )
                logger.warning(
                    "scoped_runtime_bootstrap_failed",
                    link_id=int(link.account_strategy_link_id),
                    error=str(exc),
                )
                try:
                    AuditEventRepository(session).create(
                        event_type="STRATEGY_RUNTIME_CREATE_FAILED",
                        actor="system:startup",
                        request_id=None,
                        run_id=None,
                        strategy_id=str(link.strategy_id),
                        account_hash=None,
                        order_id=None,
                        client_order_id=None,
                        symbol=None,
                        detail={
                            "link_id": int(
                                link.account_strategy_link_id
                            ),
                            "user_id": int(link.user_id),
                            "error": str(exc)[:500],
                        },
                        created_at=datetime.now(timezone.utc),
                    )
                    session.commit()
                except Exception:  # noqa: BLE001
                    session.rollback()

        # 링크가 없어도 전역 KRX Runtime은 만들지 않음
        return {
            "bootstrapped": True,
            "link_count": len(links),
            "created_running": created,
            "created_paused": paused,
            "failed": failed,
            "global_krx_runtime_created": False,
        }
    finally:
        session.close()


def _build_scope_for_link(
    session,
    link: AccountStrategyLinkEntity,
    *,
    kill_active: bool,
) -> tuple[StrategyRuntimeScope, bool]:
    definition = session.get(
        StrategyDefinitionEntity, int(link.strategy_id)
    )
    if definition is None or definition.deleted_at is not None:
        raise LookupError("Strategy definition missing")
    if not definition.is_active:
        raise LookupError("Strategy inactive")

    if link.paper_account_id is not None:
        paper = session.get(PaperAccount, int(link.paper_account_id))
        if paper is None or not paper.is_active or paper.deleted_at:
            raise LookupError("Paper account inactive")
        if int(paper.user_id or 0) != int(link.user_id):
            raise LookupError("Paper ownership mismatch")
        broker_code = "PAPER"
        account_kind = AccountKind.PAPER
        account_id = int(link.paper_account_id)
        market_code = (
            "UPBIT" if definition.market_type == "CRYPTO" else "KRX"
        )
    elif link.user_broker_account_id is not None:
        uba = session.get(
            UserBrokerAccount, int(link.user_broker_account_id)
        )
        if uba is None or not uba.is_active:
            raise LookupError("UBA inactive")
        if int(uba.user_id) != int(link.user_id):
            raise LookupError("UBA ownership mismatch")
        broker_code = uba.broker_code.upper()
        account_kind = AccountKind.USER_BROKER
        account_id = int(link.user_broker_account_id)
        market_code = broker_code
        # LIVE Credential 검증
        try:
            BrokerCredentialVaultService(
                session
            ).assert_live_order_allowed(
                account_id, broker_code=broker_code
            )
        except BrokerCredentialVaultError as exc:
            raise LookupError(f"credential:{exc.code}") from exc
    else:
        raise LookupError("Link has no account reference")

    version = (
        f"sid:{definition.strategy_id}:"
        f"{definition.updated_at.isoformat() if definition.updated_at else '1'}"
    )
    scope = StrategyRuntimeScope(
        user_id=int(link.user_id),
        account_kind=account_kind,
        account_id=account_id,
        strategy_id=int(definition.strategy_id),
        strategy_version=version,
        market_type=definition.market_type.upper(),
        broker_code=broker_code,
        strategy_code=definition.strategy_code,
        market_code=market_code,
    )

    start = True
    if kill_active:
        start = False
    else:
        reason = _pause_reason_for_link(
            session, link, kill_active=False
        )
        if reason:
            start = False
    return scope, start


def _pause_reason_for_link(
    session,
    link: AccountStrategyLinkEntity,
    *,
    kill_active: bool,
) -> str | None:
    if kill_active:
        return "kill_switch"
    if link.user_broker_account_id is not None:
        uba = session.get(
            UserBrokerAccount, int(link.user_broker_account_id)
        )
        broker = uba.broker_code.upper() if uba else "UPBIT"
        if RecoveryAccountLockService(session).is_trading_paused(
            user_broker_account_id=int(link.user_broker_account_id),
            broker_code=broker,
        ):
            return "recovery_paused"
    if link.paper_account_id is not None:
        if RecoveryAccountLockService(session).is_trading_paused(
            paper_account_id=int(link.paper_account_id),
            broker_code="PAPER",
        ):
            return "recovery_paused"
    return None


def create_paused_placeholder(
    scope: StrategyRuntimeScope,
    *,
    reason: str,
    strategy: object | None = None,
) -> ScopedRuntimeEntry:
    from stock_platform.strategy_deployment.runtime_models import (
        LoadedStrategyRuntime,
    )

    runtime = LoadedStrategyRuntime(
        deployment_id=0,
        strategy_code=scope.strategy_code or "UNKNOWN",
        market_code=scope.market_code or scope.market_type,
        symbol=None,
        parameter_payload={},
        loaded_at=datetime.now(timezone.utc),
        user_id=scope.user_id,
        account_id=scope.paper_account_id,
        user_broker_account_id=scope.user_broker_account_id,
        strategy_id=scope.strategy_id,
        strategy_version=scope.strategy_version,
        market_type=scope.market_type,
        scope_key=scope.scope_key,
        broker_code=scope.broker_code,
        account_kind=scope.account_kind.value,
    )
    return ScopedRuntimeEntry(
        scope=scope,
        runtime=runtime,
        strategy=strategy or object(),
        status=RuntimeLifecycleStatus.PAUSED,
        pause_reason=reason,
        last_paused_at=datetime.now(timezone.utc),
    )
