"""Alembic head helpers for migration integration tests."""

from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory


def alembic_config() -> Config:
    root = Path(__file__).resolve().parents[1]
    return Config(str(root / "alembic.ini"))


def alembic_script_directory() -> ScriptDirectory:
    return ScriptDirectory.from_config(alembic_config())


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


def assert_revision_is_ancestor_of_head(revision_id: str) -> None:
    """revision_id가 현재(단일) head까지 이어지는 조상 계열에 속하는지 검증.

    이후 Migration이 추가되어 head가 바뀌어도 이 검증은 깨지지 않는다
    (구 STEP12-1A 이전에는 head 문자열을 직접 하드코딩해 새 Migration이
    추가될 때마다 실패했다).
    """

    script = alembic_script_directory()
    head = alembic_current_head()
    ancestors = {
        rev.revision for rev in script.walk_revisions(base="base", head=head)
    }
    assert revision_id in ancestors, (
        f"Revision {revision_id} is not an ancestor of current head {head!r}"
    )
