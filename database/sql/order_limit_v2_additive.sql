-- ORDER_LIMIT_V2 additive DDL (idempotent)
-- Alembic cycle 회피: 운영 DB 직접 적용. 그래프에 revision join 금지.

CREATE TABLE IF NOT EXISTS operation.strategy_daily_order_usage (
    strategy_daily_order_usage_id BIGSERIAL PRIMARY KEY,
    trading_date DATE NOT NULL,
    broker_code VARCHAR(30) NOT NULL,
    user_broker_account_id BIGINT NOT NULL,
    strategy_id BIGINT NOT NULL,
    deployment_id BIGINT NOT NULL DEFAULT 0,
    submit_count INTEGER NOT NULL DEFAULT 0,
    filled_entry_count INTEGER NOT NULL DEFAULT 0,
    filled_entry_order_ids JSONB NOT NULL DEFAULT '[]'::jsonb,
    policy_version VARCHAR(64) NOT NULL DEFAULT 'ORDER_LIMIT_V2_SUBMIT_AND_FILLED_ENTRY',
    meta_json JSONB NOT NULL DEFAULT '{}'::jsonb,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_strategy_daily_order_usage_scope UNIQUE (
        trading_date,
        broker_code,
        user_broker_account_id,
        strategy_id,
        deployment_id
    )
);

CREATE INDEX IF NOT EXISTS ix_strategy_daily_order_usage_uba
    ON operation.strategy_daily_order_usage (user_broker_account_id);

ALTER TABLE trading.system_risk_setting
    ADD COLUMN IF NOT EXISTS daily_submit_limit INTEGER;

ALTER TABLE trading.system_risk_setting
    ADD COLUMN IF NOT EXISTS daily_filled_entry_limit INTEGER;

ALTER TABLE trading.user_risk_setting
    ADD COLUMN IF NOT EXISTS daily_submit_limit INTEGER;

ALTER TABLE trading.user_risk_setting
    ADD COLUMN IF NOT EXISTS daily_filled_entry_limit INTEGER;

ALTER TABLE trading.user_broker_account_risk_setting
    ADD COLUMN IF NOT EXISTS daily_submit_limit INTEGER;

ALTER TABLE trading.user_broker_account_risk_setting
    ADD COLUMN IF NOT EXISTS daily_filled_entry_limit INTEGER;

COMMENT ON TABLE operation.strategy_daily_order_usage IS
    'ORDER_LIMIT_V2 strategy-owned daily submit/filled-entry usage (DB SoT)';

COMMENT ON COLUMN trading.user_broker_account_risk_setting.daily_order_limit IS
    'Legacy V1 daily order CREATE limit (alias retained)';

COMMENT ON COLUMN trading.user_broker_account_risk_setting.daily_submit_limit IS
    'V2 daily ENTRY broker-submit attempt limit; NULL = V1 until admin opt-in';

COMMENT ON COLUMN trading.user_broker_account_risk_setting.daily_filled_entry_limit IS
    'V2 daily filled new-entry limit; NULL = V1 until admin opt-in';
