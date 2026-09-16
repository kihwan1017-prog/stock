"""COMPLETED Shadow stored vs historical dry-recompute 회귀 감시 (READ ONLY)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import structlog
from sqlalchemy.orm import Session

from stock_platform.common.settings import get_settings
from stock_platform.operation.upbit_opportunity_shadow.candle_path import (
    DEFAULT_MAX_PRIOR_LAG_SECONDS,
    SELECTION_EXACT,
    SELECTION_LAST_KNOWN,
)
from stock_platform.operation.upbit_opportunity_shadow.constants import (
    EVALUATION_WINDOWS_MINUTES,
    SHADOW_STATUS_ACTIVE,
    SHADOW_STATUS_COMPLETED,
)
from stock_platform.operation.upbit_opportunity_shadow.entities import (
    UpbitOpportunityShadowEntity,
)
from stock_platform.operation.upbit_opportunity_shadow.evaluator import (
    UpbitOpportunityShadowEvaluator,
)
from stock_platform.operation.upbit_opportunity_shadow.notify import (
    publish_shadow_mismatch,
)
from stock_platform.operation.upbit_opportunity_shadow.service import (
    UpbitOpportunityShadowService,
)

logger = structlog.get_logger(__name__)

MISMATCH_CODE = "SHADOW_EVALUATION_MISMATCH"
LEGACY_PROVENANCE_MISMATCH = "LEGACY_PROVENANCE_MISMATCH"
ALLOWED_FINAL_SELECTION = frozenset({SELECTION_EXACT, SELECTION_LAST_KNOWN})


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _within_tol(a: Any, b: Any, *, tol: float) -> bool:
    if isinstance(a, bool) or isinstance(b, bool):
        return bool(a) is bool(b)
    if a is None or b is None:
        return a is b
    try:
        return abs(float(a) - float(b)) <= tol
    except (TypeError, ValueError):
        return False


def _recomputed_provenance_ok(
    window: dict[str, Any],
    *,
    max_prior_lag_seconds: float = DEFAULT_MAX_PRIOR_LAG_SECONDS,
) -> tuple[bool, str | None]:
    """신규 FINAL provenance 허용 여부."""

    status = window.get("status")
    if status in ("NOT_MATURED", "MISSING_CANDLE"):
        # final stamp 전이면 watcher numeric 과 별개
        return True, None
    if status == "SOURCE_UNAVAILABLE":
        return False, "SOURCE_UNAVAILABLE"
    if status != "OK" and not window.get("final"):
        return True, None

    selection = window.get("selection_type")
    if selection == SELECTION_EXACT:
        return True, None
    if selection == SELECTION_LAST_KNOWN:
        lag = window.get("lag_seconds")
        try:
            lag_f = float(lag) if lag is not None else None
        except (TypeError, ValueError):
            lag_f = None
        if lag_f is None or lag_f > float(max_prior_lag_seconds):
            return False, "LAG_EXCEEDED"
        if window.get("fallback_reason") == "SOURCE_UNAVAILABLE":
            return False, "SOURCE_UNAVAILABLE"
        return True, None
    if selection is None and (window.get("final") or status == "OK"):
        return False, "UNKNOWN_PROVENANCE"
    if selection not in ALLOWED_FINAL_SELECTION:
        return False, "DISALLOWED_SELECTION"
    return True, None


def _stored_provenance_note(
    stored_windows: dict[str, Any],
    recomputed_windows: dict[str, Any],
    *,
    max_prior_lag_seconds: float = DEFAULT_MAX_PRIOR_LAG_SECONDS,
) -> dict[str, Any]:
    """legacy COMPLETED row provenance 별도 표기."""

    notes: dict[str, Any] = {}
    legacy = False
    for minutes in EVALUATION_WINDOWS_MINUTES:
        key = str(minutes)
        stored_w = dict(stored_windows.get(key) or {})
        recomputed_w = dict(recomputed_windows.get(key) or {})
        if recomputed_w.get("status") != "OK":
            continue
        ok_new, reason_new = _recomputed_provenance_ok(
            recomputed_w, max_prior_lag_seconds=max_prior_lag_seconds
        )
        stored_sel = stored_w.get("selection_type")
        if stored_sel in ALLOWED_FINAL_SELECTION:
            notes[key] = {
                "stored_selection_type": stored_sel,
                "recomputed_selection_type": recomputed_w.get(
                    "selection_type"
                ),
                "legacy": False,
                "recomputed_ok": ok_new,
                "reason": reason_new,
            }
            continue
        # 숫자 일치해도 구형 provenance 없음 → LEGACY 표기 후보
        legacy = True
        notes[key] = {
            "stored_selection_type": stored_sel,
            "recomputed_selection_type": recomputed_w.get("selection_type"),
            "legacy": True,
            "recomputed_ok": ok_new,
            "reason": "UNKNOWN_LEGACY_PROVENANCE",
        }
    return {"legacy": legacy, "windows": notes}


def _compare(
    stored: dict[str, Any],
    recomputed: dict[str, Any],
    *,
    tol: float,
    stored_detail: dict[str, Any] | None = None,
    max_prior_lag_seconds: float = DEFAULT_MAX_PRIOR_LAG_SECONDS,
) -> tuple[bool, dict[str, Any], dict[str, Any]]:
    windows = recomputed.get("windows") or {}
    tp_sl = recomputed.get("tp_sl") or {}
    diffs: dict[str, Any] = {}
    ok = True
    for minutes in EVALUATION_WINDOWS_MINUTES:
        key = f"return_{minutes}m_pct"
        got = (windows.get(str(minutes)) or {}).get("return_pct")
        old = stored.get(key)
        match = _within_tol(old, got, tol=tol)
        w = windows.get(str(minutes)) or {}
        prov_ok, prov_reason = _recomputed_provenance_ok(
            w, max_prior_lag_seconds=max_prior_lag_seconds
        )
        diffs[key] = {
            "stored": old,
            "recomputed": got,
            "match": match,
            "selection_type": w.get("selection_type"),
            "lag_seconds": w.get("lag_seconds"),
            "fallback_reason": w.get("fallback_reason"),
            "provenance_ok": prov_ok,
            "provenance_reason": prov_reason,
        }
        if not match:
            ok = False
        # FINAL 확정 재계산인데 provenance 불허면 mismatch
        if w.get("status") == "OK" and not prov_ok:
            ok = False
    for key in ("mfe_pct", "mae_pct"):
        got = recomputed.get(key)
        old = stored.get(key)
        match = _within_tol(old, got, tol=tol)
        diffs[key] = {"stored": old, "recomputed": got, "match": match}
        if not match:
            ok = False
    for key in ("tp_hit", "sl_hit"):
        got = tp_sl.get(key)
        old = stored.get(key)
        match = _within_tol(old, got, tol=tol)
        diffs[key] = {"stored": old, "recomputed": got, "match": match}
        if not match:
            ok = False

    provenance = _stored_provenance_note(
        dict((stored_detail or {}).get("windows") or {}),
        windows,
        max_prior_lag_seconds=max_prior_lag_seconds,
    )
    return ok, diffs, provenance


class ShadowEvaluationMismatchWatch:
    """자동 reconciliation 금지 — Audit + Telegram만."""

    def __init__(
        self,
        session: Session,
        *,
        now: datetime | None = None,
        allow_sync: bool = True,
    ) -> None:
        self._session = session
        self._now = now or _utcnow()
        self._allow_sync = allow_sync

    async def verify_completed(
        self,
        row: UpbitOpportunityShadowEntity,
        *,
        notify: bool = True,
        force: bool = False,
    ) -> dict[str, Any]:
        settings = get_settings()
        if not bool(
            getattr(settings, "upbit_scanner_shadow_mismatch_watch_enabled", True)
        ):
            return {
                "ok": True,
                "skipped": True,
                "code": "WATCH_DISABLED",
                "orders_created": 0,
            }
        # ACTIVE 는 mismatch 감시 대상 제외
        if row.status == SHADOW_STATUS_ACTIVE:
            return {
                "ok": True,
                "skipped": True,
                "code": "ACTIVE_EXCLUDED",
                "orders_created": 0,
            }
        if row.status != SHADOW_STATUS_COMPLETED:
            return {
                "ok": False,
                "code": "NOT_COMPLETED",
                "orders_created": 0,
            }

        detail = dict(row.evaluation_detail or {})
        prev = detail.get("mismatch_watch") or {}
        # 이미 일치로 확인된 건 재검사 skip (force 제외)
        if (
            not force
            and prev.get("ok") is True
            and prev.get("code") in ("MATCH", LEGACY_PROVENANCE_MISMATCH)
        ):
            return {
                "ok": True,
                "skipped": True,
                "code": "ALREADY_MATCHED",
                "shadow_id": int(row.shadow_id),
                "orders_created": 0,
            }

        tol = float(
            getattr(settings, "upbit_scanner_shadow_mismatch_tolerance", 5e-4)
            or 5e-4
        )
        evaluator = UpbitOpportunityShadowEvaluator(
            self._session, now=self._now, allow_sync=self._allow_sync
        )
        dry = await evaluator.dry_recompute(int(row.shadow_id))
        if not dry.get("ok"):
            return {
                "ok": False,
                "code": "RECOMPUTE_FAILED",
                "error": dry.get("error"),
                "orders_created": 0,
            }

        stored = dry.get("stored") or UpbitOpportunityShadowService.to_public(
            row
        )
        recomputed = dry.get("recomputed") or {}
        match_ok, diffs, provenance = _compare(
            stored,
            recomputed,
            tol=tol,
            stored_detail=detail,
            max_prior_lag_seconds=float(
                recomputed.get("max_prior_lag_seconds")
                or DEFAULT_MAX_PRIOR_LAG_SECONDS
            ),
        )
        if match_ok and provenance.get("legacy"):
            code = LEGACY_PROVENANCE_MISMATCH
        elif match_ok:
            code = "MATCH"
        else:
            code = MISMATCH_CODE

        watch_payload = {
            "at": self._now.isoformat(),
            "ok": match_ok,
            "code": code,
            "tolerance": tol,
            "diff": diffs,
            "provenance": provenance,
            "source": "minute_candle_historical_v1",
            # reconciliation allowlist 경로와 분리
            "auto_reconcile": False,
        }
        detail["mismatch_watch"] = watch_payload
        row.evaluation_detail = detail
        row.updated_at = self._now
        self._session.commit()

        if code == MISMATCH_CODE:
            self._audit(row, diffs)
            if notify:
                try:
                    publish_shadow_mismatch(
                        UpbitOpportunityShadowService.to_public(row),
                        diff=diffs,
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "shadow_mismatch_notify_failed",
                        shadow_id=row.shadow_id,
                        error=type(exc).__name__,
                    )

        return {
            "ok": match_ok,
            "code": watch_payload["code"],
            "shadow_id": int(row.shadow_id),
            "symbol": row.symbol,
            "diff": diffs,
            "provenance": provenance,
            "orders_created": 0,
            "mutated_evaluation_fields": False,
            "watch_meta_only": True,
        }

    async def verify_many(
        self,
        rows: list[UpbitOpportunityShadowEntity],
        *,
        notify: bool = True,
    ) -> dict[str, Any]:
        results = []
        mismatches = 0
        for row in rows:
            out = await self.verify_completed(row, notify=notify)
            results.append(out)
            if out.get("code") == MISMATCH_CODE:
                mismatches += 1
        return {
            "checked": len(results),
            "mismatches": mismatches,
            "results": results,
            "orders_created": 0,
        }

    def _audit(
        self,
        row: UpbitOpportunityShadowEntity,
        diffs: dict[str, Any],
    ) -> None:
        try:
            from stock_platform.api.deps_admin import AuditLogService

            AuditLogService(self._session).record(
                event_type=MISMATCH_CODE,
                actor="shadow_mismatch_watch",
                symbol=row.symbol,
                detail={
                    "shadow_id": int(row.shadow_id),
                    "code": MISMATCH_CODE,
                    "diff": diffs,
                    "auto_reconcile": False,
                    "orders_created": 0,
                },
                auto_commit=True,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "shadow_mismatch_audit_failed",
                error=type(exc).__name__,
            )
