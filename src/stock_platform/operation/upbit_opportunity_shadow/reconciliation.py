"""COMPLETED Shadow historical reconciliation — 승인형 1회 교정."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import structlog
from sqlalchemy.orm import Session

from stock_platform.operation.upbit_opportunity_shadow.constants import (
    EVALUATION_WINDOWS_MINUTES,
    SHADOW_STATUS_COMPLETED,
)
from stock_platform.operation.upbit_opportunity_shadow.entities import (
    UpbitOpportunityShadowEntity,
)
from stock_platform.operation.upbit_opportunity_shadow.evaluator import (
    UpbitOpportunityShadowEvaluator,
)
from stock_platform.operation.upbit_opportunity_shadow.service import (
    UpbitOpportunityShadowService,
)

logger = structlog.get_logger(__name__)

# 이번 STEP 고정 대상 — 다른 shadow 자동 수정 금지
ALLOWED_RECONCILE_SHADOW_IDS: frozenset[int] = frozenset({1, 2})

APPROVAL_PHRASE = "RECONCILE UPBIT SHADOW HISTORY"

# 이전 STEP dry 검증 체크포인트 (WRITE 값 아님 — mismatch gate 전용)
# 하드코딩 DB write 금지. preview 시 live recompute와 교차검증만.
_REFERENCE_CHECKPOINT: dict[int, dict[str, float | bool]] = {
    1: {
        "return_5m_pct": -0.472255,
        "return_15m_pct": -0.354191,
        "return_30m_pct": -0.708383,
        "return_60m_pct": -1.180638,
        "mfe_pct": 0.118064,
        "mae_pct": -1.770956,
        "tp_hit": False,
        "sl_hit": False,
    },
    2: {
        "return_5m_pct": 0.0,
        "return_15m_pct": -0.093371,
        "return_30m_pct": 0.186741,
        "return_60m_pct": 0.186741,
        "mfe_pct": 0.280112,
        "mae_pct": -0.186741,
        "tp_hit": False,
        "sl_hit": False,
    },
}

_ABS_TOL = 5e-4


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _canonical_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _fingerprint(payload: dict[str, Any]) -> str:
    digest = hashlib.sha256(_canonical_json(payload).encode("utf-8")).hexdigest()
    return digest


def _within_tol(a: Any, b: Any) -> bool:
    if isinstance(a, bool) or isinstance(b, bool):
        return bool(a) is bool(b)
    if a is None or b is None:
        return a is b
    try:
        return abs(float(a) - float(b)) <= _ABS_TOL
    except (TypeError, ValueError):
        return False


def _evaluation_snapshot(row: UpbitOpportunityShadowEntity) -> dict[str, Any]:
    return {
        "shadow_id": int(row.shadow_id),
        "symbol": row.symbol,
        "status": row.status,
        "detected_at": row.detected_at.isoformat() if row.detected_at else None,
        "completed_at": row.completed_at.isoformat() if row.completed_at else None,
        "entry_price": str(row.entry_price),
        "assumed_amount_krw": str(row.assumed_amount_krw),
        "recommendation": row.recommendation,
        "confidence": row.confidence,
        "risk_level": row.risk_level,
        "scanner_score": row.scanner_score,
        "scanner_rank": row.scanner_rank,
        "return_5m_pct": row.return_5m_pct,
        "return_15m_pct": row.return_15m_pct,
        "return_30m_pct": row.return_30m_pct,
        "return_60m_pct": row.return_60m_pct,
        "price_5m": float(row.price_5m) if row.price_5m is not None else None,
        "price_15m": float(row.price_15m) if row.price_15m is not None else None,
        "price_30m": float(row.price_30m) if row.price_30m is not None else None,
        "price_60m": float(row.price_60m) if row.price_60m is not None else None,
        "evaluated_5m_at": (
            row.evaluated_5m_at.isoformat() if row.evaluated_5m_at else None
        ),
        "evaluated_15m_at": (
            row.evaluated_15m_at.isoformat() if row.evaluated_15m_at else None
        ),
        "evaluated_30m_at": (
            row.evaluated_30m_at.isoformat() if row.evaluated_30m_at else None
        ),
        "evaluated_60m_at": (
            row.evaluated_60m_at.isoformat() if row.evaluated_60m_at else None
        ),
        "mfe_pct": row.mfe_pct,
        "mae_pct": row.mae_pct,
        "tp_hit": row.tp_hit,
        "sl_hit": row.sl_hit,
        "tp_hit_at": row.tp_hit_at.isoformat() if row.tp_hit_at else None,
        "sl_hit_at": row.sl_hit_at.isoformat() if row.sl_hit_at else None,
        "evaluation_detail": dict(row.evaluation_detail or {}),
        "evaluator_version": (row.evaluation_detail or {}).get("source"),
    }


def _fingerprint_payload(
    row: UpbitOpportunityShadowEntity,
    recomputed: dict[str, Any],
) -> dict[str, Any]:
    windows = recomputed.get("windows") or {}
    compact_windows = {
        k: {
            "target_at": (windows.get(k) or {}).get("target_at"),
            "observed_candle_at": (windows.get(k) or {}).get(
                "observed_candle_at"
            ),
            "price": (windows.get(k) or {}).get("price"),
            "return_pct": (windows.get(k) or {}).get("return_pct"),
            "status": (windows.get(k) or {}).get("status"),
        }
        for k in ("5", "15", "30", "60")
    }
    tp_sl = recomputed.get("tp_sl") or {}
    return {
        "shadow_id": int(row.shadow_id),
        "symbol": row.symbol,
        "entry_price": str(row.entry_price),
        "detected_at": row.detected_at.isoformat() if row.detected_at else None,
        "windows": compact_windows,
        "mfe_pct": recomputed.get("mfe_pct"),
        "mae_pct": recomputed.get("mae_pct"),
        "tp_hit": bool(tp_sl.get("tp_hit")),
        "sl_hit": bool(tp_sl.get("sl_hit")),
        "source": "minute_candle_historical_v1",
    }


def _windows_complete(recomputed: dict[str, Any]) -> tuple[bool, dict[str, Any]]:
    """모든 window status=OK 여부 — missing/future candle BLOCK."""

    windows = recomputed.get("windows") or {}
    detail: dict[str, Any] = {}
    ok = True
    for minutes in EVALUATION_WINDOWS_MINUTES:
        st = (windows.get(str(minutes)) or {}).get("status")
        detail[f"window_{minutes}_status"] = st
        if st != "OK":
            ok = False
    return ok, detail


def _checkpoint_ok(
    shadow_id: int, recomputed: dict[str, Any]
) -> tuple[bool, dict[str, Any]]:
    """이전 dry 검증 체크포인트와 live recompute 교차검증 (WRITE 값 아님)."""

    ref = _REFERENCE_CHECKPOINT.get(int(shadow_id))
    if ref is None:
        return True, {"skipped": True}
    windows = recomputed.get("windows") or {}
    tp_sl = recomputed.get("tp_sl") or {}
    diffs: dict[str, Any] = {}
    ok = True
    for minutes in EVALUATION_WINDOWS_MINUTES:
        key = f"return_{minutes}m_pct"
        got = (windows.get(str(minutes)) or {}).get("return_pct")
        expected = ref.get(key)
        match = _within_tol(got, expected)
        diffs[key] = {"expected": expected, "got": got, "match": match}
        if not match:
            ok = False
    for key in ("mfe_pct", "mae_pct"):
        match = _within_tol(recomputed.get(key), ref.get(key))
        diffs[key] = {
            "expected": ref.get(key),
            "got": recomputed.get(key),
            "match": match,
        }
        if not match:
            ok = False
    for key in ("tp_hit", "sl_hit"):
        match = _within_tol(tp_sl.get(key), ref.get(key))
        diffs[key] = {
            "expected": ref.get(key),
            "got": tp_sl.get(key),
            "match": match,
        }
        if not match:
            ok = False
    return ok, diffs


class UpbitOpportunityShadowReconciliationService:
    """PREVIEW → fingerprint → APPLY. COMPLETED #1/#2만."""

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

    async def preview(self, shadow_id: int) -> dict[str, Any]:
        row = self._require_eligible(shadow_id)
        if isinstance(row, dict):
            return row

        original = _evaluation_snapshot(row)
        evaluator = UpbitOpportunityShadowEvaluator(
            self._session, now=self._now, allow_sync=self._allow_sync
        )
        dry = await evaluator.dry_recompute(int(shadow_id))
        if not dry.get("ok"):
            return {
                "ok": False,
                "code": "RECOMPUTE_FAILED",
                "error": dry.get("error"),
                "orders_created": 0,
            }
        recomputed = dry.get("recomputed") or {}
        windows_ok, windows_detail = _windows_complete(recomputed)
        if not windows_ok:
            return {
                "ok": False,
                "code": "RECONCILIATION_BLOCKED",
                "reason": "MISSING_CANDLE",
                "shadow_id": int(shadow_id),
                "windows_detail": windows_detail,
                "recomputed": recomputed,
                "original": original,
                "orders_created": 0,
                "mutated": False,
            }
        checkpoint_ok, checkpoint_diff = _checkpoint_ok(int(shadow_id), recomputed)
        if not checkpoint_ok:
            return {
                "ok": False,
                "code": "RECONCILIATION_MISMATCH",
                "shadow_id": int(shadow_id),
                "symbol": row.symbol,
                "checkpoint_diff": checkpoint_diff,
                "recomputed": recomputed,
                "original": original,
                "orders_created": 0,
                "mutated": False,
            }

        fp_payload = _fingerprint_payload(row, recomputed)
        fp = _fingerprint(fp_payload)
        already = self._already_reconciled(row, fp)

        return {
            "ok": True,
            "code": "ALREADY_RECONCILED" if already else "PREVIEW_OK",
            "shadow_id": int(shadow_id),
            "symbol": row.symbol,
            "status": row.status,
            "fingerprint": fp,
            "fingerprint_payload": fp_payload,
            "original": original,
            "recomputed": recomputed,
            "diff": dry.get("diff"),
            "checkpoint_diff": checkpoint_diff,
            "approval_phrase_required": APPROVAL_PHRASE,
            "orders_created": 0,
            "mutated": False,
            "persist": False,
        }

    async def apply(
        self,
        shadow_id: int,
        *,
        expected_fingerprint: str,
        actor: str,
        reason: str,
        approval_phrase: str,
    ) -> dict[str, Any]:
        if (approval_phrase or "").strip() != APPROVAL_PHRASE:
            return {
                "ok": False,
                "code": "INVALID_APPROVAL_PHRASE",
                "orders_created": 0,
                "mutated": False,
            }

        row = self._require_eligible(shadow_id)
        if isinstance(row, dict):
            return row

        # 적용 직전 재검증
        evaluator = UpbitOpportunityShadowEvaluator(
            self._session, now=self._now, allow_sync=self._allow_sync
        )
        dry = await evaluator.dry_recompute(int(shadow_id))
        if not dry.get("ok"):
            return {
                "ok": False,
                "code": "RECOMPUTE_FAILED",
                "error": dry.get("error"),
                "orders_created": 0,
                "mutated": False,
            }
        recomputed = dry.get("recomputed") or {}
        windows_ok, windows_detail = _windows_complete(recomputed)
        if not windows_ok:
            return {
                "ok": False,
                "code": "RECONCILIATION_BLOCKED",
                "reason": "MISSING_CANDLE",
                "windows_detail": windows_detail,
                "orders_created": 0,
                "mutated": False,
            }
        checkpoint_ok, checkpoint_diff = _checkpoint_ok(int(shadow_id), recomputed)
        if not checkpoint_ok:
            return {
                "ok": False,
                "code": "RECONCILIATION_MISMATCH",
                "checkpoint_diff": checkpoint_diff,
                "orders_created": 0,
                "mutated": False,
            }

        fp_payload = _fingerprint_payload(row, recomputed)
        fp = _fingerprint(fp_payload)
        if fp != (expected_fingerprint or "").strip():
            return {
                "ok": False,
                "code": "FINGERPRINT_MISMATCH",
                "expected": expected_fingerprint,
                "actual": fp,
                "orders_created": 0,
                "mutated": False,
            }

        if self._already_reconciled(row, fp):
            return {
                "ok": True,
                "code": "ALREADY_RECONCILED",
                "shadow_id": int(shadow_id),
                "fingerprint": fp,
                "orders_created": 0,
                "mutated": False,
            }

        original = _evaluation_snapshot(row)
        # identity / AI / entry 보존 검증
        preserved = {
            "entry_price": row.entry_price,
            "assumed_amount_krw": row.assumed_amount_krw,
            "recommendation": row.recommendation,
            "confidence": row.confidence,
            "risk_level": row.risk_level,
            "scanner_score": row.scanner_score,
            "symbol": row.symbol,
            "status": row.status,
            "detected_at": row.detected_at,
        }
        self._apply_fields(row, recomputed)
        detail = dict(row.evaluation_detail or {})
        history = list(detail.get("reconciliation_history") or [])
        # 동일 fingerprint 중복 history 방지
        if not any(h.get("fingerprint") == fp for h in history):
            history.append(
                {
                    "at": self._now.isoformat(),
                    "actor": actor,
                    "reason": reason,
                    "fingerprint": fp,
                    "source": "minute_candle_historical_v1",
                    "original": original,
                    "applied": {
                        "windows": (recomputed.get("windows") or {}),
                        "mfe_pct": recomputed.get("mfe_pct"),
                        "mae_pct": recomputed.get("mae_pct"),
                        "tp_sl": recomputed.get("tp_sl"),
                    },
                }
            )
        detail["reconciliation_history"] = history
        detail["last_reconciliation"] = {
            "at": self._now.isoformat(),
            "actor": actor,
            "fingerprint": fp,
            "source": "minute_candle_historical_v1",
        }
        detail["source"] = "minute_candle_historical_v1_reconciled"
        detail["windows"] = recomputed.get("windows") or {}
        detail["mfe_mae"] = recomputed.get("mfe_mae_detail")
        detail["tp_sl"] = recomputed.get("tp_sl")
        row.evaluation_detail = detail
        row.updated_at = self._now
        # COMPLETED / identity 필드 불변
        assert row.status == SHADOW_STATUS_COMPLETED
        assert row.entry_price == preserved["entry_price"]
        assert row.assumed_amount_krw == preserved["assumed_amount_krw"]
        assert row.recommendation == preserved["recommendation"]
        assert row.confidence == preserved["confidence"]
        assert row.risk_level == preserved["risk_level"]
        assert row.scanner_score == preserved["scanner_score"]
        assert row.symbol == preserved["symbol"]
        assert row.detected_at == preserved["detected_at"]

        self._session.commit()
        self._audit(
            actor=actor,
            shadow_id=int(shadow_id),
            symbol=row.symbol,
            fingerprint=fp,
            reason=reason,
            original=original,
        )

        return {
            "ok": True,
            "code": "RECONCILED",
            "shadow_id": int(shadow_id),
            "symbol": row.symbol,
            "fingerprint": fp,
            "status": row.status,
            "after": UpbitOpportunityShadowService.to_public(row),
            "orders_created": 0,
            "mutated": True,
            "history_path": "evaluation_detail.reconciliation_history",
        }

    def _require_eligible(
        self, shadow_id: int
    ) -> UpbitOpportunityShadowEntity | dict[str, Any]:
        if int(shadow_id) not in ALLOWED_RECONCILE_SHADOW_IDS:
            return {
                "ok": False,
                "code": "SHADOW_NOT_IN_ALLOWLIST",
                "shadow_id": int(shadow_id),
                "allowed": sorted(ALLOWED_RECONCILE_SHADOW_IDS),
                "orders_created": 0,
                "mutated": False,
            }
        row = self._session.get(UpbitOpportunityShadowEntity, int(shadow_id))
        if row is None or row.deleted_at is not None:
            return {
                "ok": False,
                "code": "NOT_FOUND",
                "orders_created": 0,
                "mutated": False,
            }
        if row.status != SHADOW_STATUS_COMPLETED:
            return {
                "ok": False,
                "code": "NOT_COMPLETED",
                "status": row.status,
                "orders_created": 0,
                "mutated": False,
            }
        return row

    @staticmethod
    def _already_reconciled(
        row: UpbitOpportunityShadowEntity, fingerprint: str
    ) -> bool:
        detail = row.evaluation_detail or {}
        last = detail.get("last_reconciliation") or {}
        if last.get("fingerprint") == fingerprint:
            return True
        history = detail.get("reconciliation_history") or []
        return any(h.get("fingerprint") == fingerprint for h in history)

    def _apply_fields(
        self,
        row: UpbitOpportunityShadowEntity,
        recomputed: dict[str, Any],
    ) -> None:
        windows = recomputed.get("windows") or {}
        for minutes in EVALUATION_WINDOWS_MINUTES:
            obs = windows.get(str(minutes)) or {}
            if obs.get("status") != "OK":
                raise RuntimeError("MISSING_CANDLE")
            price = Decimal(str(obs["price"]))
            ret = float(obs["return_pct"])
            setattr(row, f"price_{minutes}m", price)
            setattr(row, f"return_{minutes}m_pct", ret)
            # observed candle 시각을 evaluated_* 에 보존(추적성)
            observed = obs.get("observed_candle_at")
            if isinstance(observed, str):
                setattr(
                    row,
                    f"evaluated_{minutes}m_at",
                    datetime.fromisoformat(observed),
                )
            else:
                setattr(row, f"evaluated_{minutes}m_at", self._now)

        if recomputed.get("mfe_pct") is not None:
            row.mfe_pct = float(recomputed["mfe_pct"])
        if recomputed.get("mae_pct") is not None:
            row.mae_pct = float(recomputed["mae_pct"])

        tp_sl = recomputed.get("tp_sl") or {}
        row.tp_hit = bool(tp_sl.get("tp_hit"))
        row.sl_hit = bool(tp_sl.get("sl_hit"))
        tp_at = tp_sl.get("tp_hit_at")
        sl_at = tp_sl.get("sl_hit_at")
        row.tp_hit_at = (
            datetime.fromisoformat(tp_at) if isinstance(tp_at, str) else tp_at
        )
        row.sl_hit_at = (
            datetime.fromisoformat(sl_at) if isinstance(sl_at, str) else sl_at
        )

    def _audit(
        self,
        *,
        actor: str,
        shadow_id: int,
        symbol: str,
        fingerprint: str,
        reason: str,
        original: dict[str, Any],
    ) -> None:
        try:
            from stock_platform.api.deps_admin import AuditLogService

            AuditLogService(self._session).record(
                event_type="UPBIT_SHADOW_HISTORY_RECONCILED",
                actor=actor,
                symbol=symbol,
                detail={
                    "shadow_id": shadow_id,
                    "fingerprint": fingerprint,
                    "reason": reason,
                    "original_returns": {
                        k: original.get(k)
                        for k in (
                            "return_5m_pct",
                            "return_15m_pct",
                            "return_30m_pct",
                            "return_60m_pct",
                            "mfe_pct",
                            "mae_pct",
                        )
                    },
                    "orders_created": 0,
                },
                auto_commit=True,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "shadow_reconcile_audit_failed",
                error=type(exc).__name__,
            )
