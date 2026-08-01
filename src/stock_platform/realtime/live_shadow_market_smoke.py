"""실시세 → Hub → Signal → Risk → LIVE_SHADOW_INTENT.

실주문 Flag OFF 유지. live_shadow_mode_enabled=True.
Broker submit/cancel/replace 호출 0. Secret 값 미출력.
"""

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any
from unittest.mock import patch

import httpx
import structlog
from sqlalchemy import text

from stock_platform.common.settings import clear_settings_cache, get_settings
from stock_platform.database.session import get_session_factory
from stock_platform.order.live_shadow import reset_shadow_counters, shadow_counters
from stock_platform.realtime.execution_models import (
    RealtimeExecutionConfig,
    RealtimeExecutionMode,
)
from stock_platform.realtime.manager import realtime_manager
from stock_platform.realtime.market_data_hub import (
    get_realtime_market_data_hub,
    reset_realtime_market_data_hub_for_tests,
)
from stock_platform.realtime.models import MarketEventType, RealtimeQuote
from stock_platform.realtime.runtime import (
    realtime_execution_runner,
    realtime_safety_guard,
    realtime_strategy_runner,
)
from stock_platform.realtime.safety_models import RealtimeOrderSafetyConfig
from stock_platform.realtime.scoped_signal_pipeline import (
    reset_signal_dedup_for_tests,
)
from stock_platform.realtime.strategy_models import RealtimeStrategyConfig
from stock_platform.strategy_deployment.runtime_scope import (
    AccountKind,
    RuntimeLifecycleStatus,
    StrategyRuntimeScope,
)


logger = structlog.get_logger(__name__)


@dataclass
class ShadowSmokeReport:
    broker: str
    auth_ok: bool = False
    quotes_received: int = 0
    shadow_intents: int = 0
    duplicate_intents: int = 0
    broker_submit_calls: int = 0
    broker_cancel_calls: int = 0
    broker_replace_calls: int = 0
    reconnects: int = 0
    kill_blocked: bool | None = None
    pause_blocked: bool | None = None
    runtime_stopped: bool = False
    secret_leaked: bool = False
    errors: list[str] = field(default_factory=list)
    duration_seconds: float = 0.0
    detail: dict[str, Any] = field(default_factory=dict)

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "broker": self.broker,
            "auth_ok": self.auth_ok,
            "quotes_received": self.quotes_received,
            "shadow_intents": self.shadow_intents,
            "duplicate_intents": self.duplicate_intents,
            "broker_submit_calls": self.broker_submit_calls,
            "broker_cancel_calls": self.broker_cancel_calls,
            "broker_replace_calls": self.broker_replace_calls,
            "reconnects": self.reconnects,
            "kill_blocked": self.kill_blocked,
            "pause_blocked": self.pause_blocked,
            "runtime_stopped": self.runtime_stopped,
            "secret_leaked": self.secret_leaked,
            "errors": self.errors[:20],
            "duration_seconds": round(self.duration_seconds, 2),
            "detail": self.detail,
            "shadow_counters": shadow_counters(),
        }


class _BrokerSpy:
    def __init__(self) -> None:
        self.submit = 0
        self.cancel = 0
        self.replace = 0

    def block_submit(self, *_a, **_k):
        self.submit += 1
        raise AssertionError("shadow smoke: submit forbidden")

    def block_cancel(self, *_a, **_k):
        self.cancel += 1
        raise AssertionError("shadow smoke: cancel forbidden")

    def block_replace(self, *_a, **_k):
        self.replace += 1
        raise AssertionError("shadow smoke: replace forbidden")


def _force_shadow_env() -> None:
    os.environ["LIVE_SHADOW_MODE_ENABLED"] = "true"
    os.environ["UPBIT_LIVE_ORDER_ENABLED"] = "false"
    os.environ["KIWOOM_LIVE_ORDER_ENABLED"] = "false"
    clear_settings_cache()


def _no_secret(text: str, secrets: list[str]) -> bool:
    blob = text.lower()
    for secret in secrets:
        s = str(secret or "").strip()
        if len(s) >= 8 and s.lower() in blob:
            return False
    return True


def _configure_runner(
    *,
    paper_id: int,
    uba_id: int,
    order_amount: Decimal | None = None,
) -> None:
    # 주식 1주 확보용 (risk max_order_amount=100000 이하)
    amount = order_amount if order_amount is not None else Decimal("100000")
    realtime_execution_runner._config = RealtimeExecutionConfig(
        mode=RealtimeExecutionMode.LIVE,
        account_id=int(paper_id),
        order_amount=amount,
        auto_fill=False,
        allow_buy=True,
        allow_sell=True,
        user_broker_account_id=int(uba_id),
    )
    sc = realtime_safety_guard._config
    realtime_safety_guard._config = RealtimeOrderSafetyConfig(
        max_order_amount=Decimal("5000000"),
        max_daily_loss=Decimal("5000000"),
        max_open_positions=20,
        duplicate_order_window_seconds=0,
        symbol_cooldown_seconds=0,
        max_orders_per_minute=200,
        trading_start_time=sc.trading_start_time,
        trading_end_time=sc.trading_end_time,
        enforce_market_hours_for_krx=False,
        live_trading_enabled=True,
        live_unlock_token="SHADOW-SMOKE-UNLOCK",
    )


async def _shutdown() -> None:
    try:
        await realtime_execution_runner.stop()
    except Exception:  # noqa: BLE001
        pass
    try:
        await realtime_strategy_runner.stop()
    except Exception:  # noqa: BLE001
        pass
    try:
        await realtime_manager.stop_all()
    except Exception:  # noqa: BLE001
        pass
    try:
        hub = get_realtime_market_data_hub()
        await hub.stop_dispatch()
        hub.registry.clear()
    except Exception:  # noqa: BLE001
        pass
    reset_realtime_market_data_hub_for_tests()
    reset_signal_dedup_for_tests()


def _shadow_count(
    session,
    uba_id: int,
    since: datetime,
    *,
    side: str | None = None,
) -> int:
    side_clause = ""
    params: dict[str, Any] = {"u": uba_id, "t": since}
    if side:
        side_clause = " AND side_code=:side"
        params["side"] = side.upper()
    return int(
        session.execute(
            text(
                f"""
                SELECT COUNT(*) FROM trading.trading_order
                WHERE user_broker_account_id=:u
                  AND metadata_payload->>'shadow_mode'='LIVE_SHADOW'
                  AND created_at >= :t
                  {side_clause}
                """
            ),
            params,
        ).scalar_one()
    )


def _broker_id_count(session, uba_id: int, since: datetime) -> int:
    return int(
        session.execute(
            text(
                """
                SELECT COUNT(*) FROM trading.trading_order
                WHERE user_broker_account_id=:u
                  AND broker_order_id IS NOT NULL
                  AND created_at >= :t
                """
            ),
            {"u": uba_id, "t": since},
        ).scalar_one()
    )


def _dup_count(session, uba_id: int, since: datetime) -> int:
    return int(
        session.execute(
            text(
                """
                SELECT COUNT(*) FROM (
                  SELECT client_order_id
                  FROM trading.trading_order
                  WHERE user_broker_account_id=:u
                    AND metadata_payload->>'shadow_mode'='LIVE_SHADOW'
                    AND created_at >= :t
                  GROUP BY client_order_id
                  HAVING COUNT(*) > 1
                ) d
                """
            ),
            {"u": uba_id, "t": since},
        ).scalar_one()
    )


async def _publish(quote: RealtimeQuote) -> None:
    await realtime_manager.handle_quote(quote)


async def _inject_ma_cross_burst(
    *,
    exchange_code: str,
    symbol: str,
    mid: Decimal,
    source_code: str,
) -> None:
    """실호가 mid 기준 Golden/Dead Cross 유도 시퀀스(장외·횡보 대응)."""

    cycle = [
        Decimal("-0.004"),
        Decimal("-0.004"),
        Decimal("-0.004"),
        Decimal("-0.002"),
        Decimal("0.000"),
        Decimal("0.002"),
        Decimal("0.004"),
        Decimal("0.006"),
        Decimal("0.004"),
        Decimal("0.000"),
        Decimal("-0.003"),
        Decimal("-0.005"),
    ]
    for wobble in cycle:
        px = (mid * (Decimal("1") + wobble)).quantize(Decimal("1"))
        if px <= 0:
            px = mid
        now = datetime.now(timezone.utc)
        await _publish(
            RealtimeQuote(
                exchange_code=exchange_code,
                symbol=symbol,
                event_type=MarketEventType.TICKER,
                trade_price=px,
                opening_price=None,
                high_price=None,
                low_price=None,
                previous_close_price=None,
                change_price=None,
                change_rate=None,
                accumulated_volume=None,
                trade_volume=Decimal("1"),
                event_time=now,
                received_at=now,
                source_code=source_code,
            )
        )
        await asyncio.sleep(0.15)


async def _boot_hub_consumer(
    *,
    user_id: int,
    uba_id: int,
    broker: str,
    market_type: str,
    symbols: list[str],
    strategy_id: int,
) -> Any:
    hub = get_realtime_market_data_hub()
    hub.set_quote_bus(realtime_manager.bus)
    await hub.start_dispatch()
    hub.register_consumer(
        StrategyRuntimeScope(
            user_id=int(user_id),
            account_kind=AccountKind.USER_BROKER,
            account_id=int(uba_id),
            strategy_id=strategy_id,
            strategy_version="shadow-md-1",
            market_type=market_type,
            broker_code=broker,
            strategy_code="SHADOW_MA",
        ),
        symbols,
        config=RealtimeStrategyConfig(
            short_window=2,
            long_window=3,
            minimum_change_rate=Decimal("0"),
            stop_loss_ratio=Decimal("0.5"),
            take_profit_ratio=Decimal("0.5"),
            cooldown_seconds=0,
        ),
        runtime_status=RuntimeLifecycleStatus.RUNNING,
    )
    await realtime_execution_runner.start()
    return hub


async def run_upbit_real_market_shadow_smoke(
    *,
    duration_seconds: float = 300.0,
    symbol: str = "KRW-BTC",
    uba_id: int | None = None,
    paper_account_id: int | None = None,
) -> ShadowSmokeReport:
    report = ShadowSmokeReport(broker="UPBIT")
    t0 = time.monotonic()
    since = datetime.now(timezone.utc)
    secrets: list[str] = []
    spy = _BrokerSpy()
    _force_shadow_env()
    reset_shadow_counters()
    await _shutdown()

    settings = get_settings()
    paper_id = int(paper_account_id or settings.realtime_paper_account_id or 1)
    SessionLocal = get_session_factory()

    with SessionLocal() as session:
        if uba_id is None:
            uba_id = session.execute(
                text(
                    """
                    SELECT user_broker_account_id FROM trading.user_broker_account
                    WHERE broker_code='UPBIT' AND is_active IS TRUE
                    ORDER BY user_broker_account_id LIMIT 1
                    """
                )
            ).scalar()
        if not uba_id:
            report.errors.append("UPBIT_UBA_NOT_FOUND")
            report.duration_seconds = time.monotonic() - t0
            return report
        user_id = int(
            session.execute(
                text(
                    "SELECT user_id FROM trading.user_broker_account "
                    "WHERE user_broker_account_id=:u"
                ),
                {"u": uba_id},
            ).scalar_one()
        )
        try:
            from stock_platform.broker.credential_vault_service import (
                BrokerCredentialVaultService,
            )
            from stock_platform.broker.upbit.private_client import (
                UpbitPrivateClient,
            )

            resolved = BrokerCredentialVaultService(session).resolve_for_runtime(
                int(uba_id),
                expected_broker="UPBIT",
                require_verified=True,
                touch_last_used=False,
            )
            payload = dict(resolved.payload or {})
            access = str(payload.get("access_key") or "")
            secret = str(payload.get("secret_key") or "")
            secrets.extend([access, secret])
        except Exception as exc:  # noqa: BLE001
            report.errors.append(f"UPBIT_VAULT:{type(exc).__name__}")
            report.duration_seconds = time.monotonic() - t0
            return report

    try:
        from stock_platform.broker.upbit.private_client import (
            UpbitPrivateClient,
        )

        verify_settings = settings.model_copy(
            update={
                "upbit_access_key": access,
                "upbit_secret_key": secret,
                "upbit_use_mock": False,
            }
        )
        client = UpbitPrivateClient(settings=verify_settings)
        try:
            accounts = await client.list_accounts()
        finally:
            await client.aclose()
        report.auth_ok = isinstance(accounts, list)
        report.detail["balance_rows"] = len(accounts)
        report.detail["uba_id"] = int(uba_id)
    except Exception as exc:  # noqa: BLE001
        report.auth_ok = False
        report.errors.append(f"UPBIT_AUTH:{type(exc).__name__}")
        report.duration_seconds = time.monotonic() - t0
        return report

    _configure_runner(paper_id=paper_id, uba_id=int(uba_id))
    await _boot_hub_consumer(
        user_id=user_id,
        uba_id=int(uba_id),
        broker="UPBIT",
        market_type="CRYPTO",
        symbols=[symbol],
        strategy_id=941001,
    )

    from stock_platform.broker.adapter import BrokerAdapter

    quotes = 0
    with patch.object(BrokerAdapter, "submit_order", spy.block_submit), patch.object(
        BrokerAdapter, "cancel_order", spy.block_cancel
    ), patch.object(BrokerAdapter, "replace_order", spy.block_replace):
        # WS + REST 폴백
        try:
            await realtime_manager.start_upbit(
                symbols=[symbol], channels=["ticker"]
            )
        except Exception as exc:  # noqa: BLE001
            report.errors.append(f"UPBIT_WS:{type(exc).__name__}")
            report.reconnects += 1

        deadline = time.monotonic() + float(duration_seconds)
        reconnect_done = False
        async with httpx.AsyncClient(timeout=8.0) as http:
            while time.monotonic() < deadline:
                # 중간에 WS 끊고 재연결 1회
                if (
                    not reconnect_done
                    and quotes >= 5
                    and time.monotonic() > t0 + min(30.0, duration_seconds / 3)
                ):
                    try:
                        await realtime_manager.stop_all()
                        await asyncio.sleep(0.5)
                        await realtime_manager.start_upbit(
                            symbols=[symbol], channels=["ticker"]
                        )
                        report.reconnects += 1
                        reconnect_done = True
                        report.detail["ws_reconnect"] = True
                    except Exception as exc:  # noqa: BLE001
                        report.errors.append(
                            f"UPBIT_RECONNECT:{type(exc).__name__}"
                        )
                        report.reconnects += 1
                        reconnect_done = True
                try:
                    r = await http.get(
                        "https://api.upbit.com/v1/ticker",
                        params={"markets": symbol},
                    )
                    r.raise_for_status()
                    rows = r.json()
                    px = Decimal(str(rows[0]["trade_price"]))
                    now = datetime.now(timezone.utc)
                    q = RealtimeQuote(
                        exchange_code="UPBIT",
                        symbol=symbol,
                        event_type=MarketEventType.TICKER,
                        trade_price=px,
                        opening_price=None,
                        high_price=None,
                        low_price=None,
                        previous_close_price=None,
                        change_price=None,
                        change_rate=None,
                        accumulated_volume=None,
                        trade_volume=Decimal("1"),
                        event_time=now,
                        received_at=now,
                        source_code="UPBIT_PUBLIC_TICKER",
                    )
                    quotes += 1
                    await _publish(q)
                except Exception as exc:  # noqa: BLE001
                    report.errors.append(f"UPBIT_TICKER:{type(exc).__name__}")
                    report.reconnects += 1
                await asyncio.sleep(1.0)

        # Kill switch probe — WS 중지 후 교차 버스트로 Intent 유발 시도
        try:
            from stock_platform.risk_engine.kill_switch_service import (
                KillSwitchService,
            )
            from stock_platform.trading.account_identity import (
                uba_kill_switch_scope,
            )

            try:
                await realtime_manager.stop_all()
            except Exception:  # noqa: BLE001
                pass
            await asyncio.sleep(1.0)

            with SessionLocal() as session:
                scope = uba_kill_switch_scope(int(uba_id))
                KillSwitchService(session).activate_scope(
                    scope_code=scope, actor="SHADOW_MD", reason="probe"
                )
                session.commit()
                before = _shadow_count(
                    session, int(uba_id), since, side="BUY"
                )
            await _inject_ma_cross_burst(
                exchange_code="UPBIT",
                symbol=symbol,
                mid=Decimal("100000000"),
                source_code="UPBIT_KILL_PROBE",
            )
            await asyncio.sleep(2.0)
            with SessionLocal() as session:
                after = _shadow_count(
                    session, int(uba_id), since, side="BUY"
                )
                report.kill_blocked = after <= before
                report.detail["kill_before"] = before
                report.detail["kill_after"] = after
                KillSwitchService(session).deactivate_scope(
                    scope_code=scope, actor="SHADOW_MD", reason="probe_done"
                )
                session.commit()
        except Exception as exc:  # noqa: BLE001
            report.errors.append(f"KILL:{type(exc).__name__}")

    hub = get_realtime_market_data_hub()
    report.detail["hub"] = hub.status()
    report.detail["execution"] = realtime_execution_runner.status()

    with SessionLocal() as session:
        report.shadow_intents = _shadow_count(session, int(uba_id), since)
        report.duplicate_intents = _dup_count(session, int(uba_id), since)
        if _broker_id_count(session, int(uba_id), since):
            report.errors.append("BROKER_ORDER_ID_CREATED")

    report.quotes_received = quotes
    report.broker_submit_calls = spy.submit
    report.broker_cancel_calls = spy.cancel
    report.broker_replace_calls = spy.replace
    await _shutdown()
    report.runtime_stopped = True
    report.duration_seconds = time.monotonic() - t0
    report.secret_leaked = not _no_secret(str(report.to_public_dict()), secrets)
    return report


async def run_kiwoom_real_market_shadow_smoke(
    *,
    duration_seconds: float = 300.0,
    symbol: str = "005930",
    uba_id: int | None = None,
    paper_account_id: int | None = None,
) -> ShadowSmokeReport:
    report = ShadowSmokeReport(broker="KIWOOM")
    t0 = time.monotonic()
    since = datetime.now(timezone.utc)
    secrets: list[str] = []
    spy = _BrokerSpy()
    _force_shadow_env()
    reset_shadow_counters()
    await _shutdown()

    settings = get_settings()
    paper_id = int(paper_account_id or settings.realtime_paper_account_id or 1)
    SessionLocal = get_session_factory()

    with SessionLocal() as session:
        if uba_id is None:
            uba_id = session.execute(
                text(
                    """
                    SELECT user_broker_account_id FROM trading.user_broker_account
                    WHERE broker_code='KIWOOM' AND is_active IS TRUE
                    ORDER BY user_broker_account_id DESC LIMIT 1
                    """
                )
            ).scalar()
        if not uba_id:
            report.errors.append("KIWOOM_UBA_NOT_FOUND")
            report.duration_seconds = time.monotonic() - t0
            return report
        user_id = int(
            session.execute(
                text(
                    "SELECT user_id FROM trading.user_broker_account "
                    "WHERE user_broker_account_id=:u"
                ),
                {"u": uba_id},
            ).scalar_one()
        )

    app_key = str(settings.kiwoom_app_key or "")
    secret_key = str(settings.kiwoom_secret_key or "")
    secrets.extend([app_key, secret_key])
    if not app_key or not secret_key:
        report.errors.append("KIWOOM_SETTINGS_KEY_MISSING")
        report.duration_seconds = time.monotonic() - t0
        return report

    try:
        from stock_platform.broker.kiwoom.config import KiwoomOrderConfig
        from stock_platform.broker.kiwoom.http_client import KiwoomRestClient
        from stock_platform.broker.kiwoom.rate_limiter import KiwoomRateLimiters
        from stock_platform.broker.kiwoom.token_cache import KiwoomTokenCache
        from stock_platform.broker.kiwoom.token_client import KiwoomTokenClient

        # 시세 조회용 토큰 — 실주문 Flag는 항상 False
        # mock 설정이어도 인증 실패 시 실 API base로 1회 재시도(조회 전용)
        bases = [settings.kiwoom_base_url]
        if bool(settings.kiwoom_use_mock):
            bases.append("https://api.kiwoom.com")
        token = None
        config = None
        last_exc: Exception | None = None
        for base in bases:
            try:
                config = KiwoomOrderConfig(
                    base_url=base,
                    app_key=app_key,
                    secret_key=secret_key,
                    use_mock=("mockapi" in base),
                    live_order_enabled=False,
                    timeout_seconds=settings.kiwoom_http_timeout_seconds,
                )
                token_client = KiwoomTokenClient(config)
                token = token_client.issue()
                report.detail["auth_base"] = base
                break
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                continue
        if token is None or config is None:
            raise last_exc or RuntimeError("KIWOOM_AUTH_FAILED")
        report.auth_ok = bool(getattr(token, "token", None))
        report.detail["uba_id"] = int(uba_id)
        report.detail["use_mock"] = "mockapi" in str(
            report.detail.get("auth_base") or ""
        )
        rest = KiwoomRestClient(
            config=config,
            token_cache=KiwoomTokenCache(KiwoomTokenClient(config)),
            rate_limiters=KiwoomRateLimiters(),
        )
    except Exception as exc:  # noqa: BLE001
        report.auth_ok = False
        report.errors.append(f"KIWOOM_AUTH:{type(exc).__name__}")
        report.duration_seconds = time.monotonic() - t0
        return report

    _configure_runner(paper_id=paper_id, uba_id=int(uba_id))
    await _boot_hub_consumer(
        user_id=user_id,
        uba_id=int(uba_id),
        broker="KIWOOM",
        market_type="STOCK",
        symbols=[symbol],
        strategy_id=941002,
    )

    from stock_platform.broker.adapter import BrokerAdapter

    quotes = 0
    last_mid = Decimal("70000")
    with patch.object(BrokerAdapter, "submit_order", spy.block_submit), patch.object(
        BrokerAdapter, "cancel_order", spy.block_cancel
    ), patch.object(BrokerAdapter, "replace_order", spy.block_replace):
        deadline = time.monotonic() + float(duration_seconds)
        while time.monotonic() < deadline:
            try:
                payload, _hdr = rest.post(
                    path="/api/dostk/mrkcond",
                    api_id="ka10007",
                    body={"stk_cd": symbol},
                    request_type="INQUIRY",
                )
                price = (
                    payload.get("cur_prc")
                    or payload.get("exec_pric")
                    or payload.get("current_price")
                    or payload.get("stck_prpr")
                    or payload.get("trade_price")
                    or payload.get("buy_fpr_bid")
                    or payload.get("buy_1bid")
                )
                if price in (None, ""):
                    raise ValueError("NO_PRICE_FIELD")
                px = Decimal(str(price).lstrip("+-").replace(",", ""))
                if px <= 0:
                    raise ValueError("NON_POSITIVE_PRICE")
                last_mid = px
                # 실호가 + 주기적 Cross 버스트(장외 횡보 시 Signal 보장)
                if quotes == 0 or quotes % 20 == 0:
                    await _inject_ma_cross_burst(
                        exchange_code="KRX",
                        symbol=symbol,
                        mid=px,
                        source_code="KIWOOM_MRKCOND_BURST",
                    )
                now = datetime.now(timezone.utc)
                await _publish(
                    RealtimeQuote(
                        exchange_code="KRX",
                        symbol=symbol,
                        event_type=MarketEventType.TICKER,
                        trade_price=px,
                        opening_price=None,
                        high_price=None,
                        low_price=None,
                        previous_close_price=None,
                        change_price=None,
                        change_rate=None,
                        accumulated_volume=None,
                        trade_volume=Decimal("1"),
                        event_time=now,
                        received_at=now,
                        source_code="KIWOOM_MRKCOND",
                    )
                )
                quotes += 1
            except Exception as exc:  # noqa: BLE001
                report.errors.append(f"KIWOOM_QUOTE:{type(exc).__name__}")
                report.reconnects += 1
                await asyncio.sleep(2.0)
                continue
            await asyncio.sleep(1.0)

        # Account pause probe — ORM FK 메타 이슈 회피: SQL로 Pause
        try:
            with SessionLocal() as session:
                exists = session.execute(
                    text(
                        """
                        SELECT 1 FROM operation.broker_recovery_account_state
                        WHERE broker_code='KIWOOM'
                          AND user_broker_account_id=:uba
                        LIMIT 1
                        """
                    ),
                    {"uba": int(uba_id)},
                ).scalar()
                if exists:
                    session.execute(
                        text(
                            """
                            UPDATE operation.broker_recovery_account_state
                            SET trading_paused = TRUE, updated_at = NOW()
                            WHERE broker_code='KIWOOM'
                              AND user_broker_account_id=:uba
                            """
                        ),
                        {"uba": int(uba_id)},
                    )
                else:
                    session.execute(
                        text(
                            """
                            INSERT INTO operation.broker_recovery_account_state
                              (broker_code, user_id, user_broker_account_id,
                               recovery_status, trading_paused, updated_at)
                            VALUES
                              ('KIWOOM', :uid, :uba, 'IDLE', TRUE, NOW())
                            """
                        ),
                        {"uid": user_id, "uba": int(uba_id)},
                    )
                session.commit()
                before = _shadow_count(
                    session, int(uba_id), since, side="BUY"
                )
            await _inject_ma_cross_burst(
                exchange_code="KRX",
                symbol=symbol,
                mid=last_mid if last_mid > 0 else Decimal("70000"),
                source_code="KIWOOM_PAUSE_PROBE",
            )
            await asyncio.sleep(2.0)
            with SessionLocal() as session:
                after = _shadow_count(
                    session, int(uba_id), since, side="BUY"
                )
                report.pause_blocked = after <= before
                report.detail["pause_before"] = before
                report.detail["pause_after"] = after
                session.execute(
                    text(
                        """
                        UPDATE operation.broker_recovery_account_state
                        SET trading_paused = FALSE, updated_at = NOW()
                        WHERE broker_code='KIWOOM'
                          AND user_broker_account_id=:uba
                        """
                    ),
                    {"uba": int(uba_id)},
                )
                session.commit()
        except Exception as exc:  # noqa: BLE001
            report.errors.append(f"PAUSE:{type(exc).__name__}")

    hub = get_realtime_market_data_hub()
    report.detail["hub"] = hub.status()
    report.detail["execution"] = realtime_execution_runner.status()

    with SessionLocal() as session:
        report.shadow_intents = _shadow_count(session, int(uba_id), since)
        report.duplicate_intents = _dup_count(session, int(uba_id), since)
        if _broker_id_count(session, int(uba_id), since):
            report.errors.append("BROKER_ORDER_ID_CREATED")

    report.quotes_received = quotes
    report.broker_submit_calls = spy.submit
    report.broker_cancel_calls = spy.cancel
    report.broker_replace_calls = spy.replace
    await _shutdown()
    report.runtime_stopped = True
    report.duration_seconds = time.monotonic() - t0
    report.secret_leaked = not _no_secret(str(report.to_public_dict()), secrets)
    return report
