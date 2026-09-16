"""리허설 오케스트레이터."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

from stock_platform.operations.rehearsal.checks.audit_telegram_failure import (
    run_audit_checks,
    run_failure_checks,
    run_telegram_checks,
)
from stock_platform.operations.rehearsal.checks.health import run_health_checks
from stock_platform.operations.rehearsal.checks.kiwoom import run_kiwoom_checks
from stock_platform.operations.rehearsal.checks.live_protection import (
    run_live_protection_checks,
)
from stock_platform.operations.rehearsal.checks.paper import run_paper_checks
from stock_platform.operations.rehearsal.checks.recovery import (
    run_recovery_checks,
)
from stock_platform.operations.rehearsal.checks.risk import run_risk_checks
from stock_platform.operations.rehearsal.checks.scheduler import (
    run_scheduler_checks,
)
from stock_platform.operations.rehearsal.checks.upbit import run_upbit_checks
from stock_platform.operations.rehearsal.checks.upbit_live_smoke import (
    run_upbit_live_smoke_checks,
)
from stock_platform.operations.rehearsal.checks.upbit_live_tracking import (
    run_upbit_live_tracking_checks,
)
from stock_platform.operations.rehearsal.models import (
    CheckResult,
    CheckStatus,
    RehearsalOptions,
    RehearsalReport,
)
from stock_platform.operations.rehearsal.report import (
    collect_meta,
    regenerate_reports_from_json,
    write_reports,
)
from stock_platform.operations.rehearsal.safety import assert_rehearsal_safe


def make_run_id(started: datetime | None = None) -> str:
    stamp = (started or datetime.now(timezone.utc)).strftime("%Y%m%d-%H%M%S")
    return f"operation-rehearsal-{stamp}-{uuid.uuid4().hex[:8]}"


def run_operation_rehearsal(
    options: RehearsalOptions | None = None,
) -> RehearsalReport:
    opts = options or RehearsalOptions(full=True)
    started = datetime.now(timezone.utc)
    run_id = make_run_id(started)

    if opts.report_only:
        return _run_report_only(opts, started=started, run_id=run_id)

    report = RehearsalReport(
        started_at=started,
        meta=collect_meta(run_id=run_id),
    )

    gate = assert_rehearsal_safe(telegram_mode=opts.telegram)
    report.results.append(
        CheckResult(
            suite="safety",
            name="live_order_gate",
            status=(
                CheckStatus.PASS if gate.allowed else CheckStatus.FAIL
            ),
            message=gate.message,
            detail={"code": gate.code, "run_id": run_id, **gate.detail},
        )
    )
    if not gate.allowed:
        report.finished_at = datetime.now(timezone.utc)
        _emit_reports(report, opts)
        return report

    suites = opts.enabled_suites()
    if "health" in suites:
        report.results.extend(run_health_checks())
    if "kiwoom" in suites:
        report.results.extend(run_kiwoom_checks())
    if "upbit" in suites:
        report.results.extend(run_upbit_checks())
    if "paper" in suites:
        report.results.extend(run_paper_checks(opts, run_id=run_id))
    if "risk" in suites:
        report.results.extend(run_risk_checks())
    if "live_protection" in suites:
        report.results.extend(run_live_protection_checks())
    if "upbit_live_smoke" in suites:
        report.results.extend(run_upbit_live_smoke_checks())
    if "upbit_live_tracking" in suites:
        report.results.extend(run_upbit_live_tracking_checks())
    if "scheduler" in suites:
        report.results.extend(run_scheduler_checks())
    if "recovery" in suites:
        report.results.extend(run_recovery_checks())
    if "audit" in suites:
        report.results.extend(run_audit_checks(run_id=run_id))
    if "telegram" in suites:
        report.results.extend(run_telegram_checks(opts))
    if "failure" in suites:
        report.results.extend(run_failure_checks())

    report.finished_at = datetime.now(timezone.utc)
    _emit_reports(report, opts)
    return report


def _run_report_only(
    opts: RehearsalOptions,
    *,
    started: datetime,
    run_id: str,
) -> RehearsalReport:
    """기존 JSON 기반 MD/HTML 재생성 — Broker/DB mutation 없음."""

    report_dir = Path(opts.report_dir) if opts.report_dir else None
    source = (
        Path(opts.report_source_json) if opts.report_source_json else None
    )
    try:
        report, paths = regenerate_reports_from_json(
            source_json=source,
            report_dir=report_dir,
        )
    except Exception as exc:  # noqa: BLE001
        report = RehearsalReport(
            started_at=started,
            finished_at=datetime.now(timezone.utc),
            meta=collect_meta(run_id=run_id),
            results=[
                CheckResult(
                    suite="report",
                    name="report_only",
                    status=CheckStatus.FAIL,
                    message=f"report-only failed: {type(exc).__name__}",
                    detail={"error": str(exc)[:200]},
                )
            ],
        )
        return report

    report.meta = {
        **report.meta,
        "report_only": True,
        "report_only_source": str(source or paths.get("json")),
        "report_only_run_id": run_id,
    }
    # 재생성 후 경로 반영된 JSON 다시 기록 (mutation 아님)
    write_reports(
        report,
        report_dir=report_dir,
        stamp=report.started_at,
    )
    for item in report.results:
        print(f"[{item.status}] {item.suite}.{item.name}: {item.message}")
    print(
        f"SUMMARY ok={report.ok} pass={report.pass_count} "
        f"fail={report.fail_count} warn={report.warning_count} "
        f"duration_s={report.duration_seconds():.2f} report_only=True"
    )
    for kind, path in report.report_paths.items():
        print(f"REPORT_{kind.upper()}={path}")
    return report


def _emit_reports(report: RehearsalReport, opts: RehearsalOptions) -> None:
    report_dir = Path(opts.report_dir) if opts.report_dir else None
    try:
        write_reports(report, report_dir=report_dir)
    except Exception as exc:  # noqa: BLE001
        report.results.append(
            CheckResult(
                suite="report",
                name="write_reports",
                status=CheckStatus.FAIL,
                message=f"report write failed: {type(exc).__name__}",
                detail={"error": str(exc)[:200]},
            )
        )
        print(f"FAIL_CLOSED: report write failed: {type(exc).__name__}")
        return
    for item in report.results:
        print(f"[{item.status}] {item.suite}.{item.name}: {item.message}")
    print(
        f"SUMMARY ok={report.ok} pass={report.pass_count} "
        f"fail={report.fail_count} warn={report.warning_count} "
        f"na={report.not_applicable_count} "
        f"duration_s={report.duration_seconds():.2f} "
        f"run_id={report.meta.get('run_id')}"
    )
    for kind, path in report.report_paths.items():
        print(f"REPORT_{kind.upper()}={path}")
