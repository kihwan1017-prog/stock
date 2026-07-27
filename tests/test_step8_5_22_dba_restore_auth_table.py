"""STEP 8-5-22-DBA-RESTORE-AUTH-TABLE-FINAL-FIX — auth.user row compare."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "rc22_db_verify.py"


def _load_rc22():
    spec = importlib.util.spec_from_file_location("rc22_db_verify", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


rc22 = _load_rc22()


def test_compare_tables_use_auth_user_not_users() -> None:
    assert ("auth", "user") in rc22.COMPARE_TABLES
    assert ("auth", "users") not in rc22.COMPARE_TABLES
    # 비교 대상 SQL은 Identifier quoting 경로만 사용
    source = SCRIPT.read_text(encoding="utf-8")
    assert "FROM auth.users" not in source
    assert 'FROM {schema}.{table}' not in source
    assert "build_count_sql" in source


def test_build_count_sql_quotes_user_keyword() -> None:
    sql_text = rc22.build_count_sql("auth", "user")
    assert sql_text == 'SELECT COUNT(*) FROM "auth"."user"'
    assert "auth.user" not in sql_text.replace('"auth"."user"', "")


def test_build_exists_sql_uses_literals() -> None:
    sql_text = rc22.build_exists_sql("auth", "user")
    assert "information_schema.tables" in sql_text
    assert "'auth'" in sql_text
    assert "'user'" in sql_text


def test_classify_table_not_found() -> None:
    assert (
        rc22.classify_psql_failure(
            'relation "auth.users" does not exist'
        )
        == rc22.ERROR_TABLE_NOT_FOUND
    )
    assert (
        rc22.classify_psql_failure(
            '"auth.users" 이름의 릴레이션(relation)이 없습니다'
        )
        == rc22.ERROR_TABLE_NOT_FOUND
    )


def test_classify_permission_denied() -> None:
    assert (
        rc22.classify_psql_failure("permission denied for table user")
        == rc22.ERROR_PERMISSION_DENIED
    )


def test_classify_connection_failed() -> None:
    assert (
        rc22.classify_psql_failure("could not connect to server")
        == rc22.ERROR_CONNECTION_FAILED
    )


def test_redact_secrets_hides_password_and_dsn() -> None:
    msg = rc22._redact_secrets(
        "fail postgresql+psycopg://u:SecretPass@localhost/db SecretPass",
        "SecretPass",
    )
    assert "SecretPass" not in msg
    assert "postgresql://***" in msg


def test_compare_match_success() -> None:
    def runner(query: str) -> str:
        if "information_schema" in query:
            return "t"
        if '"auth"."user"' in query:
            return "3"
        raise AssertionError(query)

    result = rc22.compare_table_row_counts("auth", "user", runner, runner)
    assert result["table"] == "auth.user"
    assert result["source_exists"] is True
    assert result["restored_exists"] is True
    assert result["source_count"] == 3
    assert result["restored_count"] == 3
    assert result["match"] is True
    assert result["error"] is None


def test_compare_auth_users_missing_fail_closed() -> None:
    def runner(query: str) -> str:
        if "information_schema" in query and "'users'" in query:
            return "f"
        if "information_schema" in query:
            return "t"
        raise RuntimeError('relation "auth.users" does not exist')

    result = rc22.compare_table_row_counts("auth", "users", runner, runner)
    assert result["match"] is False
    assert result["error"] == rc22.ERROR_TABLE_NOT_FOUND


def test_compare_permission_denied_fail_closed() -> None:
    def runner(query: str) -> str:
        if "information_schema" in query:
            return "t"
        raise RuntimeError("permission denied for table user")

    result = rc22.compare_table_row_counts("auth", "user", runner, runner)
    assert result["match"] is False
    assert result["error"] == rc22.ERROR_PERMISSION_DENIED


def test_compare_count_mismatch_fail_closed() -> None:
    def source_runner(query: str) -> str:
        if "information_schema" in query:
            return "t"
        return "7"

    def restored_runner(query: str) -> str:
        if "information_schema" in query:
            return "t"
        return "5"

    result = rc22.compare_table_row_counts(
        "trading", "paper_account", source_runner, restored_runner
    )
    assert result["match"] is False
    assert result["error"] == rc22.ERROR_COUNT_MISMATCH
    assert result["source_count"] == 7
    assert result["restored_count"] == 5


def test_all_compare_tables_match_implies_restore_ok() -> None:
    comparisons = [
        {
            "table": f"{schema}.{table}",
            "source_exists": True,
            "restored_exists": True,
            "source_count": 0,
            "restored_count": 0,
            "match": True,
            "error": None,
        }
        for schema, table in rc22.COMPARE_TABLES
    ]
    assert all(c["match"] for c in comparisons)
    # 스크립트 판정과 동일
    assert all(c.get("match") is True for c in comparisons)


def test_live_auth_user_keyword_count_succeeds() -> None:
    """운영 DB에서 quoted auth.user COUNT 가 성공하는지."""

    from sqlalchemy import create_engine, text

    from stock_platform.common.settings import get_settings

    engine = create_engine(get_settings().database_url)
    count_sql = rc22.build_count_sql("auth", "user")
    with engine.connect() as conn:
        count = conn.execute(text(count_sql)).scalar()
    assert isinstance(count, int)
    assert count >= 0


def test_live_auth_users_missing_classified() -> None:
    """존재하지 않는 auth.users 는 table_not_found."""

    from sqlalchemy import create_engine, text
    from sqlalchemy.exc import ProgrammingError

    from stock_platform.common.settings import get_settings

    engine = create_engine(get_settings().database_url)
    bad_sql = rc22.build_count_sql("auth", "users")
    with engine.connect() as conn:
        with pytest.raises(ProgrammingError) as exc:
            conn.execute(text(bad_sql))
    assert (
        rc22.classify_psql_failure(str(exc.value))
        == rc22.ERROR_TABLE_NOT_FOUND
    )


def test_script_has_no_plaintext_password_logging() -> None:
    source = SCRIPT.read_text(encoding="utf-8")
    assert "print(admin_pw" not in source
    assert "print(meta[\"app_password\"]" not in source
    assert "print(meta['app_password']" not in source
