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

# 승인형 allowlist — 다른 shadow 자동 수정 금지
ALLOWED_RECONCILE_SHADOW_IDS: frozenset[int] = frozenset({1, 2, 3, 19})

# numeric 유지 · evaluation_detail provenance만 교정
PROVENANCE_ONLY_SHADOW_IDS: frozenset[int] = frozenset({19})

# Shadow별 승인 phrase (오적용 방지)
APPROVAL_PHRASE_BY_SHADOW: dict[int, str] = {
    1: "RECONCILE UPBIT SHADOW HISTORY",
    2: "RECONCILE UPBIT SHADOW HISTORY",
    3: "RECONCILE SHADOW 3 EVALUATION",
    19: "RECONCILE SHADOW 19 PROVENANCE",
}
# 하위 호환 (tests / 기존 #1/#2)
APPROVAL_PHRASE = "RECONCILE UPBIT SHADOW HISTORY"

# provenance detail 키 (numeric column 과 분리)
_PROVENANCE_WINDOW_KEYS: tuple[str, ...] = (
    "target_at",
    "target_candle_start",
    "target_candle_end",
    "observed_candle_at",
    "final",
    "selection_type",
    "lag_seconds",
    "fallback_reason",
    "source",
    "status",
    "price",
    "return_pct",
)

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
    # #3 — evaluator race 로 return_30m 만 잘못 stamp 된 COMPLETED
    3: {
        "return_5m_pct": -0.101937,
        "return_15m_pct": 0.0,
        "return_30m_pct": 0.101937,
        "return_60m_pct": 0.101937,
        "mfe_pct": 0.203874,
        "mae_pct": -0.203874,
        "tp_hit": False,
        "sl_hit": False,
    },
    # #19 — numeric MATCH · legacy provenance만 교정
    19: {
        "return_5m_pct": -0.311042,
        "return_15m_pct": -0.466563,
        "return_30m_pct": -1.088647,
        "return_60m_pct": 0.311042,
        "mfe_pct": 0.622084,
        "mae_pct": -1.399689,
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
            "selection_type": (windows.get(k) or {}).get("selection_type"),
            "lag_seconds": (windows.get(k) or {}).get("lag_seconds"),
            "fallback_reason": (windows.get(k) or {}).get("fallback_reason"),
            "final": (windows.get(k) or {}).get("final"),
            "target_candle_start": (windows.get(k) or {}).get(
                "target_candle_start"
            ),
            "target_candle_end": (windows.get(k) or {}).get(
                "target_candle_end"
            ),
            "source": (windows.get(k) or {}).get("source"),
        }
        for k in ("5", "15", "30", "60")
    }
    tp_sl = recomputed.get("tp_sl") or {}
    payload: dict[str, Any] = {
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
    # #3: preview↔apply 사이에 stored 컬럼이 바뀌면 fingerprint 불일치로 차단
    if int(row.shadow_id) == 3:
        payload["stored"] = {
            "return_5m_pct": row.return_5m_pct,
            "return_15m_pct": row.return_15m_pct,
            "return_30m_pct": row.return_30m_pct,
            "return_60m_pct": row.return_60m_pct,
            "price_30m": (
                float(row.price_30m) if row.price_30m is not None else None
            ),
            "mfe_pct": row.mfe_pct,
            "mae_pct": row.mae_pct,
            "tp_hit": row.tp_hit,
            "sl_hit": row.sl_hit,
            "status": row.status,
        }
    # #19: stored numeric + absence evidence + provenance-only mode
    if int(row.shadow_id) == 19:
        stored_detail = dict(row.evaluation_detail or {})
        stored_windows = dict(stored_detail.get("windows") or {})
        payload["mode"] = "provenance_only"
        payload["window_finalization"] = "last_known_price_at_target_v1"
        payload["max_prior_lag_seconds"] = int(
            recomputed.get("max_prior_lag_seconds") or 180
        )
        payload["target_resolve"] = recomputed.get("target_resolve") or {}
        payload["stored"] = {
            "status": row.status,
            "return_5m_pct": row.return_5m_pct,
            "return_15m_pct": row.return_15m_pct,
            "return_30m_pct": row.return_30m_pct,
            "return_60m_pct": row.return_60m_pct,
            "price_5m": (
                float(row.price_5m) if row.price_5m is not None else None
            ),
            "price_15m": (
                float(row.price_15m) if row.price_15m is not None else None
            ),
            "price_30m": (
                float(row.price_30m) if row.price_30m is not None else None
            ),
            "price_60m": (
                float(row.price_60m) if row.price_60m is not None else None
            ),
            "mfe_pct": row.mfe_pct,
            "mae_pct": row.mae_pct,
            "tp_hit": row.tp_hit,
            "sl_hit": row.sl_hit,
            "window_finalization": stored_detail.get("window_finalization"),
            "windows_30": stored_windows.get("30"),
        }
        # absence evidence — 30m target candle
        resolve = dict(recomputed.get("target_resolve") or {})
        w30 = windows.get("30") or {}
        payload["absence_evidence"] = {
            "target_candle_start": w30.get("target_candle_start"),
            "resolve": resolve.get(str(w30.get("target_candle_start") or "")),
            "selection_type": w30.get("selection_type"),
            "fallback_reason": w30.get("fallback_reason"),
            "lag_seconds": w30.get("lag_seconds"),
        }
    return payload


def _provenance_changed_fields(
    original: dict[str, Any],
    recomputed: dict[str, Any],
) -> list[dict[str, Any]]:
    """evaluation_detail.windows / window_finalization provenance diff."""

    stored_detail = dict(original.get("evaluation_detail") or {})
    stored_windows = dict(stored_detail.get("windows") or {})
    new_windows = recomputed.get("windows") or {}
    changed: list[dict[str, Any]] = []

    stored_fin = stored_detail.get("window_finalization")
    new_fin = "last_known_price_at_target_v1"
    if stored_fin != new_fin:
        changed.append(
            {
                "field": "evaluation_detail.window_finalization",
                "stored": stored_fin,
                "recomputed": new_fin,
            }
        )

    stored_lag = stored_detail.get("max_prior_lag_seconds")
    new_lag = recomputed.get("max_prior_lag_seconds")
    if new_lag is not None and stored_lag != new_lag:
        changed.append(
            {
                "field": "evaluation_detail.max_prior_lag_seconds",
                "stored": stored_lag,
                "recomputed": new_lag,
            }
        )

    for minutes in EVALUATION_WINDOWS_MINUTES:
        key = str(minutes)
        old_w = dict(stored_windows.get(key) or {})
        new_w = dict(new_windows.get(key) or {})
        for pk in _PROVENANCE_WINDOW_KEYS:
            old_v = old_w.get(pk)
            new_v = new_w.get(pk)
            # price/return_pct 는 numeric 동일 시 provenance 로만 표기
            if pk in ("price", "return_pct", "lag_seconds"):
                if _within_tol(old_v, new_v) and old_v is not None:
                    # 값이 같아도 key 자체가 없던 경우(legacy)는 변경으로 본다
                    if pk in old_w and pk in new_w:
                        continue
            if old_v != new_v:
                changed.append(
                    {
                        "field": f"evaluation_detail.windows[{key}].{pk}",
                        "stored": old_v,
                        "recomputed": new_v,
                    }
                )
    return changed


def _numeric_changed_fields(
    original: dict[str, Any],
    recomputed: dict[str, Any],
) -> list[dict[str, Any]]:
    windows = recomputed.get("windows") or {}
    tp_sl = recomputed.get("tp_sl") or {}
    changed: list[dict[str, Any]] = []
    for minutes in EVALUATION_WINDOWS_MINUTES:
        key = f"return_{minutes}m_pct"
        old = original.get(key)
        new = (windows.get(str(minutes)) or {}).get("return_pct")
        if not _within_tol(old, new):
            changed.append(
                {"field": key, "stored": old, "recomputed": new}
            )
        pkey = f"price_{minutes}m"
        old_p = original.get(pkey)
        new_p = (windows.get(str(minutes)) or {}).get("price")
        if not _within_tol(old_p, new_p):
            changed.append(
                {"field": pkey, "stored": old_p, "recomputed": new_p}
            )
    for key in ("mfe_pct", "mae_pct"):
        old = original.get(key)
        new = recomputed.get(key)
        if not _within_tol(old, new):
            changed.append({"field": key, "stored": old, "recomputed": new})
    for key in ("tp_hit", "sl_hit"):
        old = original.get(key)
        new = tp_sl.get(key)
        if not _within_tol(old, new):
            changed.append({"field": key, "stored": old, "recomputed": new})
    return changed


def _expected_mismatch_after_provenance_apply(
    *,
    numeric_changed: list[dict[str, Any]],
    provenance_changed: list[dict[str, Any]],
) -> dict[str, Any]:
    """apply 후 watcher 예상 — WRITE 없이 dry 판단."""

    if numeric_changed:
        return {
            "code": "SHADOW_EVALUATION_MISMATCH",
            "mismatch_count_delta": 0,
            "reason": "NUMERIC_DRIFT",
        }
    if not provenance_changed:
        return {
            "code": "MATCH",
            "mismatch_count_delta": 0,
            "reason": "ALREADY_ALIGNED",
        }
    return {
        "code": "MATCH",
        "mismatch_count_delta": -1,
        "reason": "PROVENANCE_ALIGNED_CLEARS_MISMATCH",
        "note": "apply 후 force mismatch watch 시 SHADOW_EVALUATION_MISMATCH 제거 기대",
    }

def _approval_phrase_for(shadow_id: int) -> str:
    return APPROVAL_PHRASE_BY_SHADOW.get(
        int(shadow_id), APPROVAL_PHRASE
    )


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
    """PREVIEW → fingerprint → APPLY. COMPLETED allowlist만."""

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
        numeric_changed = _numeric_changed_fields(original, recomputed)
        provenance_changed = _provenance_changed_fields(original, recomputed)
        provenance_only = int(shadow_id) in PROVENANCE_ONLY_SHADOW_IDS

        if provenance_only and numeric_changed:
            return {
                "ok": False,
                "code": "RECONCILIATION_BLOCKED",
                "reason": "NUMERIC_DRIFT_ON_PROVENANCE_ONLY",
                "shadow_id": int(shadow_id),
                "symbol": row.symbol,
                "numeric_changed_fields": numeric_changed,
                "provenance_changed_fields": provenance_changed,
                "original": original,
                "recomputed": recomputed,
                "fingerprint": fp,
                "fingerprint_payload": fp_payload,
                "orders_created": 0,
                "mutated": False,
                "persist": False,
            }

        if provenance_only:
            changed_fields = list(provenance_changed)
        else:
            changed_fields = list(numeric_changed)

        already = self._already_reconciled(row, fp) or (not changed_fields)
        phrase = _approval_phrase_for(int(shadow_id))
        expected_mismatch = (
            _expected_mismatch_after_provenance_apply(
                numeric_changed=numeric_changed,
                provenance_changed=provenance_changed,
            )
            if provenance_only
            else None
        )

        return {
            "ok": True,
            "code": "ALREADY_RECONCILED" if already else "PREVIEW_OK",
            "shadow_id": int(shadow_id),
            "symbol": row.symbol,
            "status": row.status,
            "mode": "provenance_only" if provenance_only else "numeric",
            "fingerprint": fp,
            "fingerprint_payload": fp_payload,
            "original": original,
            "recomputed": recomputed,
            "diff": dry.get("diff"),
            "changed_fields": changed_fields,
            "numeric_changed_fields": numeric_changed,
            "provenance_changed_fields": provenance_changed,
            "expected_mismatch_after_apply": expected_mismatch,
            "checkpoint_diff": checkpoint_diff,
            "approval_phrase_required": phrase,
            "allowlist": sorted(ALLOWED_RECONCILE_SHADOW_IDS),
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
        required_phrase = _approval_phrase_for(int(shadow_id))
        if (approval_phrase or "").strip() != required_phrase:
            return {
                "ok": False,
                "code": "INVALID_APPROVAL_PHRASE",
                "required_phrase": required_phrase,
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

        original = _evaluation_snapshot(row)
        numeric_changed = _numeric_changed_fields(original, recomputed)
        provenance_changed = _provenance_changed_fields(original, recomputed)
        provenance_only = int(shadow_id) in PROVENANCE_ONLY_SHADOW_IDS

        if provenance_only and numeric_changed:
            return {
                "ok": False,
                "code": "RECONCILIATION_BLOCKED",
                "reason": "NUMERIC_DRIFT_ON_PROVENANCE_ONLY",
                "numeric_changed_fields": numeric_changed,
                "orders_created": 0,
                "mutated": False,
            }

        changed_fields = (
            list(provenance_changed)
            if provenance_only
            else list(numeric_changed)
        )
        # stored 가 fingerprint 에 포함되는 #3/#19 등: 1차 적용 후 fp 가 바뀌어도
        # 대상 필드가 이미 recomputed 와 일치하면 재 WRITE / audit 금지
        if not changed_fields:
            return {
                "ok": True,
                "code": "ALREADY_RECONCILED",
                "shadow_id": int(shadow_id),
                "fingerprint": fp,
                "changed_fields": [],
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
            "return_5m_pct": row.return_5m_pct,
            "return_15m_pct": row.return_15m_pct,
            "return_30m_pct": row.return_30m_pct,
            "return_60m_pct": row.return_60m_pct,
            "price_5m": row.price_5m,
            "price_15m": row.price_15m,
            "price_30m": row.price_30m,
            "price_60m": row.price_60m,
            "mfe_pct": row.mfe_pct,
            "mae_pct": row.mae_pct,
            "tp_hit": row.tp_hit,
            "sl_hit": row.sl_hit,
        }
        if provenance_only:
            self._apply_provenance_only(row, recomputed)
        else:
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
                    "mode": "provenance_only" if provenance_only else "numeric",
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
            "mode": "provenance_only" if provenance_only else "numeric",
            "source": "minute_candle_historical_v1",
        }
        if not provenance_only:
            detail["source"] = "minute_candle_historical_v1_reconciled"
            detail["windows"] = recomputed.get("windows") or {}
            detail["mfe_mae"] = recomputed.get("mfe_mae_detail")
            detail["tp_sl"] = recomputed.get("tp_sl")
        # mismatch_watch 는 apply 직후 force re-verify 에서 MATCH 로 갱신
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
        if provenance_only:
            # numeric column 절대 변경 금지
            assert row.return_5m_pct == preserved["return_5m_pct"]
            assert row.return_15m_pct == preserved["return_15m_pct"]
            assert row.return_30m_pct == preserved["return_30m_pct"]
            assert row.return_60m_pct == preserved["return_60m_pct"]
            assert row.price_5m == preserved["price_5m"]
            assert row.price_15m == preserved["price_15m"]
            assert row.price_30m == preserved["price_30m"]
            assert row.price_60m == preserved["price_60m"]
            assert row.mfe_pct == preserved["mfe_pct"]
            assert row.mae_pct == preserved["mae_pct"]
            assert row.tp_hit == preserved["tp_hit"]
            assert row.sl_hit == preserved["sl_hit"]

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
            "mode": "provenance_only" if provenance_only else "numeric",
            "after": UpbitOpportunityShadowService.to_public(row),
            "changed_fields": changed_fields,
            "numeric_changed_fields": numeric_changed,
            "provenance_changed_fields": provenance_changed,
            "orders_created": 0,
            "mutated": True,
            "history_path": "evaluation_detail.reconciliation_history",
        }

    @staticmethod
    def _changed_fields(
        original: dict[str, Any],
        recomputed: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """하위 호환 — numeric changed_fields."""

        return _numeric_changed_fields(original, recomputed)

    def _apply_provenance_only(
        self,
        row: UpbitOpportunityShadowEntity,
        recomputed: dict[str, Any],
    ) -> None:
        """numeric column 유지 · windows provenance / finalization만 갱신."""

        detail = dict(row.evaluation_detail or {})
        prev_windows = dict(detail.get("windows") or {})
        new_windows = recomputed.get("windows") or {}
        merged: dict[str, Any] = dict(prev_windows)
        for minutes in EVALUATION_WINDOWS_MINUTES:
            key = str(minutes)
            obs = dict(new_windows.get(key) or {})
            if obs.get("status") != "OK":
                raise RuntimeError("MISSING_CANDLE")
            # 기존 window 에 provenance 필드만 덮어씀 (price/return 포함 detail)
            merged[key] = {**dict(prev_windows.get(key) or {}), **obs, "final": True}
        detail["windows"] = merged
        detail["window_finalization"] = "last_known_price_at_target_v1"
        detail["max_prior_lag_seconds"] = recomputed.get(
            "max_prior_lag_seconds", 180
        )
        if recomputed.get("target_resolve") is not None:
            detail["target_resolve"] = recomputed.get("target_resolve")
        # mismatch_watch 는 apply 경로에서 이후 force verify
        row.evaluation_detail = detail

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
        # ACTIVE(#20 등) 명시 차단 — COMPLETED 전 apply/preview 금지
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
                "shadow_id": int(shadow_id),
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
