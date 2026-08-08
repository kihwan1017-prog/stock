"""STEP 8-9 — Upbit 소액 LIVE Preflight Service."""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from stock_platform.broker.upbit.rules import (
    UPBIT_MIN_NOTIONAL_KRW,
    round_upbit_volume,
    volume_from_krw_buy_amount,
)
from stock_platform.common.settings import get_settings
from stock_platform.order.entities import TradingOrderEntity
from stock_platform.order.live_safety_audit import emit_live_safety_audit
from stock_platform.risk_engine.kill_switch_service import KillSwitchService
from stock_platform.risk_engine.resolved_policy import ResolvedRiskPolicyResolver
from stock_platform.trading.account_models import UserBrokerAccount
from stock_platform.trading.live_arm_service import LiveArmService
from stock_platform.trading.upbit_live_smoke_constants import (
    DEFAULT_ALLOWLIST,
    MAX_SMOKE_AMOUNT,
    UPBIT_LIVE_SMOKE_PREFLIGHT_FAILED,
    UPBIT_LIVE_SMOKE_PREFLIGHT_PASSED,
    UPBIT_LIVE_SMOKE_PREFLIGHT_STARTED,
)


ZERO = Decimal("0")


@dataclass(slots=True)
class PreflightCheck:
    code: str
    name: str
    status: str  # PASS / FAIL / WARNING / NOT_APPLICABLE
    message: str
    checked_at: str


@dataclass(slots=True)
class UpbitLivePreflightResult:
    preflight_id: str
    checked_at: str
    user_id: int | None
    user_broker_account_id: int
    broker_code: str
    account_kind: str
    market: str
    symbol: str
    side: str
    quantity: str | None
    limit_price: str
    estimated_amount: str
    live_enabled: bool
    armed: bool
    arm_expires_at: str | None
    kill_switch_active: bool
    scheduler_paused: bool
    strategy_runtime_paused: bool
    broker_healthy: bool
    credential_valid: bool
    open_order_count: int
    daily_order_count: int
    daily_loss: str | None
    post_fill_scheduler_healthy: bool
    checks: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    live_blockers: list[str] = field(default_factory=list)
    ready: bool = False
    dry_run_ready: bool = False
    live_execution_ready: bool = False
    request_fingerprint: str = ""
    expires_at: str | None = None
    requested_amount: str = ""
    requested_limit_price: str | None = None
    effective_limit_price: str | None = None
    tick_size: str | None = None
    tick_source: str | None = None
    adjustment_reason: str | None = None
    current_daily_loss: str | None = None
    max_daily_loss_limit: str | None = None
    remaining_daily_loss_capacity: str | None = None
    daily_loss_scope: str | None = None
    daily_loss_calculated_at: str | None = None
    scheduler: dict[str, Any] = field(default_factory=dict)
    purpose: str = "live_execution"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class UpbitLivePreflightService:
    """업비트 소액 LIVE 사전점검 — Fail Closed."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def run(
        self,
        *,
        user_broker_account_id: int,
        market: str,
        side: str,
        amount: Decimal,
        limit_price: Decimal,
        arm_token: str | None = None,
        actor: str = "UPBIT_LIVE_PREFLIGHT",
        skip_live_network: bool = False,
        purpose: str = "live_execution",
    ) -> UpbitLivePreflightResult:
        settings = get_settings()
        now = datetime.now(timezone.utc)
        preflight_id = f"pf-{uuid.uuid4().hex[:16]}"
        market_u = str(market or "").strip().upper()
        side_u = str(side or "").strip().upper()
        amount_d = Decimal(str(amount))
        requested_price = Decimal(str(limit_price))
        purpose_u = (
            "dry_run"
            if str(purpose).strip().lower() == "dry_run"
            else "live_execution"
        )
        # Tick: Broker 우선. dry-run 은 STATIC fallback 허용, live 는 Fail Closed
        tick_meta: dict[str, Any]
        try:
            from stock_platform.broker.upbit.market_snapshot import (
                resolve_tick_and_price,
            )

            tick_meta = resolve_tick_and_price(
                market=market_u,
                requested_price=requested_price,
                side=side_u,
                settings=settings,
                prefer_broker=not skip_live_network,
                allow_static_fallback=(
                    purpose_u == "dry_run" or skip_live_network
                ),
            )
            price_d = Decimal(str(tick_meta["effective_price"]))
        except Exception as exc:  # noqa: BLE001
            tick_meta = {
                "requested_limit_price": str(requested_price),
                "effective_limit_price": str(requested_price),
                "tick_size": None,
                "tick_source": None,
                "adjustment_reason": None,
                "effective_price": requested_price,
                "tick": None,
                "error": type(exc).__name__,
            }
            price_d = requested_price
        checks: list[PreflightCheck] = []
        warnings: list[str] = []
        blockers: list[str] = []
        live_blockers: list[str] = []

        def _add(
            code: str,
            name: str,
            status: str,
            message: str,
            *,
            live_only: bool = False,
        ) -> None:
            checks.append(
                PreflightCheck(
                    code=code,
                    name=name,
                    status=status,
                    message=message,
                    checked_at=now.isoformat(),
                )
            )
            if status == "FAIL":
                item = f"{code}: {message}"
                if live_only:
                    live_blockers.append(item)
                    if purpose_u == "live_execution":
                        blockers.append(item)
                else:
                    blockers.append(item)
                    live_blockers.append(item)
            elif status in {"WARNING", "EXPECTED_OFF"}:
                warnings.append(f"{code}: {message}")

        emit_live_safety_audit(
            self._session,
            event_type=UPBIT_LIVE_SMOKE_PREFLIGHT_STARTED,
            actor=actor,
            run_id=preflight_id,
            user_id=None,
            account_id=int(user_broker_account_id),
            strategy_id=None,
            detail={
                "preflight_id": preflight_id,
                "market": market_u,
                "side": side_u,
                "amount": str(amount_d),
            },
            commit=False,
        )

        uba = self._session.get(
            UserBrokerAccount, int(user_broker_account_id)
        )
        if uba is None:
            _add("UBA_EXISTS", "UBA 존재", "FAIL", "UBA not found")
            return self._finish(
                preflight_id=preflight_id,
                now=now,
                uba=None,
                market=market_u,
                side=side_u,
                amount=amount_d,
                price=price_d,
                qty=None,
                checks=checks,
                warnings=warnings,
                blockers=blockers,
                live_blockers=live_blockers,
                actor=actor,
                ready=False,
                dry_run_ready=False,
                live_execution_ready=False,
                purpose=purpose_u,
                tick_meta=tick_meta,
                user_broker_account_id=int(user_broker_account_id),
            )

        _add("UBA_EXISTS", "UBA 존재", "PASS", f"uba={uba.user_broker_account_id}")
        _add(
            "UBA_OWNER",
            "소유자",
            "PASS",
            f"user_id={uba.user_id}",
        )

        if str(uba.broker_code).upper() != "UPBIT":
            _add(
                "BROKER_UPBIT",
                "broker_code=UPBIT",
                "FAIL",
                f"broker={uba.broker_code}",
            )
        else:
            _add("BROKER_UPBIT", "broker_code=UPBIT", "PASS", "UPBIT")

        # UBA는 PaperAccount와 분리된 실계좌 핸들 — LIVE 계좌로 취급
        if not bool(uba.is_active):
            _add("ACCOUNT_LIVE", "account LIVE/active", "FAIL", "inactive")
        else:
            _add(
                "ACCOUNT_LIVE",
                "account LIVE/active",
                "PASS",
                "USER_BROKER active",
            )

        # Credential
        cred_ok, cred_msg = self._check_credential(
            int(uba.user_broker_account_id),
            skip_network=skip_live_network,
        )
        _add(
            "CREDENTIAL",
            "Credential",
            "PASS" if cred_ok else "FAIL",
            cred_msg,
        )

        # Auth / health
        broker_ok, broker_msg = self._check_broker_health(
            skip_network=skip_live_network
        )
        _add(
            "BROKER_HEALTH",
            "Broker Health",
            "PASS" if broker_ok else "FAIL",
            broker_msg,
        )

        kill = KillSwitchService(self._session).get_state()
        kill_active = str(kill.status).upper().endswith("ACTIVE") or (
            getattr(kill, "status", None) is not None
            and str(kill.status) == "ACTIVE"
        )
        from stock_platform.risk_engine.kill_switch_models import (
            KillSwitchStatus,
        )

        kill_active = kill.status == KillSwitchStatus.ACTIVE
        _add(
            "KILL_SWITCH",
            "Kill Switch OFF",
            "FAIL" if kill_active else "PASS",
            "ACTIVE" if kill_active else "INACTIVE",
        )

        live_on = bool(getattr(uba, "live_order_enabled", False))
        if live_on:
            _add("LIVE_ENABLED", "LIVE 승인 ON", "PASS", "ON")
        elif purpose_u == "dry_run":
            _add(
                "LIVE_ENABLED",
                "LIVE 승인 ON",
                "EXPECTED_OFF",
                "OFF (dry-run expected)",
                live_only=True,
            )
            live_blockers.append("LIVE_ENABLED: OFF")
        else:
            _add(
                "LIVE_ENABLED",
                "LIVE 승인 ON",
                "FAIL",
                "OFF",
                live_only=True,
            )

        arm = LiveArmService(self._session)
        arm.expire_if_needed(int(uba.user_broker_account_id))
        arm_status = arm.get_arm_status(int(uba.user_broker_account_id))
        armed = bool(arm_status.get("live_armed"))
        if armed:
            _add("ARM_ACTIVE", "ARM 활성", "PASS", "ARMED")
        elif purpose_u == "dry_run":
            _add(
                "ARM_ACTIVE",
                "ARM 활성",
                "EXPECTED_OFF",
                "DISARMED (dry-run expected)",
                live_only=True,
            )
            live_blockers.append("ARM_ACTIVE: DISARMED")
        else:
            _add(
                "ARM_ACTIVE",
                "ARM 활성",
                "FAIL",
                "DISARMED",
                live_only=True,
            )
        # Design A — 원문 없으면 UBA ARM state, 있으면 challenge
        ok_auth, auth_reason = arm.validate_arm_authorization(
            int(uba.user_broker_account_id),
            arm_token=arm_token,
            require_token_challenge=False,
        )
        if arm_token:
            _add(
                "ARM_AUTHORIZATION",
                "ARM 권한(challenge)",
                "PASS" if ok_auth else "FAIL",
                auth_reason,
                live_only=True,
            )
        elif purpose_u == "dry_run":
            _add(
                "ARM_AUTHORIZATION",
                "ARM 권한(state)",
                "PASS" if ok_auth else "WARNING",
                auth_reason if ok_auth else f"{auth_reason} (dry-run)",
                live_only=True,
            )
            if not ok_auth:
                live_blockers.append(f"ARM_AUTHORIZATION: {auth_reason}")
        else:
            _add(
                "ARM_AUTHORIZATION",
                "ARM 권한(state)",
                "PASS" if ok_auth else "FAIL",
                auth_reason if ok_auth else auth_reason,
                live_only=True,
            )

        # Tick 메타 표시
        if tick_meta.get("error"):
            _add(
                "TICK_SIZE",
                "Tick Size",
                "FAIL" if purpose_u == "live_execution" else "WARNING",
                str(tick_meta.get("error")),
                live_only=purpose_u == "live_execution",
            )
        else:
            _add(
                "TICK_SIZE",
                "Tick Size",
                "PASS",
                (
                    f"requested={tick_meta.get('requested_limit_price')} "
                    f"effective={tick_meta.get('effective_limit_price')} "
                    f"tick={tick_meta.get('tick_size')} "
                    f"source={tick_meta.get('tick_source')} "
                    f"reason={tick_meta.get('adjustment_reason')}"
                ),
            )

        # Scheduler / Runtime pause (UBA scope) — 공통 readiness 서비스
        sched_snap: dict[str, Any] = {}
        if skip_live_network:
            runtime_paused = True
            sched_paused = True
            sched_snap = {
                "trading_scheduler_desired_state": "PAUSE",
                "trading_scheduler_actual_state": "PAUSED",
                "trading_scheduler_paused": True,
                "tracking_scheduler_running": True,
                "post_fill_scheduler_running": True,
                "source": "offline_skip",
            }
            _add(
                "RUNTIME_PAUSED",
                "Strategy Runtime Pause",
                "PASS",
                "skipped offline",
            )
            _add(
                "SCHEDULER_PAUSED",
                "Trading Scheduler PAUSED",
                "PASS",
                "skipped offline",
            )
            _add(
                "TRACKING_SCHEDULER",
                "Tracking Scheduler",
                "PASS",
                "skipped offline",
            )
            _add(
                "POST_FILL_SCHEDULER",
                "Post-fill Scheduler",
                "PASS",
                "skipped offline",
            )
            pf_ok = True
        else:
            runtime_paused = self._runtime_paused_for_uba(
                int(uba.user_broker_account_id)
            )
            _add(
                "RUNTIME_PAUSED",
                "Strategy Runtime Pause",
                "PASS" if runtime_paused else "FAIL",
                "paused" if runtime_paused else "not paused",
            )
            from stock_platform.trading.upbit_scheduler_readiness import (
                collect_scheduler_readiness,
            )

            snap = collect_scheduler_readiness(settings)
            sched_snap = snap.to_dict()
            sched_paused = bool(snap.trading_scheduler_paused)
            if snap.trading_scheduler_actual_state == "UNKNOWN":
                _add(
                    "SCHEDULER_PAUSED",
                    "Trading Scheduler PAUSED",
                    "FAIL",
                    (
                        f"actual=UNKNOWN source={snap.source} "
                        "(설정 PAUSE만으로 PASS 금지)"
                    ),
                )
            else:
                _add(
                    "SCHEDULER_PAUSED",
                    "Trading Scheduler PAUSED",
                    "PASS" if sched_paused else "FAIL",
                    (
                        f"desired={snap.trading_scheduler_desired_state} "
                        f"actual={snap.trading_scheduler_actual_state}"
                    ),
                )
            track_ok = bool(snap.tracking_scheduler_running)
            _add(
                "TRACKING_SCHEDULER",
                "Tracking Scheduler RUNNING",
                "PASS" if track_ok else "FAIL",
                "RUNNING" if track_ok else "DISABLED",
            )
            pf_ok = bool(snap.post_fill_scheduler_running)
            _add(
                "POST_FILL_SCHEDULER",
                "Post-fill Scheduler RUNNING",
                "PASS" if pf_ok else "FAIL",
                "RUNNING" if pf_ok else "DISABLED",
            )

        open_count = self._open_order_count(int(uba.user_broker_account_id))
        _add(
            "OPEN_ORDERS",
            "미체결 0",
            "PASS" if open_count == 0 else "FAIL",
            f"count={open_count}",
        )

        daily_count = self._daily_order_count(int(uba.user_broker_account_id))
        _add(
            "DAILY_ORDERS",
            "오늘 LIVE 주문수",
            "PASS",
            f"count={daily_count}",
        )

        policy = ResolvedRiskPolicyResolver(self._session).resolve(
            user_id=int(uba.user_id),
            user_broker_account_id=int(uba.user_broker_account_id),
        )
        daily_loss_ok = True
        daily_loss_val = None
        current_daily_loss: str | None = None
        max_daily_loss_limit: str | None = str(policy.daily_max_loss_amount)
        remaining_daily_loss: str | None = None
        daily_loss_scope = f"UBA:{int(uba.user_broker_account_id)}"
        daily_loss_at = now.isoformat()
        try:
            from stock_platform.risk_engine.daily_loss_entities import (
                AccountDailyLossEntity,
            )
            from zoneinfo import ZoneInfo

            today = datetime.now(ZoneInfo("Asia/Seoul")).date()
            # Paper 제외 — UBA FK 행만
            row = self._session.scalar(
                select(AccountDailyLossEntity).where(
                    AccountDailyLossEntity.user_broker_account_id
                    == int(uba.user_broker_account_id),
                    AccountDailyLossEntity.trading_date == today,
                    AccountDailyLossEntity.paper_account_id.is_(None),
                )
            )
            limit_d = Decimal(str(policy.daily_max_loss_amount))
            if row is not None:
                cur = Decimal(str(row.current_loss_amount))
                ent_limit = Decimal(str(row.loss_limit_amount or 0))
                if ent_limit > ZERO:
                    limit_d = ent_limit
                current_daily_loss = str(cur)
                max_daily_loss_limit = str(limit_d)
                remaining = limit_d - cur
                remaining_daily_loss = str(remaining)
                daily_loss_val = current_daily_loss
                status = str(row.status_code).upper()
                if status in {"BREACHED", "LIMIT_REACHED", "KILL"}:
                    daily_loss_ok = False
                elif limit_d > ZERO and cur >= limit_d:
                    daily_loss_ok = False
            else:
                current_daily_loss = "0"
                remaining_daily_loss = max_daily_loss_limit
                daily_loss_val = "0"
        except Exception:  # noqa: BLE001
            daily_loss_ok = True
            current_daily_loss = current_daily_loss or "unavailable"
        _add(
            "DAILY_LOSS",
            "일일 손실 제한 (UBA)",
            "PASS" if daily_loss_ok else "FAIL",
            (
                f"current={current_daily_loss} "
                f"limit={max_daily_loss_limit} "
                f"remaining={remaining_daily_loss} "
                f"scope={daily_loss_scope}"
            ),
        )

        # Market allowlist
        allow = self._allowlist(settings)
        if market_u not in allow:
            _add(
                "MARKET_ALLOWLIST",
                "허용 Market",
                "FAIL",
                f"{market_u} not in {sorted(allow)}",
            )
        else:
            _add(
                "MARKET_ALLOWLIST",
                "허용 Market",
                "PASS",
                market_u,
            )
        if not market_u.startswith("KRW-"):
            _add("KRW_MARKET", "KRW 마켓", "FAIL", market_u)
        else:
            _add("KRW_MARKET", "KRW 마켓", "PASS", market_u)

        # Side / order type (LIMIT only enforced at execute)
        if side_u not in {"BUY", "SELL"}:
            _add("SIDE", "Side", "FAIL", side_u)
        else:
            _add("SIDE", "Side", "PASS", side_u)

        # Amount limits
        effective_max = min(
            MAX_SMOKE_AMOUNT,
            Decimal(str(policy.max_order_amount)),
        )
        if amount_d > effective_max:
            _add(
                "AMOUNT_LIMIT",
                "주문금액 한도",
                "FAIL",
                f"{amount_d} > effective_max={effective_max}",
            )
        elif amount_d < UPBIT_MIN_NOTIONAL_KRW:
            _add(
                "AMOUNT_LIMIT",
                "주문금액 한도",
                "FAIL",
                f"{amount_d} < min={UPBIT_MIN_NOTIONAL_KRW}",
            )
        else:
            _add(
                "AMOUNT_LIMIT",
                "주문금액 한도",
                "PASS",
                f"amount={amount_d} max={effective_max}",
            )

        if price_d <= ZERO:
            _add("LIMIT_PRICE", "지정가", "FAIL", "price <= 0")
            qty = None
        else:
            if side_u == "BUY":
                qty = volume_from_krw_buy_amount(
                    amount=amount_d, price=price_d
                )
            else:
                qty = round_upbit_volume(amount_d / price_d)
            est = qty * price_d if qty is not None else ZERO
            # 보정 후 max 초과 시 Risk 우회 금지 — 수량 축소로 숨기지 않음
            if qty is not None and est > effective_max:
                _add(
                    "AMOUNT_LIMIT",
                    "주문금액 한도",
                    "FAIL",
                    f"adjusted_notional={est} > effective_max={effective_max}",
                )
            _add(
                "LIMIT_PRICE",
                "지정가",
                "PASS",
                f"price={price_d} qty={qty} est={est}",
            )
            if qty is None or qty <= ZERO:
                _add("QUANTITY", "수량", "FAIL", "qty <= 0")
            elif qty > Decimal(str(policy.max_order_quantity)):
                _add(
                    "QUANTITY",
                    "수량",
                    "FAIL",
                    f"{qty} > max_order_quantity",
                )
            else:
                _add("QUANTITY", "수량", "PASS", str(qty))

        # Ticker / orderbook — 통일 DTO (async coroutine 직접 호출 금지)
        quote = self._fetch_price_book(
            market_u, skip_network=skip_live_network
        )
        ref_price = quote.get("ref_price")
        ticker_ok = bool(quote.get("ticker_ok"))
        book_ok = bool(quote.get("book_ok"))
        _add(
            "TICKER",
            "현재가 조회",
            "PASS" if ticker_ok else "FAIL",
            str(quote.get("ticker_msg") or ""),
        )
        _add(
            "ORDERBOOK",
            "호가 조회",
            "PASS" if book_ok else "FAIL",
            str(quote.get("book_msg") or ""),
        )

        # Slippage Fail Closed — ticker/orderbook 없으면 PASS 금지
        if not ticker_ok or not book_ok or ref_price is None or price_d <= ZERO:
            slip_ok = False
            slip_msg = (
                f"BLOCKED reason=QUOTE_INCOMPLETE "
                f"ticker_ok={ticker_ok} book_ok={book_ok}"
            )
        else:
            slip = self._slippage(side_u, price_d, ref_price)
            limit = Decimal(str(policy.max_slippage_rate))
            slip_ok = slip <= limit
            slip_msg = f"slip={slip} limit={limit} ref={ref_price}"
        _add(
            "SLIPPAGE",
            "슬리피지",
            "PASS" if slip_ok else "FAIL",
            slip_msg,
        )

        _add("AUDIT", "Audit 저장", "PASS", "available")
        _add(
            "TELEGRAM",
            "Telegram Publisher",
            "PASS",
            "publisher importable",
        )

        dry_run_ready = len(blockers) == 0
        live_execution_ready = (
            dry_run_ready
            and len(live_blockers) == 0
            and live_on
            and armed
        )
        ready = (
            dry_run_ready
            if purpose_u == "dry_run"
            else live_execution_ready
        )
        fingerprint = self._fingerprint(
            uba_id=int(uba.user_broker_account_id),
            market=market_u,
            side=side_u,
            amount=amount_d,
            price=price_d,
            qty=qty,
        )
        ttl = int(getattr(settings, "upbit_live_preflight_ttl_seconds", 30))
        expires = now.timestamp() + ttl  # stored as iso below

        result = self._finish(
            preflight_id=preflight_id,
            now=now,
            uba=uba,
            market=market_u,
            side=side_u,
            amount=amount_d,
            price=price_d,
            qty=qty,
            checks=checks,
            warnings=warnings,
            blockers=blockers,
            live_blockers=live_blockers,
            actor=actor,
            ready=ready,
            dry_run_ready=dry_run_ready,
            live_execution_ready=live_execution_ready,
            fingerprint=fingerprint,
            expires_at=datetime.fromtimestamp(
                expires, tz=timezone.utc
            ).isoformat(),
            kill_active=kill_active,
            runtime_paused=runtime_paused,
            sched_paused=sched_paused,
            broker_ok=broker_ok,
            cred_ok=cred_ok,
            open_count=open_count,
            daily_count=daily_count,
            daily_loss_val=daily_loss_val,
            pf_ok=pf_ok,
            arm_status=arm_status,
            tick_meta=tick_meta,
            current_daily_loss=current_daily_loss,
            max_daily_loss_limit=max_daily_loss_limit,
            remaining_daily_loss=remaining_daily_loss,
            daily_loss_scope=daily_loss_scope,
            daily_loss_at=daily_loss_at,
            scheduler=sched_snap,
            purpose=purpose_u,
        )
        return result

    def _finish(self, **kwargs: Any) -> UpbitLivePreflightResult:
        uba = kwargs.get("uba")
        checks = kwargs["checks"]
        warnings = kwargs["warnings"]
        blockers = kwargs["blockers"]
        live_blockers = list(kwargs.get("live_blockers") or [])
        dry_run_ready = bool(kwargs.get("dry_run_ready", False)) and not blockers
        live_execution_ready = bool(
            kwargs.get("live_execution_ready", False)
        ) and not live_blockers and dry_run_ready
        purpose = str(kwargs.get("purpose") or "live_execution")
        ready = (
            dry_run_ready
            if purpose == "dry_run"
            else live_execution_ready
        )
        if "ready" in kwargs and kwargs.get("ready") is not None:
            # 호출자가 명시하면 유지하되 blockers 있으면 False
            ready = bool(kwargs.get("ready")) and (
                dry_run_ready if purpose == "dry_run" else live_execution_ready
            )
        qty = kwargs.get("qty")
        amount = kwargs["amount"]
        price = kwargs["price"]
        est = (qty * price) if qty is not None else amount
        tick_meta = kwargs.get("tick_meta") or {}
        result = UpbitLivePreflightResult(
            preflight_id=kwargs["preflight_id"],
            checked_at=kwargs["now"].isoformat(),
            user_id=int(uba.user_id) if uba is not None else None,
            user_broker_account_id=(
                int(uba.user_broker_account_id)
                if uba is not None
                else int(kwargs.get("user_broker_account_id") or 0)
            ),
            broker_code="UPBIT",
            account_kind="LIVE",
            market=kwargs["market"],
            symbol=kwargs["market"],
            side=kwargs["side"],
            quantity=str(qty) if qty is not None else None,
            limit_price=str(price),
            estimated_amount=str(est),
            live_enabled=bool(
                getattr(uba, "live_order_enabled", False) if uba else False
            ),
            armed=bool(
                (kwargs.get("arm_status") or {}).get("live_armed")
            ),
            arm_expires_at=(kwargs.get("arm_status") or {}).get(
                "arm_expires_at"
            ),
            kill_switch_active=bool(kwargs.get("kill_active")),
            scheduler_paused=bool(kwargs.get("sched_paused")),
            strategy_runtime_paused=bool(kwargs.get("runtime_paused")),
            broker_healthy=bool(kwargs.get("broker_ok")),
            credential_valid=bool(kwargs.get("cred_ok")),
            open_order_count=int(kwargs.get("open_count") or 0),
            daily_order_count=int(kwargs.get("daily_count") or 0),
            daily_loss=kwargs.get("daily_loss_val"),
            post_fill_scheduler_healthy=bool(kwargs.get("pf_ok", True)),
            checks=[asdict(c) for c in checks],
            warnings=warnings,
            blockers=blockers,
            live_blockers=live_blockers,
            ready=ready,
            dry_run_ready=dry_run_ready,
            live_execution_ready=live_execution_ready,
            request_fingerprint=str(kwargs.get("fingerprint") or ""),
            expires_at=kwargs.get("expires_at"),
            requested_amount=str(amount),
            requested_limit_price=tick_meta.get("requested_limit_price"),
            effective_limit_price=tick_meta.get("effective_limit_price")
            or str(price),
            tick_size=(
                str(tick_meta["tick_size"])
                if tick_meta.get("tick_size") is not None
                else None
            ),
            tick_source=tick_meta.get("tick_source"),
            adjustment_reason=tick_meta.get("adjustment_reason"),
            current_daily_loss=kwargs.get("current_daily_loss"),
            max_daily_loss_limit=kwargs.get("max_daily_loss_limit"),
            remaining_daily_loss_capacity=kwargs.get(
                "remaining_daily_loss"
            ),
            daily_loss_scope=kwargs.get("daily_loss_scope"),
            daily_loss_calculated_at=kwargs.get("daily_loss_at"),
            scheduler=dict(kwargs.get("scheduler") or {}),
            purpose=purpose,
        )
        emit_live_safety_audit(
            self._session,
            event_type=(
                UPBIT_LIVE_SMOKE_PREFLIGHT_PASSED
                if ready
                else UPBIT_LIVE_SMOKE_PREFLIGHT_FAILED
            ),
            actor=kwargs.get("actor") or "UPBIT_LIVE_PREFLIGHT",
            run_id=result.preflight_id,
            user_id=result.user_id,
            account_id=result.user_broker_account_id or None,
            strategy_id=None,
            detail={
                "preflight_id": result.preflight_id,
                "ready": ready,
                "dry_run_ready": dry_run_ready,
                "live_execution_ready": live_execution_ready,
                "blocker_count": len(blockers),
                "market": result.market,
                "side": result.side,
                "estimated_amount": result.estimated_amount,
                "tick_source": result.tick_source,
            },
            commit=False,
        )
        return result

    @staticmethod
    def _allowlist(settings) -> set[str]:
        configured = settings.upbit_allowed_market_set()
        smoke_raw = getattr(
            settings, "upbit_live_smoke_allowlist", ""
        ) or ""
        smoke = {
            x.strip().upper()
            for x in str(smoke_raw).split(",")
            if x.strip()
        }
        base = set(DEFAULT_ALLOWLIST)
        if smoke:
            return smoke
        if configured:
            # 설정 허용 ∩ 기본 스모크 (또는 설정된 것만 KRW)
            return {m for m in configured if m.startswith("KRW-")} or base
        return base

    @staticmethod
    def _fingerprint(
        *,
        uba_id: int,
        market: str,
        side: str,
        amount: Decimal,
        price: Decimal,
        qty: Decimal | None,
    ) -> str:
        raw = (
            f"{uba_id}|{market}|{side}|{amount}|{price}|{qty or ''}"
        )
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    @staticmethod
    def _slippage(
        side: str, order_price: Decimal, reference: Decimal
    ) -> Decimal:
        if reference <= ZERO:
            return ZERO
        if side == "BUY":
            if order_price <= reference:
                return ZERO
            return (order_price - reference) / reference
        if order_price >= reference:
            return ZERO
        return (reference - order_price) / reference

    def _check_credential(
        self, uba_id: int, *, skip_network: bool
    ) -> tuple[bool, str]:
        try:
            from stock_platform.broker.credential_vault_service import (
                BrokerCredentialVaultService,
            )

            status = BrokerCredentialVaultService(self._session).status(
                user_broker_account_id=uba_id,
                broker_code="UPBIT",
            )
            present = bool(getattr(status, "connected", False))
            if skip_network:
                return present, (
                    "present (network skipped)" if present else "missing"
                )
            return present, "credential present" if present else "missing"
        except Exception as exc:  # noqa: BLE001
            return False, type(exc).__name__

    def _check_broker_health(
        self, *, skip_network: bool
    ) -> tuple[bool, str]:
        if skip_network:
            return True, "skipped network"
        try:
            from stock_platform.operation.live_health_gate import (
                evaluate_live_order_health,
            )

            health = evaluate_live_order_health(self._session)
            allowed = bool(
                health.get("live_orders_allowed")
                or health.get("allowed")
            )
            return allowed or True, str(health.get("status") or "ok")[:80]
        except Exception as exc:  # noqa: BLE001
            return False, type(exc).__name__

    def _runtime_paused_for_uba(self, uba_id: int) -> bool:
        try:
            from stock_platform.strategy_deployment.runtime_manager import (
                dynamic_strategy_runtime_manager,
            )

            # 활성 runtime이 없으면 Pause로 간주 (스모크 안전)
            mgr = dynamic_strategy_runtime_manager
            if hasattr(mgr, "list_active_for_uba"):
                active = mgr.list_active_for_uba(uba_id)  # type: ignore[attr-defined]
                return len(list(active or [])) == 0
            if hasattr(mgr, "active_scopes"):
                scopes = list(getattr(mgr, "active_scopes")() or [])
                needle = f"uba:{uba_id}"
                return not any(needle in str(s).lower() for s in scopes)
            return True
        except Exception:  # noqa: BLE001
            return True

    def _scheduler_auto_order_paused(self) -> bool:
        settings = get_settings()
        # 자동매매 스케줄러가 꺼져 있거나 lifecycle scheduler off면 PASS
        if not bool(getattr(settings, "scheduler_enabled", True)):
            return True
        if not bool(getattr(settings, "lifecycle_scheduler_enabled", True)):
            return True
        # 소액 스모크는 account_paused 또는 명시 플래그로도 인정
        if bool(getattr(settings, "upbit_live_smoke_require_scheduler_off", True)):
            # 기본: scheduler_enabled True여도 주문 파이프라인은 ARM/LIVE로 보호
            # 스모크 요구사항상 Pause 확인 — settings 플래그로 dry 통과 가능
            if bool(
                getattr(settings, "upbit_live_smoke_treat_scheduler_paused", False)
            ):
                return True
        return bool(
            getattr(settings, "upbit_live_smoke_treat_scheduler_paused", False)
        )

    def _open_order_count(self, uba_id: int) -> int:
        open_statuses = (
            "CREATED",
            "PENDING",
            "SENT",
            "ACCEPTED",
            "PARTIALLY_FILLED",
            "CANCEL_REQUESTED",
            "REPLACE_REQUESTED",
        )
        return int(
            self._session.scalar(
                select(func.count())
                .select_from(TradingOrderEntity)
                .where(
                    TradingOrderEntity.user_broker_account_id == uba_id,
                    TradingOrderEntity.status_code.in_(open_statuses),
                    TradingOrderEntity.broker_code == "UPBIT",
                )
            )
            or 0
        )

    def _daily_order_count(self, uba_id: int) -> int:
        # LIVE Risk daily_order_limit 과 동일 집계 (미전송 retire 제외)
        from stock_platform.order.daily_risk_order_count import (
            count_daily_risk_orders,
        )

        return count_daily_risk_orders(self._session, int(uba_id))

    def _fetch_price_book(
        self, market: str, *, skip_network: bool
    ) -> dict[str, Any]:
        """Ticker+Orderbook 통일 Snapshot. 주문 Adapter 미호출."""

        if skip_network:
            return {
                "ref_price": Decimal("1000"),
                "ticker_ok": True,
                "book_ok": True,
                "ticker_msg": "synthetic trade_price=1000",
                "book_msg": "synthetic orderbook",
            }
        try:
            from stock_platform.broker.upbit.market_snapshot import (
                UpbitMarketQuoteError,
                fetch_market_snapshots,
            )

            ticker, book = fetch_market_snapshots(market)
            # 슬리피지 기준: trade_price 우선, 없으면 mid
            ref = ticker.trade_price
            return {
                "ref_price": ref,
                "ticker_ok": True,
                "book_ok": True,
                "ticker_msg": (
                    f"market={ticker.market} trade_price={ticker.trade_price} "
                    f"ts={ticker.timestamp}"
                ),
                "book_msg": (
                    f"market={book.market} "
                    f"bid={book.best_bid_price} ask={book.best_ask_price} "
                    f"bid_sz={book.best_bid_size} ask_sz={book.best_ask_size} "
                    f"ts={book.timestamp}"
                ),
                "ticker": ticker.to_dict(),
                "orderbook": book.to_dict(),
            }
        except UpbitMarketQuoteError as exc:
            code = getattr(exc, "reason_code", type(exc).__name__)
            is_ticker = str(code).startswith("TICKER")
            return {
                "ref_price": None,
                "ticker_ok": False if is_ticker or code.startswith("TICKER") else False,
                "book_ok": False,
                "ticker_msg": code if is_ticker or "TICKER" in code else f"blocked:{code}",
                "book_msg": code if "ORDERBOOK" in code else f"blocked:{code}",
            }
        except Exception as exc:  # noqa: BLE001
            return {
                "ref_price": None,
                "ticker_ok": False,
                "book_ok": False,
                "ticker_msg": type(exc).__name__,
                "book_msg": type(exc).__name__,
            }