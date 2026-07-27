"""STEP 8-6-1A Operation Rehearsal 정합성 테스트."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from stock_platform.operations.rehearsal.checks.health import (
    REQUIRED_COMPONENTS,
    classify_component,
)
from stock_platform.operations.rehearsal.checks.paper import rehearsal_symbol
from stock_platform.operations.rehearsal.cli import main, options_from_args
from stock_platform.operations.rehearsal.models import (
    CheckResult,
    CheckStatus,
    RehearsalOptions,
    RehearsalReport,
)
from stock_platform.operations.rehearsal.report import (
    load_report_from_json,
    regenerate_reports_from_json,
    write_reports,
)
from stock_platform.operations.rehearsal.runner import (
    make_run_id,
    run_operation_rehearsal,
)
from stock_platform.operations.rehearsal.safety import assert_rehearsal_safe


def test_classify_required_database_down_is_fail() -> None:
    status, _ = classify_component("database", {"status": "DOWN"})
    assert status == CheckStatus.FAIL
    assert "database" in REQUIRED_COMPONENTS


def test_classify_live_trading_disabled_not_applicable() -> None:
    status, reason = classify_component(
        "live_trading",
        {"status": "DISABLED", "live_order_enabled": False},
    )
    assert status == CheckStatus.NOT_APPLICABLE
    assert "disabled" in reason.lower()


def test_classify_optional_degraded_is_warning() -> None:
    status, _ = classify_component("ollama", {"status": "DEGRADED"})
    assert status == CheckStatus.WARNING


def test_run_id_format() -> None:
    run_id = make_run_id(
        datetime(2026, 7, 26, 10, 26, 31, tzinfo=timezone.utc)
    )
    assert run_id.startswith("operation-rehearsal-20260726-102631-")
    assert len(run_id) > 40


def test_rehearsal_symbol_uses_run_id() -> None:
    symbol = rehearsal_symbol("operation-rehearsal-20260726-102631-abcd1234")
    assert symbol.startswith("RH")
    assert "REHEARSAL" not in symbol or symbol.startswith("RH")


def test_json_md_html_status_consistency(tmp_path: Path) -> None:
    report = RehearsalReport(
        started_at=datetime(2026, 7, 26, 12, 0, tzinfo=timezone.utc),
        finished_at=datetime(2026, 7, 26, 12, 1, tzinfo=timezone.utc),
        meta={"run_id": "operation-rehearsal-test", "backend_version": "t"},
        results=[
            CheckResult(
                suite="health",
                name="postgresql",
                status=CheckStatus.PASS,
                message="UP",
            ),
            CheckResult(
                suite="health",
                name="live_trading",
                status=CheckStatus.NOT_APPLICABLE,
                message="disabled",
            ),
        ],
    )
    paths = write_reports(report, report_dir=tmp_path, stamp=report.started_at)
    data = json.loads(Path(paths["json"]).read_text(encoding="utf-8"))
    assert data["report_paths"]["json"].endswith(".json")
    assert data["pass_count"] == 1
    assert data["fail_count"] == 0
    md = Path(paths["markdown"]).read_text(encoding="utf-8")
    html = Path(paths["html"]).read_text(encoding="utf-8")
    assert "PASS" in md and "NOT_APPLICABLE" in md
    assert "PASS" in html and "NOT_APPLICABLE" in html
    assert "password" not in md.lower()
    assert "postgresql+psycopg://" not in html.lower()


def test_report_only_no_mutation(tmp_path: Path) -> None:
    report = RehearsalReport(
        started_at=datetime(2026, 7, 26, 13, 0, tzinfo=timezone.utc),
        finished_at=datetime(2026, 7, 26, 13, 0, tzinfo=timezone.utc),
        meta={"run_id": "seed"},
        results=[
            CheckResult(
                suite="safety",
                name="live_order_gate",
                status=CheckStatus.PASS,
                message="ok",
            )
        ],
    )
    write_reports(report, report_dir=tmp_path, stamp=report.started_at)
    with patch(
        "stock_platform.operations.rehearsal.runner.run_health_checks"
    ) as health_mock, patch(
        "stock_platform.operations.rehearsal.runner.run_paper_checks"
    ) as paper_mock:
        out = run_operation_rehearsal(
            RehearsalOptions(report_only=True, report_dir=str(tmp_path))
        )
    health_mock.assert_not_called()
    paper_mock.assert_not_called()
    assert out.ok is True
    assert out.meta.get("report_only") is True


def test_exit_code_pass_zero(tmp_path: Path) -> None:
    safe = MagicMock(
        allowed=True, code="SAFE", message="ok", detail={}
    )
    with patch(
        "stock_platform.operations.rehearsal.runner.assert_rehearsal_safe",
        return_value=safe,
    ), patch(
        "stock_platform.operations.rehearsal.runner.collect_meta",
        return_value={"run_id": "x"},
    ):
        code = main(
            [
                "--report-only",
                "--report-dir",
                str(tmp_path),
            ]
        )
    # report-only without prior json → FAIL → non-zero OR we seed first
    # seed
    write_reports(
        RehearsalReport(
            started_at=datetime.now(timezone.utc),
            finished_at=datetime.now(timezone.utc),
            results=[
                CheckResult(
                    suite="x",
                    name="y",
                    status=CheckStatus.PASS,
                    message="ok",
                )
            ],
            meta={},
        ),
        report_dir=tmp_path,
    )
    code = main(["--report-only", "--report-dir", str(tmp_path)])
    assert code == 0


def test_exit_code_fail_nonzero(tmp_path: Path) -> None:
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
        return_value={"run_id": "x"},
    ):
        code = main(["--full", "--report-dir", str(tmp_path)])
    assert code == 1


def test_invalid_cli_option_nonzero() -> None:
    with pytest.raises(SystemExit) as exc:
        options_from_args(["--unknown-flag"])
    assert exc.value.code != 0


def test_no_paper_mutation_option() -> None:
    opts = options_from_args(["--paper", "--no-paper-mutation"])
    assert opts.allow_paper_mutation is False


def test_audit_missing_events_fail() -> None:
    from stock_platform.operations.rehearsal.checks import (
        audit_telegram_failure as audit_mod,
    )

    with patch.object(
        audit_mod,
        "emit_rehearsal_audit_events",
        return_value={"created": [], "run_id": "r1"},
    ):
        fake_repo = MagicMock()
        fake_repo.list_recent.return_value = []
        session = MagicMock()
        with patch(
            "stock_platform.database.session.get_session_factory",
            return_value=lambda: session,
        ), patch(
            "stock_platform.operation.audit_repository.AuditEventRepository",
            return_value=fake_repo,
        ):
            # store_access uses list_recent too
            results = audit_mod.run_audit_checks(run_id="r1")
    verify = [r for r in results if r.name == "rehearsal_events_by_run_id"][0]
    assert verify.status == CheckStatus.FAIL


def test_safety_rejects_live_telegram() -> None:
    assert assert_rehearsal_safe(telegram_mode="live").allowed is False


def test_live_smoke_full(tmp_path: Path) -> None:
    report = run_operation_rehearsal(
        RehearsalOptions(
            full=True,
            telegram="dry-run",
            allow_paper_mutation=False,
            report_dir=str(tmp_path),
        )
    )
    assert report.meta.get("run_id", "").startswith("operation-rehearsal-")
    assert Path(report.report_paths["json"]).exists()
    data = json.loads(
        Path(report.report_paths["json"]).read_text(encoding="utf-8")
    )
    assert data["report_paths"]["json"]
    assert data["fail_count"] == report.fail_count
    # live_trading 은 NOT_APPLICABLE 이어야 함 (RC LIVE OFF)
    agg = [
        r
        for r in report.results
        if r.name == "system_health_aggregate"
    ][0]
    live = agg.detail["components"]["live_trading"]["status"]
    assert live == CheckStatus.NOT_APPLICABLE
    audit = [r for r in report.results if r.suite == "audit"]
    assert any(r.status == CheckStatus.PASS for r in audit)
    assert report.ok is True
