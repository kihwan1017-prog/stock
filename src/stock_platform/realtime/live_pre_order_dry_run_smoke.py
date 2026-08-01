"""LIVE Pre-order Dry-run smoke — submit 직전 차단 검증.

LIVE_ORDER_DRY_RUN_ENABLED=true, live order flags false.
Broker submit/cancel/replace 0. 장외 Kiwoom Candidate 0.
"""

from __future__ import annotations

import asyncio
import os
import time
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any
from unittest.mock import patch

from sqlalchemy import text

from stock_platform.common.settings import clear_settings_cache, get_settings
from stock_platform.database.session import get_session_factory
from stock_platform.order.live_dry_run import (
    dry_run_counters,
    reset_dry_run_counters,
)
from stock_platform.realtime.live_shadow_market_smoke import (
    ShadowSmokeReport,
    _BrokerSpy,
    _boot_hub_consumer,
    _configure_runner,
    _inject_ma_cross_burst,
    _no_secret,
    _publish,
    _shutdown,
)
from stock_platform.realtime.market_data_hub import get_realtime_market_data_hub
from stock_platform.realtime.models import MarketEventType, RealtimeQuote
from stock_platform.realtime.runtime import realtime_execution_runner, realtime_manager


def _force_dry_run_env() -> None:
    os.environ["LIVE_ORDER_DRY_RUN_ENABLED"] = "true"
    os.environ["LIVE_SHADOW_MODE_ENABLED"] = "false"
    os.environ["UPBIT_LIVE_ORDER_ENABLED"] = "false"
    os.environ["KIWOOM_LIVE_ORDER_ENABLED"] = "false"
    clear_settings_cache()


def _dry_run_count(session, uba_id: int, since: datetime) -> int:
    return int(
        session.execute(
            text(
                """
                SELECT COUNT(*) FROM trading.trading_order
                WHERE user_broker_account_id=:u
                  AND (
                    reject_code='DRY_RUN_BLOCKED'
                    OR metadata_payload->>'dry_run_mode'='LIVE_DRY_RUN'
                  )
                  AND created_at >= :t
                """
            ),
            {"u": uba_id, "t": since},
        ).scalar_one()
    )


def _dup_dry_run(session, uba_id: int, since: datetime) -> int:
    return int(
        session.execute(
            text(
                """
                SELECT COUNT(*) FROM (
                  SELECT client_order_id
                  FROM trading.trading_order
                  WHERE user_broker_account_id=:u
                    AND reject_code='DRY_RUN_BLOCKED'
                    AND created_at >= :t
                  GROUP BY client_order_id
                  HAVING COUNT(*) > 1
                ) d
                """
            ),
            {"u": uba_id, "t": since},
        ).scalar_one()
    )


def _krx_live_allowed() -> tuple[bool, str]:
    try:
        from stock_platform.operation.calendar_repository import (
            TradingCalendarRepository,
        )
        from stock_platform.operation.calendar_service import (
            TradingCalendarService,
        )

        SessionLocal = get_session_factory()
        with SessionLocal() as session:
            decision = TradingCalendarService(
                TradingCalendarRepository(session)
            ).evaluate(
                exchange_code="KRX",
                calendar_date=date.today(),
            )
            allowed = bool(getattr(decision, "live_allowed", False))
            reason = str(getattr(decision, "reason_code", "") or "")
            return allowed, reason
    except Exception as exc:  # noqa: BLE001
        return False, type(exc).__name__


async def run_upbit_dry_run_smoke(
    *,
    duration_seconds: float = 90.0,
    symbol: str = "KRW-BTC",
    uba_id: int | None = None,
) -> ShadowSmokeReport:
    report = ShadowSmokeReport(broker="UPBIT")
    t0 = time.monotonic()
    since = datetime.now(timezone.utc)
    secrets: list[str] = []
    spy = _BrokerSpy()
    _force_dry_run_env()
    reset_dry_run_counters()
    await _shutdown()

    settings = get_settings()
    paper_id = int(settings.realtime_paper_account_id or 1)
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
        from stock_platform.broker.credential_vault_service import (
            BrokerCredentialVaultService,
        )

        try:
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
        from stock_platform.broker.upbit.private_client import UpbitPrivateClient

        client = UpbitPrivateClient(
            settings=settings.model_copy(
                update={
                    "upbit_access_key": access,
                    "upbit_secret_key": secret,
                    "upbit_use_mock": False,
                }
            )
        )
        try:
            accounts = await client.list_accounts()
        finally:
            await client.aclose()
        report.auth_ok = isinstance(accounts, list)
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
        strategy_id=942001,
    )

    from stock_platform.broker.adapter import BrokerAdapter
    import httpx

    quotes = 0
    with patch.object(BrokerAdapter, "submit_order", spy.block_submit), patch.object(
        BrokerAdapter, "cancel_order", spy.block_cancel
    ), patch.object(BrokerAdapter, "replace_order", spy.block_replace):
        deadline = time.monotonic() + float(duration_seconds)
        async with httpx.AsyncClient(timeout=8.0) as http:
            while time.monotonic() < deadline:
                try:
                    r = await http.get(
                        "https://api.upbit.com/v1/ticker",
                        params={"markets": symbol},
                    )
                    r.raise_for_status()
                    px = Decimal(str(r.json()[0]["trade_price"]))
                    now = datetime.now(timezone.utc)
                    quotes += 1
                    await _publish(
                        RealtimeQuote(
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
                            source_code="UPBIT_DRY_RUN",
                        )
                    )
                    if quotes % 15 == 0:
                        await _inject_ma_cross_burst(
                            exchange_code="UPBIT",
                            symbol=symbol,
                            mid=px,
                            source_code="UPBIT_DRY_BURST",
                        )
                except Exception as exc:  # noqa: BLE001
                    report.errors.append(f"UPBIT_TICKER:{type(exc).__name__}")
                await asyncio.sleep(1.0)

        # Kill probe
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
            with SessionLocal() as session:
                scope = uba_kill_switch_scope(int(uba_id))
                KillSwitchService(session).activate_scope(
                    scope_code=scope, actor="DRY_RUN", reason="probe"
                )
                session.commit()
                before = int(
                    session.execute(
                        text(
                            """
                            SELECT COUNT(*) FROM trading.trading_order
                            WHERE user_broker_account_id=:u
                              AND reject_code='DRY_RUN_BLOCKED'
                              AND side_code='BUY'
                              AND created_at >= :t
                            """
                        ),
                        {"u": int(uba_id), "t": since},
                    ).scalar_one()
                )
            await _inject_ma_cross_burst(
                exchange_code="UPBIT",
                symbol=symbol,
                mid=Decimal("100000000"),
                source_code="UPBIT_KILL_DRY",
            )
            await asyncio.sleep(2.0)
            with SessionLocal() as session:
                after = int(
                    session.execute(
                        text(
                            """
                            SELECT COUNT(*) FROM trading.trading_order
                            WHERE user_broker_account_id=:u
                              AND reject_code='DRY_RUN_BLOCKED'
                              AND side_code='BUY'
                              AND created_at >= :t
                            """
                        ),
                        {"u": int(uba_id), "t": since},
                    ).scalar_one()
                )
                report.kill_blocked = after <= before
                report.detail["kill_before_buy"] = before
                report.detail["kill_after_buy"] = after
                KillSwitchService(session).deactivate_scope(
                    scope_code=scope, actor="DRY_RUN", reason="done"
                )
                session.commit()
        except Exception as exc:  # noqa: BLE001
            report.errors.append(f"KILL:{type(exc).__name__}")

    with SessionLocal() as session:
        report.shadow_intents = _dry_run_count(session, int(uba_id), since)
        report.duplicate_intents = _dup_dry_run(session, int(uba_id), since)
        rows = session.execute(
            text(
                """
                SELECT metadata_payload
                FROM trading.trading_order
                WHERE user_broker_account_id=:u
                  AND reject_code='DRY_RUN_BLOCKED'
                  AND created_at >= :t
                ORDER BY order_id DESC LIMIT 1
                """
            ),
            {"u": int(uba_id), "t": since},
        ).scalars().all()
        if rows:
            meta = rows[0] if isinstance(rows[0], dict) else dict(rows[0] or {})
            report.detail["pre_submit_ok"] = bool(meta.get("pre_submit_ok"))
            report.detail["pre_submit_payload"] = meta.get("pre_submit_payload")

    report.quotes_received = quotes
    report.broker_submit_calls = spy.submit
    report.broker_cancel_calls = spy.cancel
    report.broker_replace_calls = spy.replace
    report.detail["hub"] = get_realtime_market_data_hub().status()
    report.detail["execution"] = realtime_execution_runner.status()
    report.detail["dry_run_counters"] = dry_run_counters()
    await _shutdown()
    report.runtime_stopped = True
    report.duration_seconds = time.monotonic() - t0
    report.secret_leaked = not _no_secret(str(report.to_public_dict()), secrets)
    return report


async def run_kiwoom_dry_run_smoke(
    *,
    duration_seconds: float = 90.0,
    symbol: str = "005930",
    uba_id: int | None = None,
) -> ShadowSmokeReport:
    report = ShadowSmokeReport(broker="KIWOOM")
    t0 = time.monotonic()
    since = datetime.now(timezone.utc)
    secrets: list[str] = []
    spy = _BrokerSpy()
    _force_dry_run_env()
    reset_dry_run_counters()
    await _shutdown()

    krx_open, krx_reason = _krx_live_allowed()
    report.detail["krx_live_allowed"] = krx_open
    report.detail["krx_reason"] = krx_reason

    settings = get_settings()
    paper_id = int(settings.realtime_paper_account_id or 1)
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

    rest = None
    try:
        from stock_platform.broker.kiwoom.config import KiwoomOrderConfig
        from stock_platform.broker.kiwoom.http_client import KiwoomRestClient
        from stock_platform.broker.kiwoom.rate_limiter import KiwoomRateLimiters
        from stock_platform.broker.kiwoom.token_cache import KiwoomTokenCache
        from stock_platform.broker.kiwoom.token_client import KiwoomTokenClient

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
                token = KiwoomTokenClient(config).issue()
                report.detail["auth_base"] = base
                break
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
        if token is None or config is None:
            raise last_exc or RuntimeError("KIWOOM_AUTH_FAILED")
        report.auth_ok = bool(getattr(token, "token", None))
        report.detail["uba_id"] = int(uba_id)
        rest = KiwoomRestClient(
            config=config,
            token_cache=KiwoomTokenCache(KiwoomTokenClient(config)),
            rate_limiters=KiwoomRateLimiters(),
        )
    except Exception as exc:  # noqa: BLE001
        report.auth_ok = False
        report.errors.append(f"KIWOOM_AUTH:{type(exc).__name__}")
        report.detail["uba_id"] = int(uba_id)
        # 장외·인증 장애 시에도 Risk 차단·ORM Pause는 검증한다 (실주문 없음)
        if krx_open:
            report.duration_seconds = time.monotonic() - t0
            return report
        report.detail["quote_source"] = "SYNTHETIC_CLOSED_MARKET"
        rest = None

    _configure_runner(paper_id=paper_id, uba_id=int(uba_id))
    await _boot_hub_consumer(
        user_id=user_id,
        uba_id=int(uba_id),
        broker="KIWOOM",
        market_type="STOCK",
        symbols=[symbol],
        strategy_id=942002,
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
                if rest is not None:
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
                    )
                    if price in (None, ""):
                        raise ValueError("NO_PRICE_FIELD")
                    px = Decimal(str(price).lstrip("+-").replace(",", ""))
                else:
                    px = last_mid
                last_mid = px
                if quotes == 0 or quotes % 20 == 0:
                    await _inject_ma_cross_burst(
                        exchange_code="KRX",
                        symbol=symbol,
                        mid=px,
                        source_code="KIWOOM_DRY_BURST",
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
                        source_code=(
                            "KIWOOM_DRY_RUN"
                            if rest is not None
                            else "KIWOOM_CLOSED_SYNTH"
                        ),
                    )
                )
                quotes += 1
            except Exception as exc:  # noqa: BLE001
                report.errors.append(f"KIWOOM_QUOTE:{type(exc).__name__}")
                await asyncio.sleep(2.0)
                continue
            await asyncio.sleep(1.0)

        # Pause ORM probe
        try:
            from stock_platform.broker.recovery_adapter import (
                AccountRecoveryContext,
            )
            from stock_platform.broker.recovery_lock import (
                RecoveryAccountLockService,
            )

            with SessionLocal() as session:
                lock = RecoveryAccountLockService(session)
                ctx = AccountRecoveryContext(
                    broker_code="KIWOOM",
                    user_id=user_id,
                    market_type="STOCK",
                    user_broker_account_id=int(uba_id),
                )
                _row, paused_before = lock.acquire(
                    ctx, holder="DRY_RUN_PAUSE", ttl_seconds=60
                )
                session.commit()
                before = _dry_run_count(session, int(uba_id), since)
            await _inject_ma_cross_burst(
                exchange_code="KRX",
                symbol=symbol,
                mid=last_mid,
                source_code="KIWOOM_PAUSE_DRY",
            )
            await asyncio.sleep(2.0)
            with SessionLocal() as session:
                after = _dry_run_count(session, int(uba_id), since)
                report.pause_blocked = after <= before
                report.detail["pause_via_orm"] = True
                RecoveryAccountLockService(session).release(
                    AccountRecoveryContext(
                        broker_code="KIWOOM",
                        user_id=user_id,
                        market_type="STOCK",
                        user_broker_account_id=int(uba_id),
                    ),
                    status_code="SUCCESS",
                    keep_paused=False,
                    run_id=None,
                    paused_before=bool(paused_before),
                )
                session.commit()
        except Exception as exc:  # noqa: BLE001
            report.errors.append(f"PAUSE:{type(exc).__name__}")

    with SessionLocal() as session:
        report.shadow_intents = _dry_run_count(session, int(uba_id), since)
        report.duplicate_intents = _dup_dry_run(session, int(uba_id), since)
        broker_ids = session.execute(
            text(
                """
                SELECT COUNT(*) FROM trading.trading_order
                WHERE user_broker_account_id=:u
                  AND broker_order_id IS NOT NULL
                  AND created_at >= :t
                """
            ),
            {"u": int(uba_id), "t": since},
        ).scalar_one()
        if broker_ids:
            report.errors.append("BROKER_ORDER_ID_CREATED")

    report.quotes_received = quotes
    report.broker_submit_calls = spy.submit
    report.broker_cancel_calls = spy.cancel
    report.broker_replace_calls = spy.replace
    report.detail["hub"] = get_realtime_market_data_hub().status()
    report.detail["market_closed_expected_zero"] = not krx_open
    await _shutdown()
    report.runtime_stopped = True
    report.duration_seconds = time.monotonic() - t0
    report.secret_leaked = not _no_secret(str(report.to_public_dict()), secrets)
    return report
