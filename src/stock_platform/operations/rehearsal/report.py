"""리허설 보고서 생성 (JSON / Markdown / HTML)."""

from __future__ import annotations

import html
import json
import platform
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from stock_platform.operations.rehearsal.models import (
    CheckResult,
    CheckStatus,
    RehearsalReport,
)

DEFAULT_REPORT_DIR = Path(r"E:\StockTrading\reports\operation_rehearsal")


def collect_meta(*, run_id: str | None = None) -> dict:
    meta: dict = {
        "os": platform.platform(),
        "python": sys.version.split()[0],
        "backend_version": _backend_version(),
        "alembic_head": _alembic_head(),
        "git_commit": _git_commit(),
        "db_version": _db_version(),
    }
    if run_id:
        meta["run_id"] = run_id
        meta["correlation_id"] = run_id
    return meta


def _backend_version() -> str:
    try:
        from importlib.metadata import version

        return version("stock-platform")
    except Exception:  # noqa: BLE001
        try:
            import tomllib

            pyproject = Path(__file__).resolve().parents[4] / "pyproject.toml"
            data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
            return str(data.get("project", {}).get("version") or "unknown")
        except Exception:  # noqa: BLE001
            return "unknown"


def _git_commit() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
        if result.returncode == 0:
            return (result.stdout or "").strip() or "unknown"
    except Exception:  # noqa: BLE001
        pass
    return "unknown"


def _alembic_head() -> str:
    try:
        from sqlalchemy import create_engine, text

        from stock_platform.common.settings import get_settings

        engine = create_engine(get_settings().database_url)
        with engine.connect() as conn:
            try:
                value = conn.execute(
                    text(
                        'SELECT version_num FROM "operation"."alembic_version"'
                    )
                ).scalar()
            except Exception:  # noqa: BLE001
                value = conn.execute(
                    text("SELECT version_num FROM alembic_version")
                ).scalar()
        return str(value or "unknown")
    except Exception:  # noqa: BLE001
        return "unknown"


def _db_version() -> str:
    try:
        from sqlalchemy import create_engine, text

        from stock_platform.common.settings import get_settings

        engine = create_engine(get_settings().database_url)
        with engine.connect() as conn:
            return str(conn.execute(text("SELECT version()")).scalar())
    except Exception:  # noqa: BLE001
        return "unknown"


def write_reports(
    report: RehearsalReport,
    *,
    report_dir: Path | None = None,
    stamp: datetime | None = None,
) -> dict[str, str]:
    target = Path(report_dir) if report_dir else DEFAULT_REPORT_DIR
    target.mkdir(parents=True, exist_ok=True)
    ts = (stamp or report.started_at).strftime("%Y%m%d_%H%M%S")
    base = f"operation_rehearsal_{ts}"
    paths = {
        "json": str(target / f"{base}.json"),
        "markdown": str(target / f"{base}.md"),
        "html": str(target / f"{base}.html"),
    }
    # JSON에 report_paths 포함되도록 선반영
    report.report_paths = paths
    payload = report.to_dict()
    Path(paths["json"]).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    Path(paths["markdown"]).write_text(
        _to_markdown(report),
        encoding="utf-8",
    )
    Path(paths["html"]).write_text(
        _to_html(report),
        encoding="utf-8",
    )
    return paths


def find_latest_report_json(report_dir: Path | None = None) -> Path:
    target = Path(report_dir) if report_dir else DEFAULT_REPORT_DIR
    if not target.exists():
        raise FileNotFoundError(f"report dir missing: {target}")
    files = sorted(
        target.glob("operation_rehearsal_*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not files:
        raise FileNotFoundError(f"no rehearsal json in {target}")
    return files[0]


def load_report_from_json(path: Path) -> RehearsalReport:
    data = json.loads(path.read_text(encoding="utf-8"))
    started = datetime.fromisoformat(data["started_at"])
    finished = (
        datetime.fromisoformat(data["finished_at"])
        if data.get("finished_at")
        else None
    )
    results = [
        CheckResult(
            suite=str(item["suite"]),
            name=str(item["name"]),
            status=CheckStatus(str(item["status"])),
            message=str(item.get("message") or ""),
            detail=dict(item.get("detail") or {}),
            duration_ms=float(item.get("duration_ms") or 0.0),
        )
        for item in data.get("results") or []
    ]
    return RehearsalReport(
        started_at=started,
        finished_at=finished,
        results=results,
        meta=dict(data.get("meta") or {}),
        report_paths=dict(data.get("report_paths") or {}),
    )


def regenerate_reports_from_json(
    *,
    source_json: Path | None = None,
    report_dir: Path | None = None,
) -> tuple[RehearsalReport, dict[str, str]]:
    """report-only: 기존 JSON을 읽어 MD/HTML(+동일 stem JSON 갱신)만 재생성."""

    target = Path(report_dir) if report_dir else DEFAULT_REPORT_DIR
    source = source_json or find_latest_report_json(target)
    report = load_report_from_json(source)
    # 동일 stem으로 재생성 (mutation 없음)
    match = re.search(r"operation_rehearsal_(\d{8}_\d{6})", source.name)
    if match:
        stamp = datetime.strptime(match.group(1), "%Y%m%d_%H%M%S").replace(
            tzinfo=timezone.utc
        )
    else:
        stamp = report.started_at
    paths = write_reports(report, report_dir=target, stamp=stamp)
    return report, paths


def _to_markdown(report: RehearsalReport) -> str:
    lines = [
        "# Operation Rehearsal Report",
        "",
        f"- OK: **{report.ok}**",
        f"- PASS: {report.pass_count}",
        f"- FAIL: {report.fail_count}",
        f"- WARNING: {report.warning_count}",
        f"- NOT_APPLICABLE: {report.not_applicable_count}",
        f"- Duration(s): {report.duration_seconds():.2f}",
        f"- Run ID: {report.meta.get('run_id')}",
        f"- Backend: {report.meta.get('backend_version')}",
        f"- Alembic Head: {report.meta.get('alembic_head')}",
        f"- Git: {report.meta.get('git_commit')}",
        f"- OS: {report.meta.get('os')}",
        f"- Python: {report.meta.get('python')}",
        f"- DB: {report.meta.get('db_version')}",
        "",
        "| Suite | Name | Status | Message | ms |",
        "|---|---|---|---|---|",
    ]
    for item in report.results:
        lines.append(
            f"| {item.suite} | {item.name} | {item.status} | "
            f"{item.message.replace('|', '/')} | {item.duration_ms} |"
        )
    lines.append("")
    return "\n".join(lines)


def _to_html(report: RehearsalReport) -> str:
    rows = []
    for item in report.results:
        color = {
            CheckStatus.PASS: "#0a7a2f",
            CheckStatus.FAIL: "#b00020",
            CheckStatus.WARNING: "#9a6700",
            CheckStatus.SKIPPED: "#555",
            CheckStatus.NOT_APPLICABLE: "#555",
        }.get(item.status, "#333")
        rows.append(
            "<tr>"
            f"<td>{html.escape(item.suite)}</td>"
            f"<td>{html.escape(item.name)}</td>"
            f"<td style='color:{color};font-weight:600'>"
            f"{html.escape(str(item.status))}</td>"
            f"<td>{html.escape(item.message)}</td>"
            f"<td>{item.duration_ms}</td>"
            "</tr>"
        )
    body = "\n".join(rows)
    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="utf-8"/>
  <title>Operation Rehearsal Report</title>
  <style>
    body {{ font-family: Segoe UI, sans-serif; margin: 2rem; }}
    table {{ border-collapse: collapse; width: 100%; }}
    th, td {{ border: 1px solid #ddd; padding: 8px; text-align: left; }}
    th {{ background: #f4f4f4; }}
  </style>
</head>
<body>
  <h1>Operation Rehearsal Report</h1>
  <p>OK={report.ok} PASS={report.pass_count} FAIL={report.fail_count}
     WARNING={report.warning_count} N/A={report.not_applicable_count}
     duration={report.duration_seconds():.2f}s</p>
  <ul>
    <li>Run ID: {html.escape(str(report.meta.get('run_id')))}</li>
    <li>Backend: {html.escape(str(report.meta.get('backend_version')))}</li>
    <li>Alembic: {html.escape(str(report.meta.get('alembic_head')))}</li>
    <li>Git: {html.escape(str(report.meta.get('git_commit')))}</li>
    <li>OS: {html.escape(str(report.meta.get('os')))}</li>
    <li>Python: {html.escape(str(report.meta.get('python')))}</li>
  </ul>
  <table>
    <thead><tr><th>Suite</th><th>Name</th><th>Status</th><th>Message</th><th>ms</th></tr></thead>
    <tbody>
{body}
    </tbody>
  </table>
</body>
</html>
"""
