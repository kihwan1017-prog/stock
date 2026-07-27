"""STEP 8-6-1 Operation Rehearsal Automation tests."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from stock_platform.operations.rehearsal.cli import (
    build_parser,
    options_from_args,
)
from stock_platform.operations.rehearsal.models import (
    CheckResult,
    CheckStatus,
    RehearsalOptions,
    RehearsalReport,
)
from stock_platform.operations.rehearsal.report import write_reports
from stock_platform.operations.rehearsal.runner import (
    run_operation_rehearsal,
)
from stock_platform.operations.rehearsal.safety import (
    assert_rehearsal_safe,
)


def test_cli_options_full_and_telegram_dry_run() -> None:
    opts = options_from_args(
        ["--full", "--telegram=dry-run", "--report-dir", "tmp_reports"]
    )
    assert opts.full is True
    assert opts.telegram == "dry-run"
    assert opts.report_dir == "tmp_reports"
    assert "health" in opts.enabled_suites()
    assert "kiwoom" in opts.enabled_suites()


def test_cli_parser_has_required_flags() -> None:
    parser = build_parser()
    action_dests = {a.dest for a in parser._actions}
    for name in (
        "paper",
        "kiwoom",
        "upbit",
        "risk",
        "scheduler",
        "recovery",
        "telegram",
        "report_only",
        "full",
    ):
        assert name in action_dests


def test_safety_rejects_telegram_live() -> None:
    gate = assert_rehearsal_safe(telegram_mode="live")
    assert gate.allowed is False
    assert gate.code == "TELEGRAM_LIVE_FORBIDDEN"


def test_safety_rejects_real_live_orders() -> None:
    settings = MagicMock(
        global_live_order_enabled=True,
        kiwoom_live_order_enabled=True,
        upbit_live_order_enabled=False,
        kiwoom_use_mock=False,
        upbit_use_mock=True,
    )
    with patch(
        "stock_platform.operations.rehearsal.safety.get_settings",
        return_value=settings,
    ):
        gate = assert_rehearsal_safe(telegram_mode="dry-run")
    assert gate.allowed is False
    assert gate.code == "LIVE_ORDER_ENABLED"


def test_safety_allows_mock_environment() -> None:
    settings = MagicMock(
        global_live_order_enabled=False,
        kiwoom_live_order_enabled=False,
        upbit_live_order_enabled=False,
        kiwoom_use_mock=True,
        upbit_use_mock=True,
    )
    with patch(
        "stock_platform.operations.rehearsal.safety.get_settings",
        return_value=settings,
    ):
        gate = assert_rehearsal_safe(telegram_mode="dry-run")
    assert gate.allowed is True


def test_write_reports_creates_json_md_html(tmp_path: Path) -> None:
    report = RehearsalReport(
        started_at=datetime(2026, 7, 26, 10, 0, tzinfo=timezone.utc),
        finished_at=datetime(2026, 7, 26, 10, 1, tzinfo=timezone.utc),
        meta={
            "backend_version": "test",
            "alembic_head": "o4e5f6a7b8c9",
            "git_commit": "abc123",
            "os": "test-os",
            "python": "3.12",
            "db_version": "PostgreSQL",
        },
        results=[
            CheckResult(
                suite="health",
                name="postgresql",
                status=CheckStatus.PASS,
                message="UP",
            )
        ],
    )
    paths = write_reports(
        report,
        report_dir=tmp_path,
        stamp=report.started_at,
    )
    assert Path(paths["json"]).exists()
    assert Path(paths["markdown"]).exists()
    assert Path(paths["html"]).exists()
    md = Path(paths["markdown"]).read_text(encoding="utf-8")
    assert "Operation Rehearsal Report" in md
    assert "PASS" in md
    html = Path(paths["html"]).read_text(encoding="utf-8")
    assert "<html" in html


def test_run_rehearsal_fail_closed_when_unsafe(tmp_path: Path) -> None:
    unsafe = MagicMock(
        allowed=False,
        code="LIVE_ORDER_ENABLED",
        message="blocked",
        detail={},
    )
    with patch(
        "stock_platform.operations.rehearsal.runner.assert_rehearsal_safe",
        return_value=unsafe,
    ), patch(
        "stock_platform.operations.rehearsal.runner.collect_meta",
        return_value={"backend_version": "t"},
    ):
        report = run_operation_rehearsal(
            RehearsalOptions(full=True, report_dir=str(tmp_path))
        )
    assert report.ok is False
    assert report.fail_count >= 1
    assert any(r.name == "live_order_gate" for r in report.results)


def test_run_rehearsal_report_only(tmp_path) -> None:
    from datetime import datetime, timezone
    from stock_platform.operations.rehearsal.report import write_reports

    seed = RehearsalReport(
        started_at=datetime.now(timezone.utc),
        finished_at=datetime.now(timezone.utc),
        results=[
            CheckResult(
                suite="safety",
                name="live_order_gate",
                status=CheckStatus.PASS,
                message="ok",
            )
        ],
        meta={},
    )
    write_reports(seed, report_dir=tmp_path)
    report = run_operation_rehearsal(
        RehearsalOptions(report_only=True, report_dir=str(tmp_path))
    )
    assert report.ok is True
    assert report.meta.get("report_only") is True


def test_kiwoom_mock_flow_blocks_live_real() -> None:
    from stock_platform.operations.rehearsal.checks import kiwoom as kiwoom_mod

    settings = MagicMock(
        kiwoom_use_mock=False,
        kiwoom_live_order_enabled=True,
        kiwoom_app_key="x",
    )
    with patch.object(kiwoom_mod, "get_settings", return_value=settings):
        results = kiwoom_mod.run_kiwoom_checks()
    assert any(r.status == CheckStatus.FAIL for r in results)


def test_failure_telegram_live_forbidden_logic() -> None:
    from stock_platform.operations.rehearsal.checks.audit_telegram_failure import (
        run_failure_checks,
    )

    results = run_failure_checks()
    names = {r.name for r in results}
    assert "broker_timeout" in names
    assert "telegram_fail" in names
    assert all(r.status != CheckStatus.FAIL for r in results if r.name == "telegram_fail")


def test_live_operation_rehearsal_smoke(tmp_path: Path) -> None:
    """실제 환경 smoke — FAIL이 있어도 예외 없이 보고서 생성."""

    report = run_operation_rehearsal(
        RehearsalOptions(
            full=True,
            telegram="dry-run",
            allow_paper_mutation=False,
            report_dir=str(tmp_path),
        )
    )
    assert report.finished_at is not None
    assert report.report_paths.get("json")
    assert Path(report.report_paths["json"]).exists()
    assert Path(report.report_paths["markdown"]).exists()
    assert Path(report.report_paths["html"]).exists()
    suites = {r.suite for r in report.results}
    for required in (
        "safety",
        "health",
        "kiwoom",
        "upbit",
        "paper",
        "risk",
        "scheduler",
        "recovery",
        "audit",
        "telegram",
        "failure",
    ):
        assert required in suites
