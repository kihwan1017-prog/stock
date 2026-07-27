"""Alembic head helpers for migration integration tests."""

from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


def alembic_script_directory() -> ScriptDirectory:
    root = Path(__file__).resolve().parents[1]
    config = Config(str(root / "alembic.ini"))
    return ScriptDirectory.from_config(config)


def alembic_current_head() -> str:
    """실제 ScriptDirectory Head — Revision 문자열 하드코딩 방지."""

    heads = alembic_script_directory().get_heads()
    if len(heads) != 1:
        raise AssertionError(f"Expected single alembic head, got {heads}")
    return str(heads[0])


def assert_db_matches_alembic_head(db_version: str | None) -> None:
    """DB alembic_version == ScriptDirectory 현재 Head."""

    head = alembic_current_head()
    assert db_version == head, (
        f"DB version {db_version!r} != alembic head {head!r}"
    )


def assert_revision_exists(revision_id: str) -> None:
    """특정 STEP Migration이 체인에 존재하는지 검증."""

    script = alembic_script_directory()
    revisions = {rev.revision for rev in script.walk_revisions()}
    assert revision_id in revisions, (
        f"Revision {revision_id} missing from alembic history"
    )
