"""STEP 8-5-5 — Active deployment → Scope Runtime 로더."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from stock_platform.strategy_deployment.models import (
    StrategyDeploymentMode,
)
from stock_platform.strategy_deployment.registry import (
    StrategyFactoryRegistry,
)
from stock_platform.strategy_deployment.repository import (
    StrategyDeploymentRepository,
)
from stock_platform.strategy_deployment.runtime_models import (
    LoadedStrategyRuntime,
    build_runtime_scope_key,
)
from stock_platform.strategy_deployment.symbol_payload import (
    symbols_from_parameter_payload,
)


def _resolve_runtime_payload_and_symbol(
    session: Session,
    deployment,
    definition,
) -> tuple[dict, str | None]:
    """Deployment row가 비어 있어도 Definition/대표 Backtest에서 실행 payload·symbol을 복원."""

    payload = dict(getattr(deployment, "parameter_payload", None) or {})
    if not payload and definition is not None:
        payload = dict(definition.parameter_payload or {})

    symbol = str(getattr(deployment, "symbol", None) or "").strip().upper() or None
    if not symbol:
        symbols = symbols_from_parameter_payload(payload)
        if symbols:
            symbol = symbols[0]

    if not symbol and definition is not None:
        from stock_platform.ai.strategy_draft_approval.backtest_execution import (
            get_latest_primary_backtest_run_id,
        )
        from stock_platform.backtest.persistence_models import BacktestRunEntity

        run_id = get_latest_primary_backtest_run_id(session, int(definition.strategy_id))
        if run_id is not None:
            run = session.get(BacktestRunEntity, int(run_id))
            if run is not None and run.symbol:
                symbol = str(run.symbol).strip().upper()

    if symbol and not payload.get("symbol"):
        payload = dict(payload)
        payload["symbol"] = symbol

    return payload, symbol


class ActiveStrategyRuntimeLoader:
    def __init__(
        self,
        *,
        session: Session,
        registry: StrategyFactoryRegistry,
    ) -> None:
        self._repository = StrategyDeploymentRepository(session)
        self._registry = registry
        self._session = session

    def load(
        self,
        *,
        market_code: str,
        symbol: str | None,
        mode: StrategyDeploymentMode = StrategyDeploymentMode.PAPER,
        user_id: int | None = None,
        account_id: int | None = None,
        user_broker_account_id: int | None = None,
        strategy_id: int | None = None,
    ) -> tuple[LoadedStrategyRuntime, object]:
        deployment = None
        if user_id is not None and hasattr(
            self._repository, "get_active_for_user"
        ):
            deployment = self._repository.get_active_for_user(
                market_code=market_code,
                symbol=symbol,
                mode_code=mode.value,
                user_id=user_id,
            )
            # strategy_id가 지정되면 일치하는 배포만 허용
            if (
                deployment is not None
                and strategy_id is not None
                and getattr(deployment, "strategy_id", None) is not None
                and int(deployment.strategy_id) != int(strategy_id)
            ):
                deployment = None

        if deployment is None:
            deployment = self._repository.get_active(
                market_code=market_code,
                symbol=symbol,
                mode_code=mode.value,
            )
            if (
                deployment is not None
                and strategy_id is not None
                and getattr(deployment, "strategy_id", None) is not None
                and int(deployment.strategy_id) != int(strategy_id)
            ):
                # SYSTEM 공용 활성 배포가 다른 전략이면 strategy_id 기준 재검색
                deployment = self._find_active_by_strategy(
                    strategy_id=int(strategy_id),
                    mode_code=mode.value,
                    user_id=user_id,
                )

        if deployment is None and strategy_id is not None:
            deployment = self._find_active_by_strategy(
                strategy_id=int(strategy_id),
                mode_code=mode.value,
                user_id=user_id,
            )

        if deployment is None:
            raise LookupError("Active strategy deployment not found")

        dep_user_id = getattr(deployment, "user_id", None)
        if (
            user_id is not None
            and dep_user_id is not None
            and int(dep_user_id) != int(user_id)
        ):
            raise LookupError("Deployment ownership mismatch")

        dep_strategy_id = getattr(deployment, "strategy_id", None)
        market_type = None
        strategy_version = f"dep:{deployment.strategy_deployment_id}"
        definition = None
        if dep_strategy_id is not None:
            from stock_platform.strategy_deployment.definition_entities import (
                StrategyDefinitionEntity,
            )

            definition = self._session.get(
                StrategyDefinitionEntity, int(dep_strategy_id)
            )
            if definition is not None:
                market_type = definition.market_type
                strategy_version = (
                    f"sid:{definition.strategy_id}:"
                    f"{definition.updated_at.isoformat() if definition.updated_at else '1'}"
                )

        resolved_payload, resolved_symbol = _resolve_runtime_payload_and_symbol(
            self._session, deployment, definition
        )
        strategy = self._registry.create(
            strategy_code=deployment.strategy_code,
            parameter_payload=resolved_payload,
        )

        resolved_user = (
            int(user_id)
            if user_id is not None
            else (int(dep_user_id) if dep_user_id is not None else None)
        )
        scope_key = build_runtime_scope_key(
            user_id=resolved_user,
            account_id=account_id,
            user_broker_account_id=user_broker_account_id,
            strategy_id=(
                int(dep_strategy_id)
                if dep_strategy_id is not None
                else strategy_id
            ),
            strategy_code=deployment.strategy_code,
            market_code=deployment.market_code,
            market_type=market_type,
            strategy_version=strategy_version,
            broker_code=(
                "PAPER"
                if mode == StrategyDeploymentMode.PAPER
                else None
            ),
        )

        runtime = LoadedStrategyRuntime(
            deployment_id=deployment.strategy_deployment_id,
            strategy_code=deployment.strategy_code,
            market_code=deployment.market_code,
            symbol=resolved_symbol or deployment.symbol,
            parameter_payload=resolved_payload,
            loaded_at=datetime.now(timezone.utc),
            user_id=resolved_user,
            account_id=account_id,
            user_broker_account_id=user_broker_account_id,
            strategy_id=(
                int(dep_strategy_id)
                if dep_strategy_id is not None
                else strategy_id
            ),
            strategy_version=strategy_version,
            market_type=market_type,
            scope_key=scope_key,
        )
        return runtime, strategy

    def _find_active_by_strategy(
        self,
        *,
        strategy_id: int,
        mode_code: str,
        user_id: int | None,
    ):
        from sqlalchemy import select

        from stock_platform.strategy_deployment.entities import (
            StrategyDeploymentEntity,
        )

        stmt = select(StrategyDeploymentEntity).where(
            StrategyDeploymentEntity.strategy_id == int(strategy_id),
            StrategyDeploymentEntity.status_code == "ACTIVE",
            StrategyDeploymentEntity.mode_code == mode_code.upper(),
        )
        if user_id is not None:
            stmt = stmt.where(
                (StrategyDeploymentEntity.user_id == int(user_id))
                | (StrategyDeploymentEntity.user_id.is_(None))
            )
        stmt = stmt.order_by(
            StrategyDeploymentEntity.strategy_deployment_id.desc()
        ).limit(1)
        return self._session.scalar(stmt)
