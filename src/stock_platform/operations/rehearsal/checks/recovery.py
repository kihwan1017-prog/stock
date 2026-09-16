"""Recovery 리허설."""

from __future__ import annotations

from typing import Any

from stock_platform.operations.rehearsal.checks import run_check
from stock_platform.operations.rehearsal.models import (
    CheckResult,
    CheckStatus,
)


def run_recovery_checks() -> list[CheckResult]:
    results: list[CheckResult] = []

    def _service() -> tuple[CheckStatus, str, dict[str, Any]]:
        from stock_platform.broker.recovery_service import BrokerRecoveryService

        assert BrokerRecoveryService is not None
        return (
            CheckStatus.PASS,
            "BrokerRecoveryService available",
            {
                "sync_targets": [
                    "position",
                    "order",
                    "pending",
                    "settlement",
                    "scheduler",
                ],
            },
        )

    results.append(
        run_check(suite="recovery", name="service_surface", fn=_service)
    )

    def _paper_adapter() -> tuple[CheckStatus, str, dict[str, Any]]:
        from stock_platform.broker.recovery_adapters import paper as paper_adapters

        has_stock = hasattr(paper_adapters, "StockPaperRecoveryAdapter")
        has_crypto = hasattr(paper_adapters, "CryptoPaperRecoveryAdapter")
        status = (
            CheckStatus.PASS
            if has_stock or has_crypto
            else CheckStatus.WARNING
        )
        return (
            status,
            "paper recovery adapters",
            {"stock": has_stock, "crypto": has_crypto},
        )

    results.append(
        run_check(suite="recovery", name="paper_adapters", fn=_paper_adapter)
    )

    def _locks() -> tuple[CheckStatus, str, dict[str, Any]]:
        from stock_platform.broker.recovery_distributed_lock import (
            DistributedRecoveryLockManager,
        )

        assert DistributedRecoveryLockManager is not None
        return (
            CheckStatus.PASS,
            "distributed recovery lock available",
            {},
        )

    results.append(
        run_check(suite="recovery", name="distributed_lock", fn=_locks)
    )
    return results
