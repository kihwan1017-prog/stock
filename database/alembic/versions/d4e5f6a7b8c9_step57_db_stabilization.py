"""STEP57 DB stabilization: schemas, FKs, indexes, comments

Revision ID: d4e5f6a7b8c9
Revises: c2d3e4f5a6b7
Create Date: 2026-07-20
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op


revision: str = "d4e5f6a7b8c9"
down_revision: Union[str, Sequence[str], None] = "c2d3e4f5a6b7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SCHEMAS = (
    "auth",
    "market",
    "trading",
    "strategy",
    "operation",
    "news",
    "disclosure",
    "ai",
    "backtest",
    "broker",
    "common",
)


def upgrade() -> None:
    # 1) 스키마 생성 순서 보장 (그린필드 / no-op revision 보완)
    for schema_name in _SCHEMAS:
        op.execute(
            f"CREATE SCHEMA IF NOT EXISTS {schema_name}"
        )

    # 2) 고아 정리 (FK 추가 전 — 현재 0건 예상, 방어적)
    op.execute(
        """
        DELETE FROM trading.trading_order_status_history h
        WHERE NOT EXISTS (
            SELECT 1 FROM trading.trading_order o
            WHERE o.order_id = h.order_id
        )
        """
    )
    op.execute(
        """
        DELETE FROM trading.strategy_deployment_history h
        WHERE NOT EXISTS (
            SELECT 1 FROM trading.strategy_deployment d
            WHERE d.strategy_deployment_id = h.strategy_deployment_id
        )
        """
    )
    op.execute(
        """
        DELETE FROM trading.strategy_deployment_performance p
        WHERE NOT EXISTS (
            SELECT 1 FROM trading.strategy_deployment d
            WHERE d.strategy_deployment_id = p.strategy_deployment_id
        )
        """
    )
    op.execute(
        """
        UPDATE strategy.position_plan p
        SET policy_id = NULL
        WHERE policy_id IS NOT NULL
          AND NOT EXISTS (
            SELECT 1 FROM strategy.risk_policy r
            WHERE r.policy_id = p.policy_id
          )
        """
    )
    op.execute(
        """
        DELETE FROM operation.broker_recovery_step s
        WHERE NOT EXISTS (
            SELECT 1 FROM operation.broker_recovery_run r
            WHERE r.broker_recovery_run_id = s.broker_recovery_run_id
        )
        """
    )
    op.execute(
        """
        UPDATE trading.trading_order o
        SET strategy_deployment_id = NULL
        WHERE strategy_deployment_id IS NOT NULL
          AND NOT EXISTS (
            SELECT 1 FROM trading.strategy_deployment d
            WHERE d.strategy_deployment_id = o.strategy_deployment_id
          )
        """
    )

    # 3) Foreign Keys (존재하지 않을 때만)
    op.execute(
        """
        DO $$
        BEGIN
          IF NOT EXISTS (
            SELECT 1 FROM pg_constraint
            WHERE conname = 'fk_order_status_history_order'
          ) THEN
            ALTER TABLE trading.trading_order_status_history
              ADD CONSTRAINT fk_order_status_history_order
              FOREIGN KEY (order_id)
              REFERENCES trading.trading_order(order_id)
              ON DELETE CASCADE;
          END IF;

          IF NOT EXISTS (
            SELECT 1 FROM pg_constraint
            WHERE conname = 'fk_strategy_deployment_history_deployment'
          ) THEN
            ALTER TABLE trading.strategy_deployment_history
              ADD CONSTRAINT fk_strategy_deployment_history_deployment
              FOREIGN KEY (strategy_deployment_id)
              REFERENCES trading.strategy_deployment(strategy_deployment_id)
              ON DELETE CASCADE;
          END IF;

          IF NOT EXISTS (
            SELECT 1 FROM pg_constraint
            WHERE conname = 'fk_strategy_deployment_performance_deployment'
          ) THEN
            ALTER TABLE trading.strategy_deployment_performance
              ADD CONSTRAINT fk_strategy_deployment_performance_deployment
              FOREIGN KEY (strategy_deployment_id)
              REFERENCES trading.strategy_deployment(strategy_deployment_id)
              ON DELETE CASCADE;
          END IF;

          IF NOT EXISTS (
            SELECT 1 FROM pg_constraint
            WHERE conname = 'fk_position_plan_policy'
          ) THEN
            ALTER TABLE strategy.position_plan
              ADD CONSTRAINT fk_position_plan_policy
              FOREIGN KEY (policy_id)
              REFERENCES strategy.risk_policy(policy_id)
              ON DELETE SET NULL;
          END IF;

          IF NOT EXISTS (
            SELECT 1 FROM pg_constraint
            WHERE conname = 'fk_broker_recovery_step_run'
          ) THEN
            ALTER TABLE operation.broker_recovery_step
              ADD CONSTRAINT fk_broker_recovery_step_run
              FOREIGN KEY (broker_recovery_run_id)
              REFERENCES operation.broker_recovery_run(broker_recovery_run_id)
              ON DELETE CASCADE;
          END IF;

          IF NOT EXISTS (
            SELECT 1 FROM pg_constraint
            WHERE conname = 'fk_trading_order_strategy_deployment'
          ) THEN
            ALTER TABLE trading.trading_order
              ADD CONSTRAINT fk_trading_order_strategy_deployment
              FOREIGN KEY (strategy_deployment_id)
              REFERENCES trading.strategy_deployment(strategy_deployment_id)
              ON DELETE SET NULL;
          END IF;
        END $$;
        """
    )

    # 4) Indexes (조회·정렬 빈번 경로)
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS ix_paper_order_status_created
          ON trading.paper_order (status_code, created_at DESC);
        CREATE INDEX IF NOT EXISTS ix_paper_order_symbol_created
          ON trading.paper_order (exchange_code, symbol, created_at DESC);
        CREATE INDEX IF NOT EXISTS ix_paper_trade_account_traded
          ON trading.paper_trade (account_id, traded_at DESC);
        CREATE INDEX IF NOT EXISTS ix_trading_order_deployment
          ON trading.trading_order (strategy_deployment_id)
          WHERE strategy_deployment_id IS NOT NULL;
        CREATE INDEX IF NOT EXISTS ix_job_run_history_name_started
          ON operation.job_run_history (job_name, started_at DESC);
        CREATE INDEX IF NOT EXISTS ix_job_run_history_status_started
          ON operation.job_run_history (status_code, started_at DESC);
        CREATE INDEX IF NOT EXISTS ix_broker_recovery_run_status_started
          ON operation.broker_recovery_run (status_code, started_at DESC);
        CREATE INDEX IF NOT EXISTS ix_broker_account_snapshot_broker
          ON trading.broker_account_snapshot (broker_code);
        CREATE INDEX IF NOT EXISTS ix_risk_event_created
          ON operation.risk_event (created_at DESC);
        CREATE INDEX IF NOT EXISTS ix_strategy_deployment_history_dep
          ON trading.strategy_deployment_history (strategy_deployment_id, created_at DESC);
        """
    )

    # 5) Table comments (운영자 가독성)
    op.execute(
        """
        COMMENT ON SCHEMA auth IS '인증·RBAC 사용자/역할';
        COMMENT ON SCHEMA market IS '종목·시세·캔들·지표';
        COMMENT ON SCHEMA trading IS '주문·체결·Paper·전략배포·브로커스냅샷';
        COMMENT ON SCHEMA strategy IS '스크리닝·리스크정책·포지션계획';
        COMMENT ON SCHEMA operation IS '감사·잡·파이프라인·킬스위치·설정';
        COMMENT ON SCHEMA news IS '뉴스 수집·요약';
        COMMENT ON SCHEMA disclosure IS '공시(DART)';
        COMMENT ON SCHEMA ai IS 'AI 분석·전략선정';
        COMMENT ON SCHEMA backtest IS '백테스트 결과';

        COMMENT ON TABLE trading.trading_order IS '실거래/공용 주문 원장';
        COMMENT ON TABLE trading.trading_order_status_history IS '주문 상태 전이 이력';
        COMMENT ON TABLE trading.execution IS '주문 체결 이벤트';
        COMMENT ON TABLE trading.order_outbox IS '주문 송신 Outbox (멱등)';
        COMMENT ON TABLE trading.paper_account IS '모의투자 계좌';
        COMMENT ON TABLE trading.paper_position IS '모의 보유 포지션';
        COMMENT ON TABLE trading.paper_order IS '모의 주문';
        COMMENT ON TABLE trading.paper_trade IS '모의 체결 원장';
        COMMENT ON TABLE trading.strategy_deployment IS '전략 배포 활성 단위';
        COMMENT ON TABLE trading.broker_account_snapshot IS '브로커 계좌 최신 스냅샷';
        COMMENT ON TABLE operation.audit_event IS '운영 감사 로그';
        COMMENT ON TABLE operation.job_run_history IS '스케줄/배치 실행 이력';
        COMMENT ON TABLE operation.kill_switch IS '전역 Kill Switch 상태';
        COMMENT ON TABLE strategy.risk_policy IS '포지션 사이징·손절익절 정책';
        COMMENT ON TABLE strategy.position_plan IS '주문 전 포지션 계획 이력';
        COMMENT ON TABLE auth."user" IS '로그인 사용자';
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE trading.trading_order
          DROP CONSTRAINT IF EXISTS fk_trading_order_strategy_deployment;
        ALTER TABLE operation.broker_recovery_step
          DROP CONSTRAINT IF EXISTS fk_broker_recovery_step_run;
        ALTER TABLE strategy.position_plan
          DROP CONSTRAINT IF EXISTS fk_position_plan_policy;
        ALTER TABLE trading.strategy_deployment_performance
          DROP CONSTRAINT IF EXISTS fk_strategy_deployment_performance_deployment;
        ALTER TABLE trading.strategy_deployment_history
          DROP CONSTRAINT IF EXISTS fk_strategy_deployment_history_deployment;
        ALTER TABLE trading.trading_order_status_history
          DROP CONSTRAINT IF EXISTS fk_order_status_history_order;

        DROP INDEX IF EXISTS trading.ix_paper_order_status_created;
        DROP INDEX IF EXISTS trading.ix_paper_order_symbol_created;
        DROP INDEX IF EXISTS trading.ix_paper_trade_account_traded;
        DROP INDEX IF EXISTS trading.ix_trading_order_deployment;
        DROP INDEX IF EXISTS operation.ix_job_run_history_name_started;
        DROP INDEX IF EXISTS operation.ix_job_run_history_status_started;
        DROP INDEX IF EXISTS operation.ix_broker_recovery_run_status_started;
        DROP INDEX IF EXISTS trading.ix_broker_account_snapshot_broker;
        DROP INDEX IF EXISTS operation.ix_risk_event_created;
        DROP INDEX IF EXISTS trading.ix_strategy_deployment_history_dep;
        """
    )
