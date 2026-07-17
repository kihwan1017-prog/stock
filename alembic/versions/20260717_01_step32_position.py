from alembic import op
import sqlalchemy as sa
revision="20260717_01"
down_revision="REPLACE_WITH_STEP32_8_REVISION"
branch_labels=None
depends_on=None
def upgrade()->None:
    op.create_table("position",sa.Column("position_id",sa.BigInteger(),primary_key=True),sa.Column("account_id",sa.String(50),nullable=False),sa.Column("market",sa.String(20),nullable=False),sa.Column("symbol",sa.String(30),nullable=False),sa.Column("quantity",sa.Numeric(24,8),nullable=False,server_default="0"),sa.Column("average_price",sa.Numeric(24,8),nullable=False,server_default="0"),sa.Column("realized_pnl",sa.Numeric(24,8),nullable=False,server_default="0"),sa.Column("last_price",sa.Numeric(24,8)),sa.UniqueConstraint("account_id","market","symbol",name="uq_position_account_market_symbol"),schema="trading")
    op.create_table("position_execution",sa.Column("execution_id",sa.String(100),primary_key=True),sa.Column("account_id",sa.String(50),nullable=False),sa.Column("market",sa.String(20),nullable=False),sa.Column("symbol",sa.String(30),nullable=False),sa.Column("side",sa.String(10),nullable=False),sa.Column("quantity",sa.Numeric(24,8),nullable=False),sa.Column("price",sa.Numeric(24,8),nullable=False),schema="trading")
def downgrade()->None:
    op.drop_table("position_execution",schema="trading"); op.drop_table("position",schema="trading")
