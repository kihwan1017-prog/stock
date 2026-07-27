"""STEP 8-5-17 — Broker Snapshot UBA Binding & Freshness.

Revision ID: e8f9a0b1c2d3
Revises: d7e8f9a0b1c2
"""
from __future__ import annotations

import hashlib
import re
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "e8f9a0b1c2d3"
down_revision: Union[str, Sequence[str], None] = "d7e8f9a0b1c2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_ALNUM = re.compile(r"[^0-9A-Za-z]")


def _hash_account_ref(raw: str) -> str:
    normalized = _ALNUM.sub("", (raw or "").strip())
    if not normalized:
        return ""
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def upgrade() -> None:
    # --- account snapshot binding / freshness columns ---
    op.add_column(
        "broker_account_snapshot",
        sa.Column("user_broker_account_id", sa.BigInteger(), nullable=True),
        schema="trading",
    )
    op.add_column(
        "broker_account_snapshot",
        sa.Column("paper_account_id", sa.BigInteger(), nullable=True),
        schema="trading",
    )
    op.add_column(
        "broker_account_snapshot",
        sa.Column(
            "snapshot_status",
            sa.String(30),
            nullable=False,
            server_default=sa.text("'ACTIVE'"),
        ),
        schema="trading",
    )
    op.add_column(
        "broker_account_snapshot",
        sa.Column(
            "snapshot_generation",
            sa.BigInteger(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        schema="trading",
    )
    op.add_column(
        "broker_account_snapshot",
        sa.Column(
            "snapshot_version",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        schema="trading",
    )
    op.add_column(
        "broker_account_snapshot",
        sa.Column("snapshot_hash", sa.String(64), nullable=True),
        schema="trading",
    )
    op.add_column(
        "broker_account_snapshot",
        sa.Column("snapshot_time", sa.DateTime(timezone=True), nullable=True),
        schema="trading",
    )
    op.add_column(
        "broker_account_snapshot",
        sa.Column(
            "broker_server_time", sa.DateTime(timezone=True), nullable=True
        ),
        schema="trading",
    )
    op.add_column(
        "broker_account_snapshot",
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        schema="trading",
    )
    op.create_check_constraint(
        "ck_broker_account_snapshot_status",
        "broker_account_snapshot",
        "snapshot_status IN ("
        "'ACTIVE','ORPHAN','STALE','SUPERSEDED','INVALID')",
        schema="trading",
    )
    op.create_check_constraint(
        "ck_broker_account_snapshot_generation_pos",
        "broker_account_snapshot",
        "snapshot_generation >= 1 AND snapshot_version >= 1",
        schema="trading",
    )
    op.create_foreign_key(
        "fk_broker_account_snapshot_uba",
        "broker_account_snapshot",
        "user_broker_account",
        ["user_broker_account_id"],
        ["user_broker_account_id"],
        source_schema="trading",
        referent_schema="trading",
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_broker_account_snapshot_uba",
        "broker_account_snapshot",
        ["user_broker_account_id"],
        schema="trading",
    )
    op.create_index(
        "ix_broker_account_snapshot_status_time",
        "broker_account_snapshot",
        ["snapshot_status", "snapshot_time"],
        schema="trading",
    )
    op.execute(
        sa.text(
            """
            CREATE UNIQUE INDEX uq_broker_account_snapshot_uba_active
            ON trading.broker_account_snapshot (user_broker_account_id)
            WHERE user_broker_account_id IS NOT NULL
              AND snapshot_status = 'ACTIVE'
            """
        )
    )

    # --- position snapshot binding ---
    op.add_column(
        "broker_position_snapshot",
        sa.Column("user_broker_account_id", sa.BigInteger(), nullable=True),
        schema="trading",
    )
    op.add_column(
        "broker_position_snapshot",
        sa.Column(
            "snapshot_status",
            sa.String(30),
            nullable=False,
            server_default=sa.text("'ACTIVE'"),
        ),
        schema="trading",
    )
    op.create_index(
        "ix_broker_position_snapshot_uba",
        "broker_position_snapshot",
        ["user_broker_account_id"],
        schema="trading",
    )

    # snapshot_time = synchronized_at
    op.execute(
        sa.text(
            """
            UPDATE trading.broker_account_snapshot
            SET snapshot_time = synchronized_at
            WHERE snapshot_time IS NULL
            """
        )
    )

    # Backfill UBA binding via account_ref_hash match
    conn = op.get_bind()
    snaps = conn.execute(
        sa.text(
            """
            SELECT broker_account_snapshot_id, broker_code, account_number
            FROM trading.broker_account_snapshot
            WHERE user_broker_account_id IS NULL
            """
        )
    ).mappings().all()
    ubas = conn.execute(
        sa.text(
            """
            SELECT user_broker_account_id, broker_code, account_ref_hash
            FROM trading.user_broker_account
            """
        )
    ).mappings().all()
    uba_by_key: dict[tuple[str, str], int] = {}
    for row in ubas:
        key = (
            str(row["broker_code"]).upper(),
            str(row["account_ref_hash"]),
        )
        # 동일 키 중복 시 첫 번째만 (충돌은 ORPHAN 처리)
        uba_by_key.setdefault(key, int(row["user_broker_account_id"]))

    bound = 0
    orphaned = 0
    used_uba: set[int] = set()
    for snap in snaps:
        digest = _hash_account_ref(str(snap["account_number"] or ""))
        broker = str(snap["broker_code"] or "").upper()
        uba_id = uba_by_key.get((broker, digest)) if digest else None
        if uba_id is None or uba_id in used_uba:
            conn.execute(
                sa.text(
                    """
                    UPDATE trading.broker_account_snapshot
                    SET snapshot_status = 'ORPHAN'
                    WHERE broker_account_snapshot_id = :id
                    """
                ),
                {"id": int(snap["broker_account_snapshot_id"])},
            )
            conn.execute(
                sa.text(
                    """
                    UPDATE trading.broker_position_snapshot
                    SET snapshot_status = 'ORPHAN'
                    WHERE broker_code = :broker
                      AND account_number = :acct
                    """
                ),
                {
                    "broker": broker,
                    "acct": snap["account_number"],
                },
            )
            orphaned += 1
            continue
        used_uba.add(uba_id)
        payload = "|".join(
            [
                broker,
                str(snap["account_number"] or ""),
                str(snap.get("deposit_amount") or "0"),
            ]
        )
        # 상세 금액은 아래에서 SELECT로 재계산
        conn.execute(
            sa.text(
                """
                UPDATE trading.broker_account_snapshot
                SET user_broker_account_id = :uba,
                    snapshot_status = 'ACTIVE'
                WHERE broker_account_snapshot_id = :id
                """
            ),
            {
                "uba": uba_id,
                "id": int(snap["broker_account_snapshot_id"]),
            },
        )
        conn.execute(
            sa.text(
                """
                UPDATE trading.broker_position_snapshot
                SET user_broker_account_id = :uba,
                    snapshot_status = 'ACTIVE'
                WHERE broker_code = :broker
                  AND account_number = :acct
                """
            ),
            {
                "uba": uba_id,
                "broker": broker,
                "acct": snap["account_number"],
            },
        )
        bound += 1
        _ = payload  # hash는 아래 일괄 처리

    # snapshot_hash — Python SHA-256 (pgcrypto 의존 제거)
    hash_rows = conn.execute(
        sa.text(
            """
            SELECT broker_account_snapshot_id, broker_code, account_number,
                   deposit_amount, available_order_amount,
                   total_evaluation_amount, synchronized_at
            FROM trading.broker_account_snapshot
            """
        )
    ).mappings().all()
    for row in hash_rows:
        payload = "|".join(
            [
                str(row["broker_code"] or ""),
                str(row["account_number"] or ""),
                str(row["deposit_amount"] or "0"),
                str(row["available_order_amount"] or "0"),
                str(row["total_evaluation_amount"] or "0"),
                str(row["synchronized_at"] or ""),
            ]
        )
        digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        conn.execute(
            sa.text(
                """
                UPDATE trading.broker_account_snapshot
                SET snapshot_hash = :h
                WHERE broker_account_snapshot_id = :id
                """
            ),
            {"h": digest, "id": int(row["broker_account_snapshot_id"])},
        )

    print(
        f"[STEP 8-5-17] backfill bound={bound} orphaned={orphaned}"
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "DROP INDEX IF EXISTS trading.uq_broker_account_snapshot_uba_active"
        )
    )
    op.drop_index(
        "ix_broker_position_snapshot_uba",
        table_name="broker_position_snapshot",
        schema="trading",
    )
    op.drop_column(
        "broker_position_snapshot",
        "snapshot_status",
        schema="trading",
    )
    op.drop_column(
        "broker_position_snapshot",
        "user_broker_account_id",
        schema="trading",
    )
    op.drop_index(
        "ix_broker_account_snapshot_status_time",
        table_name="broker_account_snapshot",
        schema="trading",
    )
    op.drop_index(
        "ix_broker_account_snapshot_uba",
        table_name="broker_account_snapshot",
        schema="trading",
    )
    op.drop_constraint(
        "fk_broker_account_snapshot_uba",
        "broker_account_snapshot",
        schema="trading",
        type_="foreignkey",
    )
    op.drop_constraint(
        "ck_broker_account_snapshot_generation_pos",
        "broker_account_snapshot",
        schema="trading",
        type_="check",
    )
    op.drop_constraint(
        "ck_broker_account_snapshot_status",
        "broker_account_snapshot",
        schema="trading",
        type_="check",
    )
    for col in (
        "created_at",
        "broker_server_time",
        "snapshot_time",
        "snapshot_hash",
        "snapshot_version",
        "snapshot_generation",
        "snapshot_status",
        "paper_account_id",
        "user_broker_account_id",
    ):
        op.drop_column(
            "broker_account_snapshot", col, schema="trading"
        )
