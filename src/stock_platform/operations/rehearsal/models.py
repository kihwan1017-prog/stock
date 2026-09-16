"""리허설 결과 모델."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any


class CheckStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    WARNING = "WARNING"
    SKIPPED = "SKIPPED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


@dataclass(slots=True)
class CheckResult:
    suite: str
    name: str
    status: CheckStatus
    message: str = ""
    detail: dict[str, Any] = field(default_factory=dict)
    duration_ms: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["status"] = str(self.status)
        return payload


@dataclass(slots=True)
class RehearsalOptions:
    paper: bool = False
    kiwoom: bool = False
    upbit: bool = False
    risk: bool = False
    scheduler: bool = False
    recovery: bool = False
    telegram: str = "dry-run"  # dry-run | off | live(차단)
    report_only: bool = False
    full: bool = False
    allow_paper_mutation: bool = True
    report_dir: str | None = None
    # report-only 입력 JSON (미지정 시 최신 파일)
    report_source_json: str | None = None

    def enabled_suites(self) -> set[str]:
        if self.full:
            return {
                "health",
                "kiwoom",
                "upbit",
                "paper",
                "risk",
                "live_protection",
                "upbit_live_smoke",
                "upbit_live_tracking",
                "scheduler",
                "recovery",
                "audit",
                "telegram",
                "failure",
            }
        if self.report_only:
            return set()
        selected = {"health", "audit", "failure"}
        if self.paper:
            selected.add("paper")
        if self.kiwoom:
            selected.add("kiwoom")
        if self.upbit:
            selected.add("upbit")
            selected.add("upbit_live_smoke")
            selected.add("upbit_live_tracking")
        if self.risk:
            selected.add("risk")
            selected.add("live_protection")
        if self.scheduler:
            selected.add("scheduler")
        if self.recovery:
            selected.add("recovery")
        if self.telegram != "off":
            selected.add("telegram")
        explicit = any(
            [
                self.paper,
                self.kiwoom,
                self.upbit,
                self.risk,
                self.scheduler,
                self.recovery,
                self.full,
            ]
        )
        if not explicit:
            return {
                "health",
                "kiwoom",
                "upbit",
                "paper",
                "risk",
                "live_protection",
                "scheduler",
                "recovery",
                "audit",
                "telegram",
                "failure",
            }
        return selected


@dataclass(slots=True)
class RehearsalReport:
    started_at: datetime
    finished_at: datetime | None = None
    results: list[CheckResult] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)
    report_paths: dict[str, str] = field(default_factory=dict)

    @property
    def pass_count(self) -> int:
        return sum(1 for r in self.results if r.status == CheckStatus.PASS)

    @property
    def fail_count(self) -> int:
        return sum(1 for r in self.results if r.status == CheckStatus.FAIL)

    @property
    def warning_count(self) -> int:
        return sum(
            1 for r in self.results if r.status == CheckStatus.WARNING
        )

    @property
    def not_applicable_count(self) -> int:
        return sum(
            1
            for r in self.results
            if r.status == CheckStatus.NOT_APPLICABLE
        )

    @property
    def ok(self) -> bool:
        """필수 FAIL 없으면 OK (WARNING/NOT_APPLICABLE 허용)."""

        return self.fail_count == 0

    def duration_seconds(self) -> float:
        end = self.finished_at or datetime.now(timezone.utc)
        return max(0.0, (end - self.started_at).total_seconds())

    def to_dict(self) -> dict[str, Any]:
        return {
            "started_at": self.started_at.isoformat(),
            "finished_at": (
                self.finished_at.isoformat() if self.finished_at else None
            ),
            "duration_seconds": self.duration_seconds(),
            "ok": self.ok,
            "pass_count": self.pass_count,
            "fail_count": self.fail_count,
            "warning_count": self.warning_count,
            "not_applicable_count": self.not_applicable_count,
            "meta": self.meta,
            "report_paths": self.report_paths,
            "results": [r.to_dict() for r in self.results],
        }
