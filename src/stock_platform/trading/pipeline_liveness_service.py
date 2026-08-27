"""UPBIT/KIWOOM Pipeline Liveness SoT — FIRST_ZERO + stage heartbeats + classification.

Watchdog / Process Map / admin API가 동일 스냅샷을 재사용한다.
REAL 정책(threshold) 변경 없음. 강제 주문 없음.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from stock_platform.trading.autotrading_health_service import (
    build_trading_health_snapshot,
)
from stock_platform.trading.autotrading_no_trade_classification import (
    classify_no_trade_status,
)

# in-process stage heartbeat (observability)
_stage_heartbeats: dict[str, dict[str, Any]] = {}


def record_stage_heartbeat(
    *,
    market: str,
    uba_id: int,
    stage: str,
    symbol: str | None = None,
    reason: str | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    key = f"{market.upper()}:{int(uba_id)}:{stage}"
    prev = _stage_heartbeats.get(key) or {}
    count = int(prev.get("count_window") or 0) + 1
    _stage_heartbeats[key] = {
        "market": market.upper(),
        "uba_id": int(uba_id),
        "stage": stage,
        "last_at": datetime.now(timezone.utc).isoformat(),
        "count_window": count,
        "last_symbol": symbol,
        "last_reason": reason,
        "extra": extra or {},
    }


def get_stage_heartbeats(*, market: str, uba_id: int) -> dict[str, dict[str, Any]]:
    prefix = f"{market.upper()}:{int(uba_id)}:"
    return {
        k.split(":")[-1]: v
        for k, v in _stage_heartbeats.items()
        if k.startswith(prefix)
    }


def _user_friendly_reason(
    *,
    classification: str,
    first_zero: str | None,
    first_zero_reason: str | None,
    stages: dict[str, Any],
    health_state: str,
) -> str:
    if classification == "SYSTEM_FAILURE":
        return (
            "자동매매 실행 스택에 장애가 있습니다. "
            "자동 복구를 시도하거나 관리자 확인이 필요합니다."
        )
    if first_zero == "ENTRY_PENDING" or first_zero_reason == "ENTRY_PENDING_ZERO_FILL_STUCK":
        return (
            "진입 대기(ENTRY_PENDING) 슬롯이 취소된 주문에 고착되어 있습니다. "
            "자동 복구로 슬롯을 비웁니다."
        )
    if classification in {"PIPELINE_STALL", "WAITING_SLOT_STARVATION"}:
        return (
            "후보/대기 슬롯은 있으나 진입·주문 단계로 진행되지 못하고 있습니다."
        )
    if classification == "NORMAL_POLICY_BLOCK":
        return "일일 진입 한도 또는 슬롯 정책으로 신규 매수가 잠시 막혀 있습니다."
    if first_zero == "ENTRY_SIGNAL" or classification == "NORMAL_NO_SIGNAL":
        eval_n = int(stages.get("ENTRY_EVALUATION") or 0)
        waiting = int(stages.get("WAITING") or 0)
        reason = first_zero_reason or "진입 조건 미충족"
        if eval_n > 0:
            return (
                f"시스템은 정상입니다. 진입 신호 평가 {eval_n}회가 있었으나 "
                f"PASS가 없습니다 (주요 사유: {reason}). "
                "전략 조건을 완화하지 않습니다."
            )
        if waiting > 0:
            return (
                f"시스템은 정상입니다. 현재 {waiting}개 후보가 "
                "진입 신호를 기다리고 있습니다."
            )
        return (
            "시스템은 정상입니다. 현재 신규 골든/진입 신호가 없어 "
            "매수가 발생하지 않았습니다."
        )
    return f"FIRST_ZERO={first_zero} reason={first_zero_reason} health={health_state}"


def build_pipeline_liveness_snapshot(
    session: Session,
    *,
    user_broker_account_id: int,
    window_minutes: float | None = None,
) -> dict[str, Any]:
    """Canonical PipelineLivenessSnapshot."""

    uba_id = int(user_broker_account_id)
    health = build_trading_health_snapshot(session, user_broker_account_id=uba_id)
    market = str(health.get("market") or "UPBIT").upper()
    funnel = health.get("funnel") or {}
    stages = dict(funnel.get("stages") or {})
    first_zero = health.get("first_zero_stage") or funnel.get("first_zero_stage")
    first_zero_reason = health.get("first_zero_reason") or funnel.get(
        "first_zero_reason"
    )
    classification = str(health.get("no_trade_classification") or "UNKNOWN")

    # last trade
    last_trade = session.execute(
        text(
            """
            SELECT order_id, symbol, side_code, status_code,
                   COALESCE(filled_at, created_at) AS ts
            FROM trading.trading_order
            WHERE user_broker_account_id = :uba AND broker_code = :brk
              AND COALESCE(filled_quantity, 0) > 0
            ORDER BY COALESCE(filled_at, created_at) DESC
            LIMIT 1
            """
        ),
        {"uba": uba_id, "brk": market if market in {"UPBIT", "KIWOOM"} else "UPBIT"},
    ).mappings().first()

    last_trade_at = None
    last_trade_summary = None
    if last_trade:
        last_trade_at = last_trade["ts"]
        last_trade_summary = {
            "order_id": last_trade["order_id"],
            "symbol": last_trade["symbol"],
            "side": last_trade["side_code"],
            "status": last_trade["status_code"],
            "at": last_trade_at.isoformat() if last_trade_at else None,
        }

    hb_db = health.get("heartbeats") or {}
    hb_mem = get_stage_heartbeats(market=market, uba_id=uba_id)
    stage_list = []
    for name in (
        "market_tick",
        "scanner",
        "candidate",
        "selection",
        "waiting_revalidation",
        "entry_evaluation",
        "entry_pass",
        "admission",
        "order_persist",
        "outbox",
        "broker_submit",
        "fill",
        "exit_evaluation",
    ):
        mem = hb_mem.get(name) or {}
        stage_list.append(
            {
                "stage": name,
                "last_at": mem.get("last_at") or hb_db.get(f"{name}_last_at"),
                "count_window": mem.get("count_window"),
                "last_symbol": mem.get("last_symbol"),
                "last_reason": mem.get("last_reason"),
                "funnel_count": stages.get(name.upper())
                or stages.get(name)
                or None,
            }
        )

    # recommended action (no forced BUY)
    if int(stages.get("ENTRY_PENDING_STUCK") or 0) > 0:
        recommended = "L1_RECONCILE_ENTRY_PENDING_ZERO_FILL"
        health_state_pipe = "DEGRADED"
    elif classification == "SYSTEM_FAILURE":
        recommended = "L2_STACK_RECONCILE"
        health_state_pipe = "SYSTEM_FAILURE"
    elif classification in {"PIPELINE_STALL", "WAITING_SLOT_STARVATION"}:
        recommended = "L1_WAITING_OR_SCANNER_RECONCILE"
        health_state_pipe = "PIPELINE_STALL"
    elif classification == "NORMAL_POLICY_BLOCK":
        recommended = "NONE_POLICY_WAIT"
        health_state_pipe = "NORMAL_POLICY_BLOCK"
    elif classification == "NORMAL_NO_SIGNAL" or first_zero == "ENTRY_SIGNAL":
        recommended = "NONE_SIGNAL_WAIT"
        health_state_pipe = "NORMAL_NO_SIGNAL"
    else:
        recommended = "OBSERVE"
        health_state_pipe = classification

    friendly = _user_friendly_reason(
        classification=classification,
        first_zero=str(first_zero) if first_zero else None,
        first_zero_reason=str(first_zero_reason) if first_zero_reason else None,
        stages=stages,
        health_state=str(health.get("health_state") or ""),
    )

    out = {
        "ok": True,
        "schema": "pipeline_liveness_v1",
        "market": market,
        "uba_id": uba_id,
        "window_start": funnel.get("window_start"),
        "window_minutes": funnel.get("window_minutes") or window_minutes,
        "last_trade_at": last_trade_at.isoformat() if last_trade_at else None,
        "last_trade": last_trade_summary,
        "stages": stages,
        "stage_heartbeats": stage_list,
        "first_zero_stage": first_zero,
        "first_zero_reason": first_zero_reason,
        "classification": classification,
        "health_state": health.get("health_state"),
        "pipeline_health_state": health_state_pipe,
        "no_trade_detail": health.get("no_trade_detail"),
        "recommended_action": recommended,
        "user_friendly_reason": friendly,
        "auto_trading_ready": health.get("auto_trading_ready"),
        "components": health.get("components"),
        "daily_blocking": health.get("daily_blocking"),
        "open_count": health.get("open_count"),
        "waiting_count": health.get("waiting_count"),
        "empty_count": health.get("empty_count"),
        "self_heal_policy": {
            "LEVEL_0": "NORMAL_NO_SIGNAL — no action",
            "LEVEL_1": "feed/scanner/entry_pending reconcile",
            "LEVEL_2": "execution stack restore",
            "LEVEL_3": "AUTO open-order startup reconciliation",
            "LEVEL_4": "fail-closed + CRITICAL telegram",
            "forbidden": [
                "FORCED_BUY",
                "THRESHOLD_RELAX",
                "DAILY_LIMIT_BYPASS",
                "MANUAL_ORDER_CANCEL",
            ],
        },
        "health_snapshot_ref": {
            "schema": health.get("schema"),
            "updated_at": health.get("updated_at"),
        },
    }
    try:
        from stock_platform.trading.autotrading_data_trust import (
            current_data_trust_summary,
            evaluate_data_trust_from_health,
        )

        ev = evaluate_data_trust_from_health(
            {
                **health,
                "stages": stages,
                "classification": classification,
                "no_trade_classification": classification,
                "first_zero_stage": first_zero,
                "watchdog": {"running": True},
            }
        )
        out["data_trust"] = ev
        # open window를 평가와 동기화 (읽기 경로에서 경량 sync — 주문 mutation 없음)
        try:
            from stock_platform.trading.autotrading_data_trust import (
                sync_data_quality_window,
            )

            sync_data_quality_window(
                session,
                market=market,
                uba_id=uba_id,
                health={
                    **health,
                    "stages": stages,
                    "classification": classification,
                    "no_trade_classification": classification,
                    "first_zero_stage": first_zero,
                    "watchdog": {"running": True},
                },
            )
            session.commit()
        except Exception:
            session.rollback()
        out["data_trust_summary"] = current_data_trust_summary(
            session, market=market, uba_id=uba_id
        )
    except Exception:
        out["data_trust"] = {"quality_status": "UNKNOWN"}
    return out


def classify_with_entry_signal_context(
    *,
    base_kwargs: dict[str, Any],
    entry_eval_count: int,
    entry_pass_count: int,
    entry_pending_stuck: int,
    top_block_reason: str | None,
) -> dict[str, Any]:
    """no_trade 분류에 entry signal / stuck pending 반영."""

    if int(entry_pending_stuck or 0) > 0:
        return {
            "classification": "PIPELINE_STALL",
            "detail": {
                "reason": "ENTRY_PENDING_ZERO_FILL_STUCK",
                "first_stalled_transition": "ENTRY_PENDING_TO_EMPTY",
                "top_block_reason": top_block_reason,
            },
            "evaluated_at": datetime.now(timezone.utc).isoformat(),
        }
    out = classify_no_trade_status(**base_kwargs)
    if (
        out.get("classification") in {"NORMAL_NO_SIGNAL", "PIPELINE_STALL", "UNKNOWN"}
        and int(entry_eval_count or 0) > 0
        and int(entry_pass_count or 0) == 0
        and not base_kwargs.get("stack_components_down")
        and base_kwargs.get("health_state") in {"READY", "DEGRADED"}
        and not base_kwargs.get("waiting_slot_starvation")
    ):
        out = {
            "classification": "NORMAL_NO_SIGNAL",
            "detail": {
                "reason": "ENTRY_SIGNAL_WAIT",
                "top_block_reason": top_block_reason,
                "entry_eval_count": int(entry_eval_count),
                "entry_pass_count": 0,
            },
            "evaluated_at": datetime.now(timezone.utc).isoformat(),
        }
    return out
