"""Research-only lineage helpers — REAL entry/exit 정책 불변."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

# 관측 구간 (초) — candle_minute 근사 스냅샷용
PRICE_PATH_HORIZONS_SEC = (30, 60, 180, 300)


def _as_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _tri_state(value: Any) -> bool | str:
    """True/False만 확정. 없으면 UNKNOWN (날조 금지)."""

    if value is None:
        return "UNKNOWN"
    if isinstance(value, str) and value.strip().upper() in {"", "UNKNOWN", "NOT_RECORDED"}:
        return "UNKNOWN"
    if isinstance(value, str) and value.strip().upper() in {"TRUE", "1", "YES"}:
        return True
    if isinstance(value, str) and value.strip().upper() in {"FALSE", "0", "NO"}:
        return False
    if isinstance(value, bool):
        return value
    return "UNKNOWN"


def resolve_candidate_provenance(
    session: Session,
    *,
    selection_id: int | None = None,
    order_meta: dict[str, Any] | None = None,
    binding_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """AUTO entry provenance — ranking 로직은 변경하지 않고 관측만."""

    meta_o = dict(order_meta or {})
    meta_b = dict(binding_meta or {})
    entry_obs = dict(meta_b.get("entry_observation") or {})

    sel_id = selection_id
    if sel_id is None:
        for src in (meta_o, entry_obs, meta_b):
            raw = src.get("candidate_selection_id") or src.get("selection_id")
            if raw is not None:
                try:
                    sel_id = int(raw)
                    break
                except (TypeError, ValueError):
                    pass

    out: dict[str, Any] = {
        "candidate_selection_id": sel_id if sel_id is not None else "NOT_RECORDED",
        "scanner_rank": meta_o.get("scanner_rank", entry_obs.get("scanner_rank", "NOT_RECORDED")),
        "scanner_score": meta_o.get("scanner_score", entry_obs.get("scanner_score", "NOT_RECORDED")),
        "candidate_universe_size": meta_o.get(
            "candidate_universe_size", entry_obs.get("candidate_universe_size", "NOT_RECORDED")
        ),
        "candidate_selected_at": meta_o.get(
            "candidate_selected_at", entry_obs.get("candidate_selected_at", "NOT_RECORDED")
        ),
        "variant_scores": meta_o.get("variant_scores", entry_obs.get("variant_scores", {})),
        "provenance_source": "ORDER_META_OR_BINDING",
    }

    if sel_id is None:
        return out

    try:
        from stock_platform.operation.upbit_full_market.entities import (
            UpbitLiveCandidateSelectionEntity,
        )

        sel = session.get(UpbitLiveCandidateSelectionEntity, int(sel_id))
    except Exception:  # noqa: BLE001
        sel = None

    if sel is None:
        out["provenance_source"] = "SELECTION_ID_MISSING_ROW"
        return out

    if out["scanner_rank"] in (None, "NOT_RECORDED") and sel.rank is not None:
        out["scanner_rank"] = int(sel.rank)
    if out["scanner_score"] in (None, "NOT_RECORDED") and sel.score is not None:
        out["scanner_score"] = float(sel.score)
    if out["candidate_selected_at"] in (None, "NOT_RECORDED") and sel.selected_at is not None:
        out["candidate_selected_at"] = sel.selected_at.isoformat()

    # universe size: 동일 scanner_run_id 내 선택 행 수 (가능 범위)
    if out["candidate_universe_size"] in (None, "NOT_RECORDED"):
        try:
            from sqlalchemy import func, select
            from stock_platform.operation.upbit_full_market.entities import (
                UpbitLiveCandidateSelectionEntity as SelE,
            )

            n = session.scalar(
                select(func.count())
                .select_from(SelE)
                .where(
                    SelE.user_broker_account_id == int(sel.user_broker_account_id),
                    SelE.scanner_run_id == str(sel.scanner_run_id),
                )
            )
            if n is not None:
                out["candidate_universe_size"] = int(n)
        except Exception:  # noqa: BLE001
            pass

    # Lab A variant scores — 후보 ranking 재계산 금지. 기존 refresh 스냅샷만 참조.
    if not out.get("variant_scores"):
        try:
            from stock_platform.operation.upbit_opportunity_shadow.profitability_improvement_shadow.entities import (
                UpbitProfitabilityCandidateRefreshEntity,
            )
            from sqlalchemy import select

            refresh = session.scalar(
                select(UpbitProfitabilityCandidateRefreshEntity)
                .where(
                    UpbitProfitabilityCandidateRefreshEntity.user_broker_account_id
                    == int(sel.user_broker_account_id),
                    UpbitProfitabilityCandidateRefreshEntity.scanner_run_id
                    == str(sel.scanner_run_id),
                )
                .order_by(UpbitProfitabilityCandidateRefreshEntity.observed_at.desc())
                .limit(1)
            )
            if refresh is not None:
                scores: dict[str, Any] = {}
                sym = str(sel.symbol).upper()
                for vid, ranks in dict(refresh.rankings_json or {}).items():
                    for item in ranks or []:
                        if str(item.get("symbol") or "").upper() == sym:
                            scores[str(vid)] = item.get("score")
                            break
                if scores:
                    out["variant_scores"] = scores
        except Exception:  # noqa: BLE001
            pass

    out["provenance_source"] = "LIVE_CANDIDATE_SELECTION"
    out["scanner_run_id"] = str(sel.scanner_run_id)
    return out


def build_reentry_context(
    session: Session,
    *,
    prior_binding: Any,
    new_binding: Any | None,
    entry_order_id: int | None,
    entry_at: datetime,
) -> dict[str, Any]:
    """C3 contextual flags — 실제 근거 없으면 UNKNOWN."""

    prior_meta = dict(getattr(prior_binding, "meta_json", None) or {})
    prior_entry_obs = dict(prior_meta.get("entry_observation") or {})
    new_meta = dict(getattr(new_binding, "meta_json", None) or {}) if new_binding else {}
    new_entry_obs = dict(new_meta.get("entry_observation") or {})

    previous_exit_reason = str(
        prior_meta.get("exit_reason")
        or prior_meta.get("signal_reason")
        or "UNKNOWN"
    ).upper()
    previous_exit_price = prior_meta.get("exit_price") or prior_meta.get(
        "average_exit_price"
    )
    previous_exit_at = getattr(prior_binding, "closed_at", None)
    # exit_intent SoT — meta에 exit_reason 없으면 durable intent에서 보강
    if previous_exit_reason in {"", "UNKNOWN", "NOT_RECORDED"}:
        try:
            from stock_platform.operation.upbit_exit_intent.entities import (
                UpbitExitIntentEntity,
            )

            intent = session.scalar(
                select(UpbitExitIntentEntity)
                .where(
                    UpbitExitIntentEntity.binding_id
                    == int(prior_binding.binding_id),
                    UpbitExitIntentEntity.exit_reason.isnot(None),
                )
                .order_by(UpbitExitIntentEntity.created_at.desc())
                .limit(1)
            )
            if intent is not None and intent.exit_reason:
                previous_exit_reason = str(intent.exit_reason).upper()
                if previous_exit_price is None:
                    detail = dict(intent.detail_json or {})
                    for key in ("current_price", "exit_price", "price"):
                        if detail.get(key) is not None:
                            previous_exit_price = detail.get(key)
                            break
        except Exception:  # noqa: BLE001
            pass

    order_meta: dict[str, Any] = {}
    new_signal_id = None
    new_entry_reason = "NOT_RECORDED"
    new_entry_price = None
    if entry_order_id is not None:
        try:
            from stock_platform.order.entities import TradingOrderEntity

            order = session.get(TradingOrderEntity, int(entry_order_id))
            if order is not None:
                order_meta = dict(getattr(order, "metadata_payload", None) or {})
                new_signal_id = (
                    getattr(order, "source_signal_id", None)
                    or order_meta.get("signal_id")
                )
                new_entry_reason = str(
                    order_meta.get("signal_reason")
                    or order_meta.get("entry_reason")
                    or new_entry_obs.get("entry_reason")
                    or "NOT_RECORDED"
                )
                if order.average_fill_price is not None:
                    new_entry_price = float(order.average_fill_price)
        except Exception:  # noqa: BLE001
            pass

    if new_entry_price is None and new_entry_obs.get("entry_price") is not None:
        try:
            new_entry_price = float(new_entry_obs["entry_price"])
        except (TypeError, ValueError):
            pass

    prior_signal_id = (
        prior_entry_obs.get("signal_id")
        or prior_entry_obs.get("source_signal_id")
        or prior_meta.get("entry_signal_id")
    )
    # fresh_signal: 이전/신규 signal id 모두 있을 때만 비교
    if prior_signal_id and new_signal_id:
        new_signal_flag: bool | str = str(prior_signal_id) != str(new_signal_id)
    else:
        new_signal_flag = "UNKNOWN"

    # score_improved: 양쪽 scanner_score 숫자일 때만
    prior_score = prior_entry_obs.get("scanner_score")
    new_score = order_meta.get("scanner_score", new_entry_obs.get("scanner_score"))
    try:
        if prior_score not in (None, "NOT_RECORDED") and new_score not in (
            None,
            "NOT_RECORDED",
        ):
            score_improved: bool | str = float(new_score) > float(prior_score)
        else:
            score_improved = "UNKNOWN"
    except (TypeError, ValueError):
        score_improved = "UNKNOWN"

    # MA_RECOVERED: reentry 시점 short>long 이면 True / short<long False / 없으면 UNKNOWN
    ma_improved: bool | str = "UNKNOWN"
    momentum_reset: bool | str = "UNKNOWN"
    short_ma = None
    long_ma = None
    try:
        from stock_platform.operation.upbit_opportunity_shadow.profitability_improvement_shadow.entities import (
            UpbitProfitabilityExitEnrollmentEntity,
        )
        from sqlalchemy import select

        enr = session.scalar(
            select(UpbitProfitabilityExitEnrollmentEntity).where(
                UpbitProfitabilityExitEnrollmentEntity.binding_id
                == int(getattr(new_binding, "binding_id"))
            )
        ) if new_binding is not None else None
        # new enrollment may not exist yet — use prior path last MA if any
        if enr is None and prior_binding is not None:
            enr = session.scalar(
                select(UpbitProfitabilityExitEnrollmentEntity).where(
                    UpbitProfitabilityExitEnrollmentEntity.binding_id
                    == int(prior_binding.binding_id)
                )
            )
        path = dict(getattr(enr, "path_state_json", None) or {}) if enr else {}
        short_ma = path.get("short_ma")
        long_ma = path.get("long_ma")
        if short_ma is not None and long_ma is not None:
            ma_improved = float(short_ma) > float(long_ma)
        mom = path.get("macd")
        if mom is not None:
            # 이전 exit 직후 macd가 음수였다가 재진입에서 양수면 reset으로 해석
            prior_macd = (prior_meta.get("exit_path") or {}).get("macd")
            if prior_macd is not None:
                momentum_reset = float(mom) > 0 and float(prior_macd) <= 0
            else:
                momentum_reset = "UNKNOWN"
    except Exception:  # noqa: BLE001
        pass

    sel_id = getattr(new_binding, "selection_id", None) if new_binding else None
    provenance = resolve_candidate_provenance(
        session,
        selection_id=int(sel_id) if sel_id is not None else None,
        order_meta=order_meta,
        binding_meta=new_meta,
    )

    return {
        "new_signal": new_signal_flag,
        "fresh_signal": new_signal_flag,
        "ma_improved": ma_improved,
        "MA_RECOVERED": ma_improved,
        "momentum_reset": momentum_reset,
        "score_improved": score_improved,
        "context_source": "REENTRY_LINEAGE_V1",
        "previous_exit_reason": previous_exit_reason,
        "previous_exit_at": (
            previous_exit_at.isoformat()
            if previous_exit_at is not None and hasattr(previous_exit_at, "isoformat")
            else None
        ),
        "previous_exit_price": (
            float(previous_exit_price) if previous_exit_price is not None else None
        ),
        "previous_binding_id": int(prior_binding.binding_id),
        "new_entry_reason": new_entry_reason,
        "new_entry_at": entry_at.isoformat() if hasattr(entry_at, "isoformat") else None,
        "new_entry_price": new_entry_price,
        "new_signal_id": new_signal_id if new_signal_id is not None else "NOT_RECORDED",
        "short_ma_at_reentry": short_ma,
        "long_ma_at_reentry": long_ma,
        **provenance,
    }


def lookup_candle_prices(
    session: Session,
    *,
    symbol: str,
    anchor_at: datetime,
    horizons_sec: tuple[int, ...] = PRICE_PATH_HORIZONS_SEC,
) -> dict[str, Any]:
    """기존 market.candle_minute 근사 — 신규 tick DB 없음."""

    anchor = _as_utc(anchor_at)
    if anchor is None:
        return {"status": "UNAVAILABLE_NO_ANCHOR", "source": "market.candle_minute"}

    end = anchor + timedelta(seconds=max(horizons_sec) + 120)
    start = anchor - timedelta(minutes=2)
    try:
        rows = session.execute(
            text(
                """
                SELECT c.candle_at, c.close_price
                FROM market.candle_minute c
                JOIN market.instrument i ON i.instrument_id = c.instrument_id
                WHERE i.exchange_code='UPBIT' AND i.symbol=:sym AND c.timeframe=1
                  AND c.candle_at >= :s AND c.candle_at <= :e
                ORDER BY c.candle_at
                """
            ),
            {"sym": str(symbol).upper(), "s": start, "e": end},
        ).mappings().all()
    except Exception:  # noqa: BLE001
        return {"status": "UNAVAILABLE_QUERY_ERROR", "source": "market.candle_minute"}

    if not rows:
        return {"status": "UNAVAILABLE_NO_CANDLE", "source": "market.candle_minute"}

    series = [
        (r["candle_at"].astimezone(timezone.utc), float(r["close_price"]))
        for r in rows
        if r["close_price"] is not None
    ]

    def price_at(t: datetime) -> float | None:
        target = t.replace(second=0, microsecond=0)
        best = None
        for ct, close in series:
            if ct <= target:
                best = close
            else:
                break
        return best

    entry = price_at(anchor)
    out: dict[str, Any] = {
        "status": "PARTIAL",
        "source": "market.candle_minute",
        "anchor_at": anchor.isoformat(),
        "entry_price": entry,
        "note": "1m candle approximation; sub-minute exact tick not stored",
    }
    hit = 0
    for sec in horizons_sec:
        key = f"price_{sec}s" if sec < 600 else f"price_{sec}s"
        # post-anchor offsets use same helper; caller prefixes post_exit_
        px = price_at(anchor + timedelta(seconds=sec))
        out[f"offset_{sec}s"] = px
        if px is not None:
            hit += 1
    if entry is not None and hit == len(horizons_sec):
        out["status"] = "COMPLETE"
    elif entry is None and hit == 0:
        out["status"] = "UNAVAILABLE_NO_CANDLE"
    return out


def build_bounded_price_path(
    session: Session,
    *,
    symbol: str,
    entry_at: datetime | None,
    entry_price: float | None,
    exit_at: datetime | None,
    exit_price: float | None = None,
) -> dict[str, Any]:
    """entry/post-exit bounded snapshots only."""

    result: dict[str, Any] = {
        "entry_price": entry_price,
        "exit_price": exit_price,
        "source": "market.candle_minute",
    }
    if entry_at is not None:
        pre = lookup_candle_prices(session, symbol=symbol, anchor_at=entry_at)
        result["entry_path_status"] = pre.get("status")
        if result["entry_price"] is None:
            result["entry_price"] = pre.get("entry_price")
        for sec in PRICE_PATH_HORIZONS_SEC:
            result[f"price_{sec}s"] = pre.get(f"offset_{sec}s")
    else:
        result["entry_path_status"] = "UNAVAILABLE_NO_ENTRY_AT"

    if exit_at is not None:
        post = lookup_candle_prices(session, symbol=symbol, anchor_at=exit_at)
        result["post_exit_path_status"] = post.get("status")
        for sec in PRICE_PATH_HORIZONS_SEC:
            result[f"post_exit_{sec}s"] = post.get(f"offset_{sec}s")
    else:
        result["post_exit_path_status"] = "UNAVAILABLE_NO_EXIT_AT"

    statuses = {
        result.get("entry_path_status"),
        result.get("post_exit_path_status"),
    }
    if "COMPLETE" in statuses and not any(
        str(s or "").startswith("UNAVAILABLE") for s in statuses
    ):
        result["status"] = "COMPLETE"
    elif all(str(s or "").startswith("UNAVAILABLE") for s in statuses):
        result["status"] = "UNAVAILABLE"
    else:
        result["status"] = "PARTIAL"
    return result
