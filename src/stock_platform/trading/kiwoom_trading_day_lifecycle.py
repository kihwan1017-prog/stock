"""Kiwoom next-trading-day AUTO START + EOD lifecycle (fail-closed).

공식 preflight/gate/transition 경로를 재사용한다.
09:00 LIVE/ARM 강제 ON 금지 — 거래일·정규장·safety gate PASS 후에만 진행.
Activation 최초 phrase 우회 금지 — source_activation successor만 허용.
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from stock_platform.order.live_safety_audit import (
    emit_live_order_telegram,
    emit_live_safety_audit,
)
from stock_platform.trading.account_models import UserBrokerAccount
from stock_platform.trading.live_session_expiry import aware_utc
from stock_platform.trading.live_unattended_authorization_service import (
    CONFIRM_ENABLE_MARKET_HOURS,
    MODE_MARKET_HOURS,
    STATUS_ACTIVE,
    STATUS_EXPIRED,
    STATUS_PROTECTIVE,
    LiveUnattendedAuthorizationService,
    LiveUnattendedError,
)
from stock_platform.trading.live_unattended_entities import (
    LiveUnattendedAuthorizationEntity,
)
from stock_platform.trading.market_hours_authorization import (
    krx_market_hours_state,
    market_hours_authorized_until,
)

logger = structlog.get_logger(__name__)

CONFIRM_ENABLE_NEXT_DAY = "ENABLE KIWOOM NEXT DAY AUTO START"
CONFIRM_DISABLE_NEXT_DAY = "DISABLE KIWOOM NEXT DAY AUTO START"

# State machine (idempotent ticks)
PHASE_WAITING_MARKET = "WAITING_MARKET"
PHASE_PRECHECK = "PRECHECK"
PHASE_ACCOUNT_SYNC = "ACCOUNT_SYNC"
PHASE_FEED_START = "FEED_START"
PHASE_WARMUP = "WARMUP"
PHASE_ACTIVATION_CHECK = "ACTIVATION_CHECK"
PHASE_LIVE_ENABLE = "LIVE_ENABLE"
PHASE_MARKET_HOURS_AUTHORIZE = "MARKET_HOURS_AUTHORIZE"
PHASE_ARM_ENABLE = "ARM_ENABLE"
PHASE_RUNTIME_RESUME = "RUNTIME_RESUME"
PHASE_RUNNER_START = "RUNNER_START"
PHASE_TRADING = "TRADING"
PHASE_MARKET_CLOSE = "MARKET_CLOSE"
PHASE_PROTECTIVE_EXIT_ONLY = "PROTECTIVE_EXIT_ONLY"
PHASE_SAFE_IDLE = "SAFE_IDLE"
PHASE_BLOCKED = "BLOCKED"

ACTOR_SYSTEM = "SYSTEM_KIWOOM_NEXT_DAY"

# 텔레그램 spam 억제
_TELEGRAM_COOLDOWN_SECONDS = 900


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _detail_flag(row: LiveUnattendedAuthorizationEntity | None) -> bool:
    if row is None:
        return False
    detail = dict(row.last_renewal_detail or {})
    return bool(detail.get("next_trading_day_auto_start"))


class KiwoomTradingDayLifecycleService:
    """UBA-scoped Kiwoom trading-day lifecycle."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._unattended = LiveUnattendedAuthorizationService(session)

    # ------------------------------------------------------------------
    # Consent / status
    # ------------------------------------------------------------------

    def get_latest_authorization(
        self, user_broker_account_id: int
    ) -> LiveUnattendedAuthorizationEntity | None:
        return self._session.scalar(
            select(LiveUnattendedAuthorizationEntity)
            .where(
                LiveUnattendedAuthorizationEntity.user_broker_account_id
                == int(user_broker_account_id),
                LiveUnattendedAuthorizationEntity.broker_code == "KIWOOM",
            )
            .order_by(
                LiveUnattendedAuthorizationEntity.live_unattended_authorization_id.desc()
            )
            .limit(1)
        )

    def list_opted_in_uba_ids(self) -> list[int]:
        """next_trading_day_auto_start=true 인 최신 KIWOOM consent UBA."""

        rows = list(
            self._session.scalars(
                select(LiveUnattendedAuthorizationEntity)
                .where(
                    LiveUnattendedAuthorizationEntity.broker_code == "KIWOOM"
                )
                .order_by(
                    LiveUnattendedAuthorizationEntity.live_unattended_authorization_id.desc()
                )
            ).all()
        )
        seen: set[int] = set()
        out: list[int] = []
        for row in rows:
            uba_id = int(row.user_broker_account_id)
            if uba_id in seen:
                continue
            seen.add(uba_id)
            if _detail_flag(row):
                out.append(uba_id)
        return out

    def set_next_trading_day_auto_start(
        self,
        user_broker_account_id: int,
        *,
        enabled: bool,
        actor: str,
        confirmation_text: str,
        reason: str | None = None,
    ) -> dict[str, Any]:
        """운영자 명시 opt-in. Activation phrase 우회 아님."""

        text_u = (confirmation_text or "").strip().upper()
        expect = (
            CONFIRM_ENABLE_NEXT_DAY if enabled else CONFIRM_DISABLE_NEXT_DAY
        )
        if not secrets.compare_digest(text_u, expect):
            raise LiveUnattendedError(
                "CONFIRMATION_REQUIRED",
                f"confirmation_text must be exactly '{expect}'",
            )

        uba = self._session.get(
            UserBrokerAccount, int(user_broker_account_id)
        )
        if uba is None:
            raise LiveUnattendedError("UBA_NOT_FOUND", "UBA not found")
        if str(uba.broker_code or "").upper() != "KIWOOM":
            raise LiveUnattendedError(
                "BROKER_NOT_SUPPORTED",
                "Next-day auto-start is KIWOOM-only",
            )

        row = self.get_latest_authorization(int(user_broker_account_id))
        if row is None:
            raise LiveUnattendedError(
                "NO_CONSENT_HISTORY",
                "Enable MARKET_HOURS unattended at least once before "
                "next-day auto-start opt-in",
            )

        # source activation 없으면 다음날 Activation successor 불가 → 차단
        if enabled and row.source_activation_id is None:
            from stock_platform.broker.live_transition_service import (
                LiveTradingTransitionService,
            )

            act = LiveTradingTransitionService(self._session).peek_active(
                broker_code="KIWOOM",
                user_broker_account_id=int(user_broker_account_id),
            )
            if act is None:
                raise LiveUnattendedError(
                    "ACTIVATION_SECURITY_BOUNDARY",
                    "Active/source Activation required — cannot bypass "
                    "'ENABLE KIWOOM LIVE TRADING' for greenfield",
                )
            row.source_activation_id = int(act.live_trading_transition_id)

        now = _now()
        detail = dict(row.last_renewal_detail or {})
        detail["authorization_mode"] = MODE_MARKET_HOURS
        detail["next_trading_day_auto_start"] = bool(enabled)
        detail["next_day_toggle"] = {
            "enabled": bool(enabled),
            "actor": actor[:100],
            "at": now.isoformat(),
            "reason": (reason or "")[:500],
        }
        # lifecycle 상태 초기화
        detail["lifecycle"] = {
            "phase": PHASE_SAFE_IDLE if not enabled else PHASE_WAITING_MARKET,
            "updated_at": now.isoformat(),
            "blockers": [],
        }
        row.last_renewal_detail = detail
        row.updated_at = now
        self._session.flush()
        emit_live_safety_audit(
            self._session,
            event_type="KIWOOM_NEXT_DAY_AUTO_START_TOGGLED",
            actor=actor,
            run_id=None,
            user_id=int(uba.user_id),
            account_id=int(user_broker_account_id),
            strategy_id=None,
            detail={
                "enabled": bool(enabled),
                "authorization_id": int(
                    row.live_unattended_authorization_id
                ),
            },
            commit=False,
        )
        self._session.commit()
        return self.status_dict(int(user_broker_account_id))

    def status_dict(self, user_broker_account_id: int) -> dict[str, Any]:
        uba = self._session.get(
            UserBrokerAccount, int(user_broker_account_id)
        )
        mh = krx_market_hours_state(self._session)
        row = self.get_latest_authorization(int(user_broker_account_id))
        active = self._unattended.get_active(int(user_broker_account_id))
        detail = dict(row.last_renewal_detail or {}) if row else {}
        life = detail.get("lifecycle") if isinstance(detail.get("lifecycle"), dict) else {}
        unattended = self._unattended.status_dict(int(user_broker_account_id))

        # next open 추정
        next_open = None
        try:
            from stock_platform.operation.calendar_repository import (
                TradingCalendarRepository,
            )
            from stock_platform.operation.calendar_service import (
                TradingCalendarService,
            )
            from zoneinfo import ZoneInfo

            cal = TradingCalendarService(
                TradingCalendarRepository(self._session)
            )
            today = datetime.now(ZoneInfo("Asia/Seoul")).date()
            if mh.get("before_open") and mh.get("is_trading_day"):
                next_open = mh.get("regular_open_at_utc")
            else:
                nxt = cal.next_trading_day(
                    exchange_code="KRX", calendar_date=today
                )
                if nxt is not None:
                    decision = cal.evaluate(
                        exchange_code="KRX", calendar_date=nxt
                    )
                    from datetime import time as time_cls

                    open_t = decision.regular_open_at or time_cls(9, 0)
                    open_kst = datetime.combine(
                        nxt, open_t, tzinfo=ZoneInfo("Asia/Seoul")
                    )
                    next_open = open_kst.astimezone(timezone.utc).isoformat()
        except Exception:  # noqa: BLE001
            next_open = None

        feed: dict[str, Any] = {}
        warmup: dict[str, Any] = {}
        try:
            from stock_platform.realtime.kiwoom_market_realtime_runtime import (
                kiwoom_market_realtime_runtime,
            )

            feed = kiwoom_market_realtime_runtime.status()
        except Exception:  # noqa: BLE001
            feed = {"running": False}
        try:
            from stock_platform.realtime.consumer_registry import (
                consumer_registry,
            )

            warmup = {
                "warmup_status": getattr(
                    consumer_registry, "warmup_status", None
                )
            }
            # registry snapshot if available
            if hasattr(consumer_registry, "status"):
                st = consumer_registry.status()
                if isinstance(st, dict):
                    warmup = {
                        "warmup_status": st.get("warmup_status"),
                        "warmup_by_symbol": st.get("warmup_by_symbol"),
                    }
        except Exception:  # noqa: BLE001
            warmup = {"warmup_status": "UNKNOWN"}

        return {
            "user_broker_account_id": int(user_broker_account_id),
            "broker_code": (
                str(uba.broker_code or "").upper() if uba else None
            ),
            "next_trading_day_auto_start": _detail_flag(row),
            "lifecycle_phase": life.get("phase") or PHASE_SAFE_IDLE,
            "lifecycle_blockers": list(life.get("blockers") or []),
            "lifecycle_updated_at": life.get("updated_at"),
            "last_precheck": life.get("last_precheck"),
            "market": mh,
            "is_trading_day": bool(mh.get("is_trading_day")),
            "market_session": (
                "OPEN"
                if mh.get("in_regular_session")
                else (
                    "BEFORE_OPEN"
                    if mh.get("before_open")
                    else (
                        "AFTER_CLOSE"
                        if mh.get("past_close")
                        else "CLOSED"
                    )
                )
            ),
            "live": bool(uba.live_order_enabled) if uba else False,
            "arm": bool(uba.live_armed) if uba else False,
            "arm_expires_at": (
                aware_utc(uba.arm_expires_at).isoformat()
                if uba is not None and uba.arm_expires_at is not None
                else None
            ),
            "unattended": unattended,
            "consent_authorization_id": (
                int(row.live_unattended_authorization_id) if row else None
            ),
            "active_lease_status": (
                str(active.status_code) if active is not None else "OFF"
            ),
            "source_activation_id": (
                int(row.source_activation_id)
                if row is not None and row.source_activation_id is not None
                else None
            ),
            "feed": feed,
            "warmup": warmup,
            "next_market_open_at": next_open,
            "required_confirmation_enable": CONFIRM_ENABLE_NEXT_DAY,
            "required_confirmation_disable": CONFIRM_DISABLE_NEXT_DAY,
        }

    # ------------------------------------------------------------------
    # Precheck
    # ------------------------------------------------------------------

    def evaluate_auto_start_precheck(
        self, user_broker_account_id: int
    ) -> dict[str, Any]:
        """자동 시작 전 fail-closed gate. LIVE/ARM은 복구 대상이라 제외 가능."""

        uba_id = int(user_broker_account_id)
        blockers: list[str] = []
        checks: dict[str, Any] = {}

        uba = self._session.get(UserBrokerAccount, uba_id)
        if uba is None:
            return {
                "ok": False,
                "blockers": ["UBA_NOT_FOUND"],
                "checks": {},
                "gate_count": 1,
            }
        if str(uba.broker_code or "").upper() != "KIWOOM":
            return {
                "ok": False,
                "blockers": ["BROKER_NOT_KIWOOM"],
                "checks": {},
                "gate_count": 1,
            }

        mh = krx_market_hours_state(self._session)
        checks["market"] = mh
        if not mh.get("is_trading_day"):
            blockers.append("NOT_KRX_TRADING_DAY")
        elif not mh.get("in_regular_session"):
            blockers.append("MARKET_SESSION_NOT_OPEN")

        # restore-grade (LIVE/ARM/Activation 제외) + MARKET_HOURS mode
        restore = self._unattended.evaluate_restore_gates(uba_id)
        # restore는 enable_gates 기반이라 MARKET_CLOSED가 중복될 수 있음
        ignored = {
            "LIVE_OFF",
            "ARM_OFF",
            "ARM_EXPIRED",
            "ACTIVATION_INACTIVE",
            "RUNTIME_NOT_RUNNING",
            "OUTBOX_WORKER_NOT_RUNNING",
            "MARKET_CLOSED",  # 위에서 별도 판정
        }
        for code in restore.get("blockers") or []:
            if code in ignored:
                continue
            blockers.append(str(code))
        checks["restore_gates"] = {
            "ok": restore.get("ok"),
            "blockers": restore.get("blockers"),
            "execution_env": (restore.get("checks") or {}).get("execution_env")
            if isinstance(restore.get("checks"), dict)
            else restore.get("execution_env"),
        }

        # UNKNOWN / unsafe OPEN
        try:
            from stock_platform.order.live_open_order_exposure import (
                evaluate_live_open_order_exposure,
            )

            exposure = evaluate_live_open_order_exposure(
                self._session,
                uba_id=uba_id,
                broker_code="KIWOOM",
                environment="LIVE",
            )
            checks["open_order_exposure"] = exposure.as_detail()
            if int(exposure.unknown_open_count) > 0:
                blockers.append("UNKNOWN_ORDER")
            # remote unmapped / total open이 비정상적으로 많으면 차단
            if int(exposure.remote_unmapped_count) > 0:
                blockers.append("UNSAFE_OPEN_ORDER")
            if not bool(exposure.remote_state_ok):
                blockers.append("OPEN_ORDER_REMOTE_STATE_BAD")
        except Exception:  # noqa: BLE001
            blockers.append("OPEN_ORDER_CHECK_FAILED")

        # consent + source activation
        row = self.get_latest_authorization(uba_id)
        if not _detail_flag(row):
            blockers.append("NEXT_DAY_OPT_IN_OFF")
        checks["next_day_opt_in"] = _detail_flag(row)
        source_id = (
            int(row.source_activation_id)
            if row is not None and row.source_activation_id is not None
            else None
        )
        if source_id is None:
            from stock_platform.broker.live_transition_service import (
                LiveTradingTransitionService,
            )

            act = LiveTradingTransitionService(self._session).peek_active(
                broker_code="KIWOOM",
                user_broker_account_id=uba_id,
            )
            if act is None:
                blockers.append("ACTIVATION_SECURITY_BOUNDARY")
            else:
                source_id = int(act.live_trading_transition_id)
        checks["source_activation_id"] = source_id

        # deployment / strategy link
        try:
            from stock_platform.strategy_deployment.definition_entities import (
                AccountStrategyLinkEntity,
            )

            link = self._session.scalar(
                select(AccountStrategyLinkEntity)
                .where(
                    AccountStrategyLinkEntity.user_broker_account_id == uba_id,
                    AccountStrategyLinkEntity.is_active.is_(True),
                )
                .limit(1)
            )
            if link is None:
                blockers.append("DEPLOYMENT_LINK_INACTIVE")
            else:
                checks["strategy_id"] = int(link.strategy_id)
        except Exception:  # noqa: BLE001
            blockers.append("DEPLOYMENT_CHECK_FAILED")

        seen: set[str] = set()
        uniq: list[str] = []
        for code in blockers:
            if code in seen:
                continue
            seen.add(code)
            uniq.append(code)

        # 명목 gate 수 (보고용)
        gate_names = [
            "KRX_TRADING_DAY",
            "MARKET_SESSION_OPEN",
            "CREDENTIAL_REAL_VERIFIED",
            "REST_CONNECTED",
            "ACCOUNT_SYNC_RECOVERY",
            "TRADING_PAUSED_OFF",
            "KILL_OFF",
            "CONFLICT_ZERO",
            "UNKNOWN_ORDER_ZERO",
            "UNSAFE_OPEN_ZERO",
            "NEXT_DAY_OPT_IN",
            "SOURCE_ACTIVATION",
            "DEPLOYMENT_ACTIVE",
        ]
        return {
            "ok": len(uniq) == 0,
            "blockers": uniq,
            "checks": checks,
            "gate_count": len(gate_names),
            "gate_names": gate_names,
        }

    # ------------------------------------------------------------------
    # Phase persistence + telegram
    # ------------------------------------------------------------------

    def _write_lifecycle(
        self,
        row: LiveUnattendedAuthorizationEntity,
        *,
        phase: str,
        blockers: list[str] | None = None,
        precheck: dict[str, Any] | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        detail = dict(row.last_renewal_detail or {})
        detail["authorization_mode"] = MODE_MARKET_HOURS
        # next_day flag 보존
        if "next_trading_day_auto_start" not in detail:
            detail["next_trading_day_auto_start"] = True
        life = {
            "phase": phase,
            "updated_at": _now().isoformat(),
            "blockers": list(blockers or []),
        }
        if precheck is not None:
            life["last_precheck"] = {
                "ok": precheck.get("ok"),
                "blockers": precheck.get("blockers"),
                "at": _now().isoformat(),
            }
        if extra:
            life.update(extra)
        detail["lifecycle"] = life
        row.last_renewal_detail = (
            LiveUnattendedAuthorizationService._preserve_mode_detail(
                row, detail
            )
        )
        # next_day 보존 (_preserve가 빠뜨릴 수 있음)
        preserved = dict(row.last_renewal_detail or {})
        if detail.get("next_trading_day_auto_start") is not None:
            preserved["next_trading_day_auto_start"] = detail[
                "next_trading_day_auto_start"
            ]
        preserved["lifecycle"] = life
        row.last_renewal_detail = preserved
        row.updated_at = _now()
        self._session.flush()

    def _emit_lifecycle_telegram(
        self,
        *,
        uba_id: int,
        event_type: str,
        title: str,
        message: str,
        detail: dict[str, Any] | None = None,
        row: LiveUnattendedAuthorizationEntity | None = None,
    ) -> None:
        store_row = row or self.get_latest_authorization(uba_id)
        now = _now()
        if store_row is not None:
            store = dict(store_row.last_renewal_detail or {})
            key = f"last_tg_{event_type}"
            last = store.get(key)
            if last:
                try:
                    dt = datetime.fromisoformat(
                        str(last).replace("Z", "+00:00")
                    )
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    if (
                        now - dt.astimezone(timezone.utc)
                    ).total_seconds() < _TELEGRAM_COOLDOWN_SECONDS:
                        return
                except Exception:  # noqa: BLE001
                    pass
            store[key] = now.isoformat()
            store_row.last_renewal_detail = store
            try:
                self._session.flush()
            except Exception:  # noqa: BLE001
                pass

        emit_live_order_telegram(
            event_type=event_type,
            title=title,
            message=message,
            detail={
                "uba_id": uba_id,
                "user_broker_account_id": uba_id,
                "broker_code": "KIWOOM",
                "telegram_market": "KIWOOM",
                **(detail or {}),
            },
        )
        # ANALYSIS suppress edge — 명확한 장 개장/종료 전환에서만 1회
        try:
            from stock_platform.notification.telegram_policy import (
                maybe_emit_kiwoom_market_edge,
            )

            phase = str(
                (detail or {}).get("phase")
                or (detail or {}).get("lifecycle_phase")
                or ""
            ).upper()
            et = str(event_type or "").upper()
            open_ready = phase == "TRADING" or et in {
                "KIWOOM_TRADING_STARTED",
                "KIWOOM_MARKET_OPEN",
                "MARKET_OPEN_AND_READY",
            }
            closed = phase in {"SAFE_IDLE", "EOD", "CLOSED", "PREOPEN"} or et in {
                "KIWOOM_MARKET_CLOSED",
                "SAFE_IDLE",
                "EOD_PROTECT",
                "MARKET_CLOSED",
            }
            if open_ready and not closed:
                maybe_emit_kiwoom_market_edge(
                    ready=True,
                    uba_id=int(uba_id),
                    context={"lifecycle_phase": phase or None},
                )
            elif closed:
                maybe_emit_kiwoom_market_edge(
                    ready=False,
                    uba_id=int(uba_id),
                    context={"lifecycle_phase": phase or None},
                )
        except Exception:  # noqa: BLE001
            pass

    # ------------------------------------------------------------------
    # Reauthorize MARKET_HOURS for trading day
    # ------------------------------------------------------------------

    def reauthorize_market_hours_for_trading_day(
        self,
        user_broker_account_id: int,
        *,
        actor: str,
        correlation_id: str | None = None,
        system_next_day: bool = False,
    ) -> dict[str, Any]:
        """PROTECTIVE/EXPIRED 이후 당일 MARKET_HOURS lease 재발급 + LIVE/ARM 복구.

        system_next_day=True 이면 기존 opt-in consent로 confirmation 대체.
        운영자 최초 Activation phrase는 우회하지 않는다 (source 필수).
        """

        uba_id = int(user_broker_account_id)
        uba = self._session.get(UserBrokerAccount, uba_id)
        if uba is None:
            raise LiveUnattendedError("UBA_NOT_FOUND", "UBA not found")
        if str(uba.broker_code or "").upper() != "KIWOOM":
            raise LiveUnattendedError(
                "BROKER_NOT_SUPPORTED", "KIWOOM only"
            )

        consent = self.get_latest_authorization(uba_id)
        if system_next_day:
            if not _detail_flag(consent):
                raise LiveUnattendedError(
                    "NEXT_DAY_OPT_IN_OFF",
                    "next trading day auto-start is not enabled",
                )

        try:
            until = market_hours_authorized_until(self._session)
        except ValueError as exc:
            raise LiveUnattendedError(
                "MARKET_HOURS_NOT_AVAILABLE",
                f"Cannot reauthorize market-hours: {exc}",
            ) from exc

        mh_meta = krx_market_hours_state(self._session)
        gates = self._unattended.evaluate_restore_gates(uba_id)
        # MARKET_CLOSED는 이미 until 계산에서 걸림
        ignored = {"MARKET_CLOSED", "LIVE_OFF", "ARM_OFF", "ACTIVATION_INACTIVE"}
        blockers = [b for b in (gates.get("blockers") or []) if b not in ignored]
        if blockers:
            raise LiveUnattendedError(
                "SAFETY_GATES_FAILED",
                f"Cannot reauthorize: {blockers}",
            )

        now = _now()
        existing = self._unattended.get_active(uba_id)
        preserve_auto_renew = True
        preserve_next_day = True
        source_activation_id = None
        if consent is not None and consent.source_activation_id is not None:
            source_activation_id = int(consent.source_activation_id)
        if existing is not None:
            preserve_auto_renew = bool(
                getattr(existing, "auto_renew_enabled", True)
            )
            preserve_next_day = _detail_flag(existing) or _detail_flag(consent)
            if existing.source_activation_id is not None:
                source_activation_id = int(existing.source_activation_id)
            status_u = str(existing.status_code or "").upper()
            until_ex = aware_utc(existing.authorized_until)
            still_active = (
                status_u == STATUS_ACTIVE
                and bool(existing.entry_authorized)
                and until_ex is not None
                and until_ex > now
                and bool(uba.live_order_enabled)
                and bool(uba.live_armed)
            )
            if still_active:
                return {
                    "reauthorized": False,
                    "reason": "ALREADY_ACTIVE",
                    "authorization_id": int(
                        existing.live_unattended_authorization_id
                    ),
                }
            existing.enabled = False
            existing.entry_authorized = False
            existing.status_code = STATUS_EXPIRED
            existing.revoked_at = now
            existing.revoked_by = actor[:100]
            existing.revoke_reason = "SUPERSEDED_BY_NEXT_DAY_REAUTH"[:200]
            existing.updated_at = now
            self._session.flush()

        from stock_platform.broker.live_transition_service import (
            LiveTradingTransitionService,
        )
        from stock_platform.common.settings import get_settings

        act = LiveTradingTransitionService(self._session).peek_active(
            broker_code="KIWOOM",
            user_broker_account_id=uba_id,
        )
        if act is not None:
            source_activation_id = int(act.live_trading_transition_id)
        elif source_activation_id is None:
            raise LiveUnattendedError(
                "ACTIVATION_SECURITY_BOUNDARY",
                "No source Activation — cannot auto-create greenfield "
                "with ENABLE KIWOOM LIVE TRADING bypass",
            )

        settings = get_settings()
        hours = max(
            1, int((until - now).total_seconds() // 3600) or 1
        )
        corr = (correlation_id or f"kiwoom-next-day-{uba_id}-{int(now.timestamp())}")[
            :128
        ]
        row = LiveUnattendedAuthorizationEntity(
            user_broker_account_id=uba_id,
            broker_code="KIWOOM",
            status_code=STATUS_ACTIVE,
            enabled=True,
            entry_authorized=True,
            protective_exit_authorized=True,
            auto_renew_enabled=bool(preserve_auto_renew),
            authorized_until=until,
            renewal_interval_seconds=int(
                getattr(
                    settings, "live_unattended_renewal_interval_seconds", 3600
                )
            ),
            renewal_margin_seconds=int(
                getattr(
                    settings, "live_unattended_renewal_margin_seconds", 600
                )
            ),
            arm_lease_ttl_seconds=int(
                getattr(
                    settings, "live_unattended_arm_lease_ttl_seconds", 3600
                )
            ),
            activation_renew_hours=int(
                getattr(
                    settings, "live_unattended_activation_renew_hours", 8
                )
            ),
            max_authorization_horizon_hours=hours,
            approved_by=actor[:100],
            approved_at=now,
            approval_reason=(
                "KIWOOM_NEXT_TRADING_DAY_AUTO_START"
                if system_next_day
                else "KIWOOM_MARKET_HOURS_REAUTHORIZE"
            )[:2000],
            approval_phrase_hash=(
                # opt-in phrase digest — LIVE Activation phrase 아님
                __import__("hashlib")
                .sha256(
                    f"UNATTENDED_LEASE:{CONFIRM_ENABLE_MARKET_HOURS}".encode()
                )
                .hexdigest()
            ),
            source_activation_id=source_activation_id,
            last_renewal_detail={
                "correlation_id": corr,
                "source": "SYSTEM_NEXT_DAY" if system_next_day else "ADMIN",
                "authorization_mode": MODE_MARKET_HOURS,
                "market_hours": mh_meta,
                "next_trading_day_auto_start": bool(preserve_next_day),
                "gates": {"ok": True, "blockers": []},
            },
        )
        self._session.add(row)
        self._session.flush()

        # LIVE/ARM/Activation 복구 (공식 restore)
        restored = self._unattended.restore_from_active_lease(
            uba_id,
            actor=actor,
            restore_stack=False,
        )
        if not restored.get("restored"):
            # fail-closed: lease 유지하되 ENTRY 차단하지 않고 보고
            # (restore 실패 시 ARM/LIVE 없을 수 있음)
            self._write_lifecycle(
                row,
                phase=PHASE_BLOCKED,
                blockers=[str(restored.get("reason") or "RESTORE_FAILED")],
            )
            raise LiveUnattendedError(
                "RESTORE_FAILED",
                f"lease created but restore failed: {restored.get('reason')}",
            )

        # auto-renew ON 유지 (MARKET_HOURS ARM renew)
        if not bool(row.auto_renew_enabled):
            row.auto_renew_enabled = True
            self._session.flush()

        self._write_lifecycle(
            row,
            phase=PHASE_MARKET_HOURS_AUTHORIZE,
            extra={"restore": restored.get("detail")},
        )
        emit_live_safety_audit(
            self._session,
            event_type="KIWOOM_MARKET_HOURS_REAUTHORIZED",
            actor=actor,
            run_id=None,
            user_id=int(uba.user_id),
            account_id=uba_id,
            strategy_id=None,
            detail={
                "authorization_id": int(row.live_unattended_authorization_id),
                "authorized_until": until.isoformat(),
                "system_next_day": bool(system_next_day),
            },
            commit=False,
        )
        return {
            "reauthorized": True,
            "authorization_id": int(row.live_unattended_authorization_id),
            "authorized_until": until.isoformat(),
            "restore": restored,
            "auto_renew_enabled": bool(row.auto_renew_enabled),
        }

    # ------------------------------------------------------------------
    # Tick
    # ------------------------------------------------------------------

    def tick_uba(
        self,
        user_broker_account_id: int,
        *,
        actor: str = ACTOR_SYSTEM,
    ) -> dict[str, Any]:
        """단일 UBA lifecycle tick — idempotent."""

        uba_id = int(user_broker_account_id)
        uba = self._session.get(UserBrokerAccount, uba_id)
        if uba is None or str(uba.broker_code or "").upper() != "KIWOOM":
            return {"uba_id": uba_id, "skipped": True, "reason": "NOT_KIWOOM"}

        consent = self.get_latest_authorization(uba_id)
        if not _detail_flag(consent):
            return {
                "uba_id": uba_id,
                "skipped": True,
                "reason": "OPT_IN_OFF",
            }

        assert consent is not None
        mh = krx_market_hours_state(self._session)
        active = self._unattended.get_active(uba_id)
        result: dict[str, Any] = {
            "uba_id": uba_id,
            "market": {
                "is_trading_day": mh.get("is_trading_day"),
                "in_regular_session": mh.get("in_regular_session"),
                "past_close": mh.get("past_close"),
                "before_open": mh.get("before_open"),
            },
        }

        # --- EOD / non-trading ---
        if not mh.get("is_trading_day"):
            phase = PHASE_SAFE_IDLE
            self._write_lifecycle(consent, phase=phase)
            result.update({"phase": phase, "action": "WAIT_TRADING_DAY"})
            return result

        if mh.get("past_close"):
            # 기존 EOD expire는 scan_renew_and_expire가 담당 — 여기서는 상태만
            if active is not None and str(active.status_code) == STATUS_PROTECTIVE:
                phase = PHASE_PROTECTIVE_EXIT_ONLY
            elif active is not None and str(active.status_code) == STATUS_ACTIVE:
                phase = PHASE_MARKET_CLOSE
            else:
                phase = PHASE_SAFE_IDLE
            self._write_lifecycle(consent, phase=phase)
            if phase in {PHASE_MARKET_CLOSE, PHASE_SAFE_IDLE}:
                self._emit_lifecycle_telegram(
                    uba_id=uba_id,
                    event_type="KIWOOM_EOD_AUTO_STOP",
                    title="장 마감 자동매매 종료",
                    message=(
                        f"⏹ 장 마감 자동매매 종료\n"
                        f"계좌: UBA {uba_id}\n"
                        f"상태: {phase}\n"
                        "신규 진입 차단 · ARM 갱신 금지"
                    ),
                    row=consent,
                )
            result.update({"phase": phase, "action": "EOD_IDLE"})
            return result

        if mh.get("before_open"):
            self._write_lifecycle(consent, phase=PHASE_WAITING_MARKET)
            result.update(
                {"phase": PHASE_WAITING_MARKET, "action": "WAIT_OPEN"}
            )
            return result

        # --- Regular session ---
        lease_entry_alive = (
            active is not None
            and str(active.status_code) == STATUS_ACTIVE
            and bool(active.entry_authorized)
            and aware_utc(active.authorized_until) is not None
            and aware_utc(active.authorized_until) > _now()  # type: ignore[operator]
        )
        trading_armed = bool(uba.live_order_enabled) and bool(uba.live_armed)

        if lease_entry_alive and trading_armed:
            # 이미 TRADING — stack idempotent ensure (restart 후 runner 복구)
            self._schedule_stack_restore(uba_id, actor=f"{actor}_STACK")
            self._write_lifecycle(consent, phase=PHASE_TRADING)
            result.update({"phase": PHASE_TRADING, "action": "ENSURE_STACK"})
            return result

        if lease_entry_alive and not trading_armed:
            # 장중 backend restart: ACTIVE lease 유지 + account sync 후 restore
            precheck = self.evaluate_auto_start_precheck(uba_id)
            hard = [
                b
                for b in (precheck.get("blockers") or [])
                if b not in {"NEXT_DAY_OPT_IN_OFF", "MARKET_SESSION_NOT_OPEN"}
            ]
            if hard:
                self._write_lifecycle(
                    consent,
                    phase=PHASE_BLOCKED,
                    blockers=hard,
                    precheck=precheck,
                )
                result.update(
                    {
                        "phase": PHASE_BLOCKED,
                        "action": "FAIL_CLOSED_RESTART",
                        "precheck": precheck,
                    }
                )
                return result
            pipeline = self._schedule_auto_start_pipeline(
                uba_id, actor=actor, mode="RESTART_RESTORE"
            )
            self._write_lifecycle(consent, phase=PHASE_ACCOUNT_SYNC)
            result.update(
                {
                    "phase": PHASE_ACCOUNT_SYNC,
                    "action": "RESTART_PIPELINE_SCHEDULED",
                    "pipeline": pipeline,
                }
            )
            return result

        # Auto start path (overnight / no ACTIVE entry lease)
        self._write_lifecycle(consent, phase=PHASE_PRECHECK)
        self._emit_lifecycle_telegram(
            uba_id=uba_id,
            event_type="KIWOOM_AUTO_START_PREPARING",
            title="키움 장 시작 자동매매 준비 중",
            message=(
                f"🔄 키움 장 시작 자동매매 준비 중\n"
                f"계좌: UBA {uba_id}\n"
                f"거래일: {mh.get('calendar_date')}"
            ),
            row=consent,
        )

        precheck = self.evaluate_auto_start_precheck(uba_id)
        if not precheck["ok"]:
            self._write_lifecycle(
                consent,
                phase=PHASE_BLOCKED,
                blockers=list(precheck.get("blockers") or []),
                precheck=precheck,
            )
            blockers = list(precheck.get("blockers") or [])
            self._emit_lifecycle_telegram(
                uba_id=uba_id,
                event_type="KIWOOM_AUTO_START_BLOCKED",
                title="자동 시작 차단",
                message=(
                    f"⛔ 자동 시작 차단\n"
                    f"계좌: UBA {uba_id}\n"
                    f"사유: {', '.join(blockers[:6]) or 'UNKNOWN'}"
                ),
                detail={"blockers": blockers},
                row=consent,
            )
            result.update(
                {
                    "phase": PHASE_BLOCKED,
                    "action": "FAIL_CLOSED",
                    "precheck": precheck,
                }
            )
            return result

        self._write_lifecycle(
            consent,
            phase=PHASE_ACCOUNT_SYNC,
            precheck=precheck,
        )
        # LIVE/ARM 전에 실제 account state sync → reauth → stack (async pipeline)
        pipeline = self._schedule_auto_start_pipeline(
            uba_id, actor=actor, mode="OVERNIGHT_START"
        )
        result.update(
            {
                "phase": PHASE_ACCOUNT_SYNC,
                "action": "PIPELINE_SCHEDULED",
                "pipeline": pipeline,
                "precheck": precheck,
            }
        )
        return result

    def preview_next_session(
        self, user_broker_account_id: int
    ) -> dict[str, Any]:
        """다음 거래일 startup dry preview — LIVE mutation 없음."""

        uba_id = int(user_broker_account_id)
        mh = krx_market_hours_state(self._session)
        status = self.status_dict(uba_id)
        precheck = self.evaluate_auto_start_precheck(uba_id)

        # 다음 거래일 / open / close
        next_meta: dict[str, Any] = {}
        try:
            from datetime import time as time_cls
            from zoneinfo import ZoneInfo

            from stock_platform.operation.calendar_repository import (
                TradingCalendarRepository,
            )
            from stock_platform.operation.calendar_service import (
                TradingCalendarService,
            )

            cal = TradingCalendarService(
                TradingCalendarRepository(self._session)
            )
            today = datetime.now(ZoneInfo("Asia/Seoul")).date()
            if mh.get("is_trading_day") and mh.get("before_open"):
                nxt = today
            elif mh.get("is_trading_day") and mh.get("in_regular_session"):
                nxt = today
            else:
                nxt = cal.next_trading_day(
                    exchange_code="KRX", calendar_date=today
                )
            decision = cal.evaluate(exchange_code="KRX", calendar_date=nxt)
            open_t = decision.regular_open_at or time_cls(9, 0)
            close_t = decision.regular_close_at or time_cls(15, 30)
            open_kst = datetime.combine(
                nxt, open_t, tzinfo=ZoneInfo("Asia/Seoul")
            )
            close_kst = datetime.combine(
                nxt, close_t, tzinfo=ZoneInfo("Asia/Seoul")
            )
            next_meta = {
                "next_trading_date": nxt.isoformat(),
                "expected_market_open_kst": open_kst.isoformat(),
                "expected_market_close_kst": close_kst.isoformat(),
                "expected_market_open_utc": open_kst.astimezone(
                    timezone.utc
                ).isoformat(),
                "expected_market_close_utc": close_kst.astimezone(
                    timezone.utc
                ).isoformat(),
                "is_trading_day": bool(decision.is_trading_day),
                "holiday_name": decision.holiday_name,
            }
        except Exception as exc:  # noqa: BLE001
            next_meta = {"error": type(exc).__name__}

        opt_in = bool(status.get("next_trading_day_auto_start"))
        source_ok = status.get("source_activation_id") is not None
        steps = [
            PHASE_WAITING_MARKET,
            PHASE_PRECHECK,
            PHASE_ACCOUNT_SYNC,
            PHASE_FEED_START,
            PHASE_WARMUP,
            PHASE_ACTIVATION_CHECK,
            PHASE_LIVE_ENABLE,
            PHASE_MARKET_HOURS_AUTHORIZE,
            PHASE_ARM_ENABLE,
            PHASE_RUNTIME_RESUME,
            PHASE_RUNNER_START,
            PHASE_TRADING,
        ]
        blockers = list(precheck.get("blockers") or [])
        # 장 마감 시점 preview: MARKET_SESSION_NOT_OPEN 은 EXPECTED (다음날 해소)
        expected_now = {
            "NOT_KRX_TRADING_DAY",
            "MARKET_SESSION_NOT_OPEN",
        }
        hard = [b for b in blockers if b not in expected_now]

        step_status: list[dict[str, Any]] = []
        for step in steps:
            if not opt_in:
                st = "BLOCKED"
                note = "NEXT_DAY_OPT_IN_OFF"
            elif hard:
                st = "BLOCKED"
                note = ",".join(hard[:4])
            elif step == PHASE_WAITING_MARKET:
                st = "EXPECTED"
                note = "until_next_open"
            elif step == PHASE_PRECHECK:
                st = "EXPECTED" if not hard else "BLOCKED"
                note = "re-evaluate_at_open"
            elif step == PHASE_ACCOUNT_SYNC:
                st = "EXPECTED"
                note = "live_kiwoom_account_state_sync_at_start"
            elif step == PHASE_ACTIVATION_CHECK:
                st = "READY" if source_ok else "BLOCKED"
                note = (
                    "successor_from_source"
                    if source_ok
                    else "ACTIVATION_SECURITY_BOUNDARY"
                )
            else:
                st = "EXPECTED"
                note = "after_prior_gates"
            step_status.append(
                {"step": step, "status": st, "note": note}
            )

        return {
            "user_broker_account_id": uba_id,
            "mutation": False,
            "current_market": mh,
            "next_session": next_meta,
            "opt_in": opt_in,
            "source_activation_id": status.get("source_activation_id"),
            "successor_eligible": bool(source_ok and opt_in and not hard),
            "greenfield_bypass": False,
            "precheck": {
                "ok": precheck.get("ok"),
                "blockers": blockers,
                "hard_blockers": hard,
                "expected_until_open": [
                    b for b in blockers if b in expected_now
                ],
                "gate_count": precheck.get("gate_count"),
            },
            "steps": step_status,
            "account_sync_at_start": "LIVE_KIWOOM_ACCOUNT_STATE_SYNC",
            "live": status.get("live"),
            "arm": status.get("arm"),
        }

    def _schedule_auto_start_pipeline(
        self,
        user_broker_account_id: int,
        *,
        actor: str,
        mode: str,
    ) -> dict[str, Any]:
        """Account sync → MARKET_HOURS reauth/restore → stack (idempotent)."""

        import asyncio
        import threading

        uba_id = int(user_broker_account_id)

        async def _run() -> None:
            from stock_platform.database.session import get_session_factory
            from stock_platform.trading.kiwoom_unattended_stack_restore import (
                restore_kiwoom_trading_stack,
                sync_kiwoom_account_state_for_startup,
            )

            sf = get_session_factory()
            session = sf()
            try:
                life = KiwoomTradingDayLifecycleService(session)
                consent = life.get_latest_authorization(uba_id)
                if consent is None or not _detail_flag(consent):
                    return

                # 1) 실제 계좌 동기화
                life._write_lifecycle(consent, phase=PHASE_ACCOUNT_SYNC)
                sync = await sync_kiwoom_account_state_for_startup(
                    session, user_broker_account_id=uba_id
                )
                if not sync.get("ok"):
                    life._write_lifecycle(
                        consent,
                        phase=PHASE_BLOCKED,
                        blockers=[
                            str(sync.get("reason") or "ACCOUNT_SYNC_FAILED")
                        ],
                        extra={"account_sync": sync},
                    )
                    life._emit_lifecycle_telegram(
                        uba_id=uba_id,
                        event_type="KIWOOM_AUTO_START_BLOCKED",
                        title="자동 시작 차단",
                        message=(
                            f"⛔ 자동 시작 차단\n"
                            f"계좌: UBA {uba_id}\n"
                            f"사유: ACCOUNT_SYNC — "
                            f"{sync.get('reason')}"
                        ),
                        detail=sync,
                        row=consent,
                    )
                    session.commit()
                    return

                life._emit_lifecycle_telegram(
                    uba_id=uba_id,
                    event_type="KIWOOM_ACCOUNT_SYNC_OK",
                    title="계좌 동기화 완료",
                    message=(
                        f"✅ 계좌 동기화 완료\n"
                        f"계좌: UBA {uba_id}\n"
                        f"미체결: {sync.get('pending_order_count')}"
                    ),
                    detail={"pending_order_count": sync.get("pending_order_count")},
                    row=consent,
                )

                # 2) Activation/LIVE/MARKET_HOURS/ARM
                life._write_lifecycle(consent, phase=PHASE_ACTIVATION_CHECK)
                if mode == "RESTART_RESTORE":
                    restored = life._unattended.restore_from_active_lease(
                        uba_id, actor=actor, restore_stack=False
                    )
                    if not restored.get("restored"):
                        life._write_lifecycle(
                            consent,
                            phase=PHASE_BLOCKED,
                            blockers=[
                                str(
                                    restored.get("reason") or "RESTORE_FAILED"
                                )
                            ],
                        )
                        session.commit()
                        return
                else:
                    try:
                        life.reauthorize_market_hours_for_trading_day(
                            uba_id,
                            actor=actor,
                            system_next_day=True,
                            correlation_id=f"next-day-{uba_id}",
                        )
                    except LiveUnattendedError as exc:
                        life._write_lifecycle(
                            consent,
                            phase=PHASE_BLOCKED,
                            blockers=[exc.code],
                        )
                        life._emit_lifecycle_telegram(
                            uba_id=uba_id,
                            event_type="KIWOOM_AUTO_START_BLOCKED",
                            title="자동 시작 차단",
                            message=(
                                f"⛔ 자동 시작 차단\n"
                                f"계좌: UBA {uba_id}\n"
                                f"사유: {exc.code}"
                            ),
                            detail={"code": exc.code},
                            row=consent,
                        )
                        session.commit()
                        return

                # 3) Feed / runtime / runner
                life._write_lifecycle(consent, phase=PHASE_FEED_START)
                stack = await restore_kiwoom_trading_stack(
                    session,
                    user_broker_account_id=uba_id,
                    actor=f"{actor}_STACK",
                )
                phase = (
                    PHASE_TRADING
                    if stack.get("restored")
                    else PHASE_BLOCKED
                )
                life._write_lifecycle(
                    consent,
                    phase=phase,
                    blockers=(
                        []
                        if stack.get("restored")
                        else [str(stack.get("reason") or "STACK_FAILED")]
                    ),
                    extra={"stack": stack.get("reason"), "account_sync": sync},
                )
                if stack.get("restored"):
                    life._emit_lifecycle_telegram(
                        uba_id=uba_id,
                        event_type="KIWOOM_AUTO_START_STARTED",
                        title="키움 자동매매 시작",
                        message=(
                            f"🚀 키움 자동매매 시작\n"
                            f"계좌: UBA {uba_id}\n"
                            "lease ACTIVE · LIVE/ARM ON · stack OK"
                        ),
                        row=consent,
                    )
                    life._emit_lifecycle_telegram(
                        uba_id=uba_id,
                        event_type="KIWOOM_FEED_CONNECTED",
                        title="실시간 시세 연결 완료",
                        message=(
                            f"✅ 실시간 시세 연결 완료\n계좌: UBA {uba_id}"
                        ),
                        row=consent,
                    )
                session.commit()
                logger.info(
                    "kiwoom_auto_start_pipeline_done",
                    uba_id=uba_id,
                    mode=mode,
                    phase=phase,
                    stack_restored=stack.get("restored"),
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "kiwoom_auto_start_pipeline_failed",
                    uba_id=uba_id,
                    error=type(exc).__name__,
                )
                try:
                    session.rollback()
                except Exception:  # noqa: BLE001
                    pass
            finally:
                session.close()

        try:
            loop = asyncio.get_running_loop()
            loop.create_task(_run())
            return {"scheduled": True, "mode": "asyncio", "pipeline": mode}
        except RuntimeError:
            threading.Thread(
                target=lambda: asyncio.run(_run()),
                name=f"kiwoom-autostart-{uba_id}",
                daemon=True,
            ).start()
            return {"scheduled": True, "mode": "thread", "pipeline": mode}

    def _schedule_stack_restore(
        self, user_broker_account_id: int, *, actor: str
    ) -> dict[str, Any]:
        import asyncio
        import threading

        uba_id = int(user_broker_account_id)

        async def _run() -> None:
            from stock_platform.database.session import get_session_factory
            from stock_platform.trading.kiwoom_unattended_stack_restore import (
                restore_kiwoom_trading_stack,
            )

            sf = get_session_factory()
            session = sf()
            try:
                result = await restore_kiwoom_trading_stack(
                    session,
                    user_broker_account_id=uba_id,
                    actor=actor,
                )
                session.commit()
                logger.info(
                    "kiwoom_stack_restore_done",
                    uba_id=uba_id,
                    restored=result.get("restored"),
                    reason=result.get("reason"),
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "kiwoom_stack_restore_failed",
                    uba_id=uba_id,
                    error=type(exc).__name__,
                )
                try:
                    session.rollback()
                except Exception:  # noqa: BLE001
                    pass
            finally:
                session.close()

        try:
            loop = asyncio.get_running_loop()
            loop.create_task(_run())
            return {"scheduled": True, "mode": "asyncio"}
        except RuntimeError:
            threading.Thread(
                target=lambda: asyncio.run(_run()),
                name=f"kiwoom-stack-{uba_id}",
                daemon=True,
            ).start()
            return {"scheduled": True, "mode": "thread"}

    def scan_all(self, *, actor: str = ACTOR_SYSTEM) -> dict[str, Any]:
        """Expiry scanner 훅 — opted-in KIWOOM UBA만."""

        results = []
        for uba_id in self.list_opted_in_uba_ids():
            try:
                results.append(self.tick_uba(uba_id, actor=actor))
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "kiwoom_lifecycle_tick_failed",
                    uba_id=uba_id,
                    error=type(exc).__name__,
                )
                results.append(
                    {
                        "uba_id": uba_id,
                        "phase": PHASE_BLOCKED,
                        "error": type(exc).__name__,
                    }
                )
        return {
            "scanned": len(results),
            "results": results,
            "actor": actor,
        }
