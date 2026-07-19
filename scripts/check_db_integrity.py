"""STEP57 — DB 무결성 점검 (고아 FK · NULL 이상 · 중복).

사용:
  python scripts/check_db_integrity.py
"""

from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy import create_engine, text

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_PATH = PROJECT_ROOT / "src"
if str(SRC_PATH) not in sys.path:
    sys.path.insert(0, str(SRC_PATH))

from stock_platform.common.settings import get_settings


# (설명, SQL) — 결과가 0이어야 통과
_ORPHAN_CHECKS: list[tuple[str, str]] = [
    (
        "trading_order_status_history orphans",
        """
        SELECT COUNT(*) AS cnt
        FROM trading.trading_order_status_history h
        WHERE NOT EXISTS (
            SELECT 1 FROM trading.trading_order o WHERE o.order_id = h.order_id
        )
        """,
    ),
    (
        "strategy_deployment_history orphans",
        """
        SELECT COUNT(*) AS cnt
        FROM trading.strategy_deployment_history h
        WHERE NOT EXISTS (
            SELECT 1 FROM trading.strategy_deployment d
            WHERE d.strategy_deployment_id = h.strategy_deployment_id
        )
        """,
    ),
    (
        "strategy_deployment_performance orphans",
        """
        SELECT COUNT(*) AS cnt
        FROM trading.strategy_deployment_performance p
        WHERE NOT EXISTS (
            SELECT 1 FROM trading.strategy_deployment d
            WHERE d.strategy_deployment_id = p.strategy_deployment_id
        )
        """,
    ),
    (
        "broker_recovery_step orphans",
        """
        SELECT COUNT(*) AS cnt
        FROM operation.broker_recovery_step s
        WHERE NOT EXISTS (
            SELECT 1 FROM operation.broker_recovery_run r
            WHERE r.broker_recovery_run_id = s.broker_recovery_run_id
        )
        """,
    ),
    (
        "execution orphans",
        """
        SELECT COUNT(*) AS cnt
        FROM trading.execution e
        WHERE NOT EXISTS (
            SELECT 1 FROM trading.trading_order o WHERE o.order_id = e.order_id
        )
        """,
    ),
    (
        "order_outbox orphans",
        """
        SELECT COUNT(*) AS cnt
        FROM trading.order_outbox x
        WHERE NOT EXISTS (
            SELECT 1 FROM trading.trading_order o WHERE o.order_id = x.order_id
        )
        """,
    ),
    (
        "paper_position orphans",
        """
        SELECT COUNT(*) AS cnt
        FROM trading.paper_position p
        WHERE NOT EXISTS (
            SELECT 1 FROM trading.paper_account a WHERE a.account_id = p.account_id
        )
        """,
    ),
    (
        "duplicate client_order_id",
        """
        SELECT COUNT(*) AS cnt FROM (
            SELECT client_order_id
            FROM trading.trading_order
            GROUP BY client_order_id
            HAVING COUNT(*) > 1
        ) d
        """,
    ),
]


def main() -> int:
    settings = get_settings()
    engine = create_engine(settings.database_url)
    failures: list[str] = []

    with engine.connect() as conn:
        for label, sql in _ORPHAN_CHECKS:
            count = int(conn.execute(text(sql)).scalar_one())
            status = "OK" if count == 0 else "FAIL"
            print(f"[{status}] {label}: {count}")
            if count != 0:
                failures.append(label)

        # FK 제약 존재 여부 (STEP57 핵심)
        fk_names = (
            "fk_order_status_history_order",
            "fk_strategy_deployment_history_deployment",
            "fk_strategy_deployment_performance_deployment",
            "fk_position_plan_policy",
            "fk_broker_recovery_step_run",
            "fk_trading_order_strategy_deployment",
        )
        for fk_name in fk_names:
            exists = conn.execute(
                text(
                    """
                    SELECT EXISTS (
                        SELECT 1 FROM pg_constraint WHERE conname = :name
                    )
                    """
                ),
                {"name": fk_name},
            ).scalar_one()
            status = "OK" if exists else "FAIL"
            print(f"[{status}] constraint {fk_name}")
            if not exists:
                failures.append(fk_name)

    if failures:
        print(f"\nIntegrity check FAILED: {len(failures)} issue(s)")
        return 1

    print("\nIntegrity check PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
