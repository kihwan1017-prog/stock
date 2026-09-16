"""STEP 8-9B — Upbit 5,000원 LIVE 직전 운영 점검 (조회 전용).

절대 금지: create_order / cancel_order / --execute-live / ARM 실행.
허용: DB 조회, Credential verify(조회), 잔고·호가·미체결 조회, dry-run 생성·실행.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from stock_platform.broker.fee_policy import UpbitFeePolicy
from stock_platform.broker.upbit.rules import (
    UPBIT_MIN_NOTIONAL_KRW,
    round_upbit_price,
    round_upbit_volume,
    upbit_tick_size,
    volume_from_krw_buy_amount,
)
from stock_platform.common.settings import get_settings
from stock_platform.order.entities import TradingOrderEntity
from stock_platform.risk_engine.kill_switch_models import KillSwitchStatus
from stock_platform.risk_engine.kill_switch_service import KillSwitchService
from stock_platform.trading.account_models import UserBrokerAccount
from stock_platform.trading.live_arm_service import (
    DEFAULT_ARM_TTL_SECONDS,
    LiveArmService,
)
from stock_platform.trading.upbit_live_smoke_constants import (
    DEFAULT_ALLOWLIST,
    DEFAULT_SMOKE_AMOUNT,
    MAX_SMOKE_AMOUNT,
)


ZERO = Decimal("0")
FEE = UpbitFeePolicy()
KST = ZoneInfo("Asia/Seoul")


def _mask_name(value: str | None) -> str:
    raw = (value or "").strip()
    if not raw:
        return "(empty)"
    if len(raw) <= 2:
        return raw[0] + "*"
    return f"{raw[0]}***{raw[-1]}"


def _mask_uba_id(uba_id: int) -> str:
    raw = str(int(uba_id))
    if len(raw) <= 2:
        return f"UBA#**{raw}"
    return f"UBA#***{raw[-2:]}"


def _dec(value: Any) -> Decimal:
    try:
        return Decimal(str(value))
    except Exception:  # noqa: BLE001
        return ZERO


@dataclass(slots=True)
class LimitCandidate:
    label: str
    limit_price: str
    quantity: str
    estimated_amount: str
    estimated_fee: str
    fill_likelihood: str
    unfilled_likelihood: str
    auto_cancel_seconds: int
    slippage_ok: bool
    min_notional_ok: bool
    orderable: bool


@dataclass(slots=True)
class MarketQuote:
    market: str
    trade_price: str | None
    bid_1: str | None
    ask_1: str | None
    tick_size: str | None
    acc_trade_volume_24h: str | None
    qty_for_5000: str | None
    estimated_amount: str | None
    estimated_fee: str | None
    min_notional_ok: bool
    slippage_note: str
    orderable: bool
    candidates: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None


@dataclass(slots=True)
class UbaCandidateView:
    uba_id_masked: str
    uba_id: int  # 운영자 선택용 — 보고서 본문에서만 사용, 완료보고는 마스킹
    user_id: int
    username_masked: str
    account_alias_masked: str
    broker: str
    account_kind: str
    credential_registered: bool
    credential_verify_status: str | None
    live_on: bool
    armed: bool
    arm_expires_at: str | None
    kill_switch: str
    runtime_paused: bool | None
    trading_scheduler_paused: bool | None
    tracking_scheduler_ok: bool | None
    open_order_count_db: int
    today_order_count: int
    today_pnl: str | None
    risk_max_order_amount: str | None
    risk_max_order_qty: str | None
    open_order_limit: str | None
    allowlist: list[str]


class UpbitLiveOpsInspectionService:
    """조회 전용 운영 점검. 주문/취소/ARM/실주문 호출 금지."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._settings = get_settings()
        self._blockers: list[str] = []
        self._warnings: list[str] = []

    def inspect(
        self,
        *,
        amount: Decimal = DEFAULT_SMOKE_AMOUNT,
        actor: str = "STEP8_9B_OPS",
        write_report: bool = True,
        report_dir: Path | None = None,
    ) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        amount_d = Decimal(str(amount))
        if amount_d <= ZERO:
            self._blockers.append("AMOUNT: must be > 0")
        if amount_d > MAX_SMOKE_AMOUNT:
            self._blockers.append(
                f"AMOUNT: {amount_d} > max {MAX_SMOKE_AMOUNT}"
            )

        db_info = self._db_info()
        uba_rows = self._list_upbit_ubas()
        if not uba_rows:
            self._blockers.append(
                "UBA: 운영 DB에 UPBIT UserBrokerAccount 후보가 0건"
            )

        kill = KillSwitchService(self._session).get_state()
        kill_active = kill.status == KillSwitchStatus.ACTIVE
        if kill_active:
            self._blockers.append("KILL_SWITCH: ACTIVE")

        system = self._system_flags()
        risk_states = self._post_fill_and_run_states()
        for code, count in risk_states.items():
            if code in {
                "unknown_runs",
                "manual_review_runs",
                "mismatch_post_fill",
                "expired_post_fill",
                "failed_post_fill",
            } and int(count) > 0:
                self._blockers.append(f"{code}={count}")

        if int(risk_states.get("db_open_orders_upbit", 0)) > 0:
            self._blockers.append(
                f"DB_OPEN_ORDERS={risk_states['db_open_orders_upbit']}"
            )

        candidates: list[dict[str, Any]] = []
        for uba in uba_rows:
            view = self._inspect_uba(uba, kill_active=kill_active)
            candidates.append(asdict(view))
            if view.open_order_count_db > 0:
                self._blockers.append(
                    f"UBA_OPEN_ORDERS:{_mask_uba_id(view.uba_id)}"
                    f"={view.open_order_count_db}"
                )

        markets = self._inspect_markets(amount=amount_d)
        arm_readiness = self._arm_readiness()
        dry_run_cmds = self._build_dry_run_commands(
            candidates=candidates, markets=markets, amount=amount_d
        )
        dry_run_results: list[dict[str, Any]] = []
        if not candidates:
            dry_run_results.append(
                {
                    "status": "BLOCKER",
                    "ready": False,
                    "blockers": [
                        "DRY_RUN_NOT_EXECUTED: UPBIT UBA 후보 0건"
                    ],
                    "warnings": [],
                    "note": (
                        "UBA 생성·Credential 등록 후 "
                        "--run-dry-run --uba-id ... 로 재실행"
                    ),
                }
            )
        live_template = None
        release_ok = not self._blockers and bool(candidates)
        # 실주문 템플릿은 모든 게이트 PASS일 때만 (UBA/시세 수동 선택 placeholder)
        if release_ok:
            live_template = self._build_live_template(
                amount=amount_d, markets=markets
            )
        else:
            self._warnings.append(
                "실주문 명령 템플릿 미생성 — Release 게이트 미충족"
            )

        post_check_cmds = self._post_execution_check_commands()
        emergency = self._emergency_procedures()

        verdict = "READY" if release_ok else "NOT_READY"
        payload: dict[str, Any] = {
            "step": "8-9B",
            "checked_at": now.isoformat(),
            "actor": actor,
            "verdict": verdict,
            "execute_live_ran": False,
            "db": db_info,
            "kill_switch": {
                "status": str(kill.status),
                "reason": kill.reason,
            },
            "system": system,
            "uba_candidate_count": len(candidates),
            "uba_candidates_masked": [
                {
                    "uba_id_masked": c["uba_id_masked"],
                    "user_id": c["user_id"],
                    "username_masked": c["username_masked"],
                    "broker": c["broker"],
                    "live_on": c["live_on"],
                    "armed": c["armed"],
                    "credential_registered": c["credential_registered"],
                    "credential_verify_status": c[
                        "credential_verify_status"
                    ],
                }
                for c in candidates
            ],
            "uba_candidates_detail": candidates,
            "risk_states": risk_states,
            "markets": markets,
            "arm_readiness": arm_readiness,
            "dry_run_commands": dry_run_cmds,
            "dry_run_results": dry_run_results,
            "live_command_template": live_template,
            "post_execution_checks": post_check_cmds,
            "emergency_procedures": emergency,
            "blockers": list(self._blockers),
            "warnings": list(self._warnings),
            "release_blocker_count": len(self._blockers),
            "amount": str(amount_d),
            "allowlist": list(self._allowlist()),
            "notes": [
                "실주문(--execute-live) 미실행",
                "ARM 미실행 / arm_token 미생성",
                "UBA·Market 자동 선택 금지 — 운영자 수동 선택",
            ],
        }

        if write_report:
            report_path = self._write_report(
                payload, report_dir=report_dir, now=now
            )
            payload["report_path"] = str(report_path)
        return payload

    def run_dry_runs(
        self,
        *,
        uba_id: int,
        market: str,
        limit_price: Decimal,
        amount: Decimal = DEFAULT_SMOKE_AMOUNT,
        actor: str = "STEP8_9B_OPS",
    ) -> dict[str, Any]:
        """조회 파이프라인 dry-run만 실행 (주문 생성 없음)."""

        from stock_platform.trading.upbit_live_smoke_service import (
            UpbitLiveSmokeService,
        )

        svc = UpbitLiveSmokeService(self._session)
        result = svc.dry_run(
            user_broker_account_id=int(uba_id),
            market=str(market).upper(),
            side="BUY",
            amount=Decimal(str(amount)),
            limit_price=Decimal(str(limit_price)),
            actor=actor,
            arm_token=None,
            skip_live_network=False,
        )
        # 민감 제거
        safe = json.loads(json.dumps(result, default=str))
        if isinstance(safe, dict):
            safe.pop("arm_token", None)
            pf = safe.get("preflight")
            if isinstance(pf, dict):
                pf.pop("arm_token", None)
        blockers = list((safe.get("preflight") or {}).get("blockers") or [])
        warnings = list((safe.get("preflight") or {}).get("warnings") or [])
        ready = bool((safe.get("preflight") or {}).get("ready"))
        status = "PASS" if ready and not blockers else (
            "WARNING" if warnings and not blockers else "BLOCKER"
        )
        if blockers:
            status = "BLOCKER"
        return {
            "status": status,
            "ready": ready,
            "blockers": blockers,
            "warnings": warnings,
            "result": safe,
        }

    def _db_info(self) -> dict[str, Any]:
        db_name = self._session.execute(
            text("SELECT current_database()")
        ).scalar()
        db_user = self._session.execute(
            text("SELECT current_user")
        ).scalar()
        try:
            alembic = self._session.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar()
        except Exception as exc:  # noqa: BLE001
            alembic = f"ERR:{type(exc).__name__}"
            self._blockers.append(f"ALEMBIC: {type(exc).__name__}")
        uba_total = int(
            self._session.scalar(
                select(func.count()).select_from(UserBrokerAccount)
            )
            or 0
        )
        return {
            "connected": True,
            "database": db_name,
            "db_user": db_user,
            "alembic_head": alembic,
            "uba_total": uba_total,
            "expected_alembic": "o4e5f6a7b8c9",
            "alembic_ok": str(alembic) == "o4e5f6a7b8c9",
        }

    def _list_upbit_ubas(self) -> list[UserBrokerAccount]:
        return list(
            self._session.scalars(
                select(UserBrokerAccount)
                .where(func.upper(UserBrokerAccount.broker_code) == "UPBIT")
                .order_by(UserBrokerAccount.user_broker_account_id)
            ).all()
        )

    def _inspect_uba(
        self, uba: UserBrokerAccount, *, kill_active: bool
    ) -> UbaCandidateView:
        username = self._session.execute(
            text('SELECT username FROM auth."user" WHERE user_id = :uid'),
            {"uid": int(uba.user_id)},
        ).scalar()

        cred_registered = False
        cred_status: str | None = None
        try:
            from stock_platform.broker.credential_vault_service import (
                BrokerCredentialVaultService,
            )

            status = BrokerCredentialVaultService(self._session).status(
                user_broker_account_id=int(uba.user_broker_account_id),
                broker_code="UPBIT",
            )
            cred_registered = bool(status.connected)
            cred_status = status.verification_status
            # 네트워크 verify (조회 전용) — 시크릿 로그 금지
            if cred_registered:
                try:
                    BrokerCredentialVaultService(self._session).verify(
                        user_broker_account_id=int(
                            uba.user_broker_account_id
                        ),
                        owner_user_id=None,
                        actor="STEP8_9B_OPS_READONLY",
                        admin=True,
                    )
                    cred_status = "VERIFIED"
                except Exception as exc:  # noqa: BLE001
                    cred_status = f"VERIFY_FAIL:{type(exc).__name__}"
                    self._blockers.append(
                        f"CREDENTIAL_VERIFY:{_mask_uba_id(int(uba.user_broker_account_id))}"
                        f":{type(exc).__name__}"
                    )
            else:
                self._blockers.append(
                    f"CREDENTIAL_MISSING:{_mask_uba_id(int(uba.user_broker_account_id))}"
                )
        except Exception as exc:  # noqa: BLE001
            cred_status = type(exc).__name__
            self._warnings.append(f"credential_status_err:{type(exc).__name__}")

        arm = LiveArmService(self._session)
        arm.expire_if_needed(int(uba.user_broker_account_id))
        arm_status = arm.get_arm_status(int(uba.user_broker_account_id))

        open_count = self._db_open_orders(int(uba.user_broker_account_id))
        daily_count = self._daily_orders(int(uba.user_broker_account_id))
        risk = self._risk_for_uba(int(uba.user_broker_account_id))

        runtime_paused = self._runtime_paused(
            int(uba.user_broker_account_id)
        )
        trading_paused = self._trading_scheduler_paused()
        tracking_ok = bool(
            getattr(self._settings, "upbit_live_track_enabled", True)
        )

        if runtime_paused is False:
            self._blockers.append(
                f"RUNTIME_NOT_PAUSED:{_mask_uba_id(int(uba.user_broker_account_id))}"
            )
        if trading_paused is False:
            self._blockers.append("TRADING_SCHEDULER_NOT_PAUSED")
        if not tracking_ok:
            self._blockers.append("TRACKING_SCHEDULER_DISABLED")

        return UbaCandidateView(
            uba_id_masked=_mask_uba_id(int(uba.user_broker_account_id)),
            uba_id=int(uba.user_broker_account_id),
            user_id=int(uba.user_id),
            username_masked=_mask_name(str(username) if username else None),
            account_alias_masked=_mask_name(uba.account_alias),
            broker=str(uba.broker_code).upper(),
            account_kind="LIVE",
            credential_registered=cred_registered,
            credential_verify_status=cred_status,
            live_on=bool(uba.live_order_enabled),
            armed=bool(arm_status.get("live_armed")),
            arm_expires_at=arm_status.get("arm_expires_at"),
            kill_switch="ON" if kill_active else "OFF",
            runtime_paused=runtime_paused,
            trading_scheduler_paused=trading_paused,
            tracking_scheduler_ok=tracking_ok,
            open_order_count_db=open_count,
            today_order_count=daily_count,
            today_pnl=None,
            risk_max_order_amount=risk.get("max_order_amount"),
            risk_max_order_qty=risk.get("max_order_qty"),
            open_order_limit=risk.get("open_order_limit"),
            allowlist=list(self._allowlist()),
        )

    def _system_flags(self) -> dict[str, Any]:
        s = self._settings
        post_fill_ok = bool(getattr(s, "post_fill_verify_enabled", True))
        track_ok = bool(getattr(s, "upbit_live_track_enabled", True))
        if not post_fill_ok:
            self._blockers.append("POST_FILL_SCHEDULER_DISABLED")
        if bool(s.upbit_use_mock):
            self._blockers.append(
                "UPBIT_USE_MOCK=true (LIVE 실주문 전 mock 해제 필요)"
            )
        if not bool(s.upbit_live_order_enabled):
            self._warnings.append(
                "UPBIT_LIVE_ORDER_ENABLED=false "
                "(실주문 전 명시적 활성화 필요)"
            )
        # env 키 존재 여부만 (값 출력 금지) — UBA Vault와 별개
        env_keys_present = bool(
            (getattr(s, "upbit_access_key", "") or "").strip()
            and (getattr(s, "upbit_secret_key", "") or "").strip()
        )
        if not env_keys_present:
            self._warnings.append(
                "ENV_UPBIT_KEYS_NOT_CONFIGURED "
                "(UBA Vault Credential이 주 경로)"
            )
        return {
            "upbit_use_mock": bool(s.upbit_use_mock),
            "upbit_live_order_enabled_setting": bool(
                s.upbit_live_order_enabled
            ),
            "env_upbit_keys_configured": env_keys_present,
            "post_fill_verify_enabled": post_fill_ok,
            "post_fill_verify_ttl_seconds": int(
                getattr(s, "post_fill_verify_ttl_seconds", 60)
            ),
            "upbit_live_track_enabled": track_ok,
            "upbit_live_track_poll_seconds": int(
                getattr(s, "upbit_live_track_poll_seconds", 2)
            ),
            "upbit_live_smoke_order_watch_seconds": int(
                getattr(s, "upbit_live_smoke_order_watch_seconds", 60)
            ),
            "upbit_live_smoke_auto_cancel": bool(
                getattr(s, "upbit_live_smoke_auto_cancel", True)
            ),
            "arm_ttl_default_seconds": DEFAULT_ARM_TTL_SECONDS,
            "max_smoke_amount": str(MAX_SMOKE_AMOUNT),
            "trading_scheduler_treat_paused_flag": bool(
                getattr(s, "upbit_live_smoke_treat_scheduler_paused", False)
            ),
        }

    def _post_fill_and_run_states(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "db_open_orders_upbit": 0,
            "unknown_runs": 0,
            "manual_review_runs": 0,
            "pending_post_fill": 0,
            "waiting_snapshot": 0,
            "mismatch_post_fill": 0,
            "expired_post_fill": 0,
            "failed_post_fill": 0,
        }
        open_statuses = (
            "CREATED",
            "PENDING",
            "SENT",
            "ACCEPTED",
            "PARTIALLY_FILLED",
            "CANCEL_REQUESTED",
            "REPLACE_REQUESTED",
            "UNKNOWN",
        )
        out["db_open_orders_upbit"] = int(
            self._session.scalar(
                select(func.count())
                .select_from(TradingOrderEntity)
                .where(
                    TradingOrderEntity.broker_code == "UPBIT",
                    TradingOrderEntity.status_code.in_(open_statuses),
                )
            )
            or 0
        )
        # live_validation_run
        try:
            rows = self._session.execute(
                text(
                    """
                    SELECT status_code, count(*)::int AS cnt
                    FROM trading.live_validation_run
                    GROUP BY 1
                    """
                )
            ).mappings().all()
            by_status = {
                str(r["status_code"] or "").upper(): int(r["cnt"])
                for r in rows
            }
            out["unknown_runs"] = by_status.get("UNKNOWN", 0)
            out["manual_review_runs"] = by_status.get(
                "MANUAL_REVIEW_REQUIRED", 0
            )
            out["live_validation_by_status"] = by_status
            mr_flag = self._session.execute(
                text(
                    """
                    SELECT count(*)::int
                    FROM trading.live_validation_run
                    WHERE manual_review_required IS TRUE
                    """
                )
            ).scalar()
            out["manual_review_flag_count"] = int(mr_flag or 0)
            if int(mr_flag or 0) > 0:
                self._blockers.append(
                    f"MANUAL_REVIEW_FLAG={mr_flag}"
                )
        except Exception as exc:  # noqa: BLE001
            self._warnings.append(
                f"live_validation_run_query:{type(exc).__name__}"
            )

        try:
            pf_rows = self._session.execute(
                text(
                    """
                    SELECT status_code, count(*)::int AS cnt
                    FROM trading.post_fill_verification
                    GROUP BY 1
                    """
                )
            ).mappings().all()
            by_pf = {
                str(r["status_code"] or "").upper(): int(r["cnt"])
                for r in pf_rows
            }
            out["pending_post_fill"] = (
                by_pf.get("PENDING", 0)
                + by_pf.get("IN_PROGRESS", 0)
                + by_pf.get("CLAIMED", 0)
            )
            out["waiting_snapshot"] = by_pf.get("WAITING_SNAPSHOT", 0)
            out["mismatch_post_fill"] = by_pf.get("MISMATCH", 0)
            out["expired_post_fill"] = by_pf.get("EXPIRED", 0)
            out["failed_post_fill"] = by_pf.get("FAILED", 0)
            out["post_fill_by_status"] = by_pf
            # TTL 초과 pending
            ttl = int(
                getattr(self._settings, "post_fill_verify_ttl_seconds", 60)
            )
            stale = self._session.execute(
                text(
                    """
                    SELECT count(*)::int
                    FROM trading.post_fill_verification
                    WHERE upper(status_code) IN
                      ('PENDING','IN_PROGRESS','CLAIMED','WAITING_SNAPSHOT')
                      AND created_at < (now() AT TIME ZONE 'utc')
                          - make_interval(secs => :ttl)
                    """
                ),
                {"ttl": ttl},
            ).scalar()
            out["pending_post_fill_stale_ttl"] = int(stale or 0)
            if int(stale or 0) > 0:
                self._blockers.append(
                    f"PENDING_POST_FILL_STALE={stale}"
                )
        except Exception as exc:  # noqa: BLE001
            self._warnings.append(
                f"post_fill_query:{type(exc).__name__}"
            )
        return out

    def _inspect_markets(self, *, amount: Decimal) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        allow = self._allowlist()
        watch_sec = int(
            getattr(
                self._settings, "upbit_live_smoke_order_watch_seconds", 60
            )
        )
        try:
            tickers, books = self._fetch_public_quotes(allow)
        except Exception as exc:  # noqa: BLE001
            self._blockers.append(f"MARKET_QUOTE:{type(exc).__name__}")
            for m in allow:
                results.append(
                    asdict(
                        MarketQuote(
                            market=m,
                            trade_price=None,
                            bid_1=None,
                            ask_1=None,
                            tick_size=None,
                            acc_trade_volume_24h=None,
                            qty_for_5000=None,
                            estimated_amount=None,
                            estimated_fee=None,
                            min_notional_ok=False,
                            slippage_note="quote failed",
                            orderable=False,
                            error=type(exc).__name__,
                        )
                    )
                )
            return results

        for market in allow:
            ticker = tickers.get(market) or {}
            book = books.get(market) or {}
            units = book.get("orderbook_units") or []
            bid_1 = None
            ask_1 = None
            if units:
                first = units[0] if isinstance(units[0], dict) else {}
                bid_1 = _dec(first.get("bid_price"))
                ask_1 = _dec(first.get("ask_price"))
            trade_price = _dec(ticker.get("trade_price"))
            vol = ticker.get("acc_trade_volume_24h")
            if trade_price <= ZERO and ask_1 and ask_1 > ZERO:
                trade_price = ask_1

            if trade_price <= ZERO:
                results.append(
                    asdict(
                        MarketQuote(
                            market=market,
                            trade_price=None,
                            bid_1=str(bid_1) if bid_1 else None,
                            ask_1=str(ask_1) if ask_1 else None,
                            tick_size=None,
                            acc_trade_volume_24h=str(vol) if vol else None,
                            qty_for_5000=None,
                            estimated_amount=None,
                            estimated_fee=None,
                            min_notional_ok=False,
                            slippage_note="no trade_price",
                            orderable=False,
                            error="no_price",
                        )
                    )
                )
                self._warnings.append(f"{market}: no trade_price")
                continue

            tick = upbit_tick_size(trade_price)
            # 기본 수량 산출: ask_1 우선, 없으면 현재가
            ref_buy = ask_1 if ask_1 and ask_1 > ZERO else trade_price
            ref_buy = round_upbit_price(ref_buy)
            qty = (
                self._qty_for_amount(amount, ref_buy)
                if ref_buy > ZERO
                else ZERO
            )
            est_amt = (qty * ref_buy).quantize(Decimal("0.0001"))
            fee = FEE.fee_amount(notional=est_amt, is_maker=True)
            min_ok = est_amt >= UPBIT_MIN_NOTIONAL_KRW
            candidates = self._limit_candidates(
                trade_price=trade_price,
                ask_1=ask_1,
                amount=amount,
                watch_sec=watch_sec,
            )
            any_orderable = any(c.orderable for c in candidates)
            mq = MarketQuote(
                market=market,
                trade_price=str(trade_price),
                bid_1=str(bid_1) if bid_1 is not None else None,
                ask_1=str(ask_1) if ask_1 is not None else None,
                tick_size=str(tick),
                acc_trade_volume_24h=str(vol) if vol is not None else None,
                qty_for_5000=str(qty),
                estimated_amount=str(est_amt),
                estimated_fee=str(fee),
                min_notional_ok=min_ok,
                slippage_note="candidates evaluated vs trade_price",
                orderable=any_orderable and min_ok,
                candidates=[asdict(c) for c in candidates],
            )
            results.append(asdict(mq))
        return results

    def _limit_candidates(
        self,
        *,
        trade_price: Decimal,
        ask_1: Decimal | None,
        amount: Decimal,
        watch_sec: int,
    ) -> list[LimitCandidate]:
        from stock_platform.risk_engine.resolved_policy import (
            ResolvedRiskPolicyResolver,
        )

        # 시스템 기본 slippage (UBA 없으면 user_id=None 경로 회피)
        try:
            policy = ResolvedRiskPolicyResolver(self._session).resolve(
                user_id=None,
                user_broker_account_id=None,
            )
            slip_limit = Decimal(str(policy.max_slippage_rate))
        except Exception:  # noqa: BLE001
            slip_limit = Decimal("0.01")

        ask_raw = ask_1 if ask_1 and ask_1 > ZERO else trade_price
        # 호가 원값은 거래소 tick 준수 — 불필요 재양자화로 호가 왜곡 방지
        ask = Decimal(str(ask_raw))
        tick = upbit_tick_size(ask)
        one_tick_below = round_upbit_price(ask - tick)
        if one_tick_below >= ask:
            one_tick_below = round_upbit_price(ask - tick)
        if one_tick_below <= ZERO:
            one_tick_below = ask
        # 현재가 기준 slippage 한도 내 (BUY)
        max_buy = round_upbit_price(
            trade_price * (Decimal("1") + slip_limit)
        )
        slip_cap_price = ask if ask <= max_buy else max_buy

        specs = [
            ("ask_1", ask, "즉시체결 가능성 높음", "낮음"),
            (
                "ask_1_minus_1tick",
                one_tick_below,
                "중간 — 호가 개선 시 체결",
                "중간~높음",
            ),
            (
                "within_slippage_cap",
                slip_cap_price,
                "한도 내 — 가격에 따라 가변",
                "가변",
            ),
        ]
        out: list[LimitCandidate] = []
        for label, price, fill_n, unfill_n in specs:
            # ask_1은 호가 원값 유지 — tick 테이블 보수 반올림으로 왜곡 금지
            if label != "ask_1":
                price = round_upbit_price(price)
            else:
                price = Decimal(str(price))
            if price <= ZERO:
                continue
            qty = self._qty_for_amount(amount, price)
            est = (qty * price).quantize(Decimal("0.0001"))
            fee = FEE.fee_amount(notional=est, is_maker=True)
            slip = ZERO
            if trade_price > ZERO and price > trade_price:
                slip = (price - trade_price) / trade_price
            slip_ok = slip <= slip_limit
            min_ok = est >= UPBIT_MIN_NOTIONAL_KRW
            orderable = slip_ok and min_ok and qty > ZERO
            out.append(
                LimitCandidate(
                    label=label,
                    limit_price=str(price),
                    quantity=str(qty),
                    estimated_amount=str(est),
                    estimated_fee=str(fee),
                    fill_likelihood=fill_n,
                    unfilled_likelihood=unfill_n,
                    auto_cancel_seconds=watch_sec,
                    slippage_ok=slip_ok,
                    min_notional_ok=min_ok,
                    orderable=orderable,
                )
            )
        return out

    def _fetch_public_quotes(
        self, markets: list[str]
    ) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
        base = (self._settings.upbit_base_url or "https://api.upbit.com").rstrip(
            "/"
        )
        markets_csv = ",".join(markets)
        with httpx.Client(timeout=10.0) as client:
            t_resp = client.get(
                f"{base}/v1/ticker", params={"markets": markets_csv}
            )
            t_resp.raise_for_status()
            tickers_raw = t_resp.json()
            o_resp = client.get(
                f"{base}/v1/orderbook", params={"markets": markets_csv}
            )
            o_resp.raise_for_status()
            books_raw = o_resp.json()
        tickers: dict[str, dict[str, Any]] = {}
        for row in tickers_raw if isinstance(tickers_raw, list) else []:
            if isinstance(row, dict) and row.get("market"):
                tickers[str(row["market"]).upper()] = row
        books: dict[str, dict[str, Any]] = {}
        for row in books_raw if isinstance(books_raw, list) else []:
            if isinstance(row, dict) and row.get("market"):
                books[str(row["market"]).upper()] = row
        return tickers, books

    def _arm_readiness(self) -> dict[str, Any]:
        # ARM 실행·토큰 생성 없음 — 정책/코드 경로만 확인
        return {
            "live_approval_possible": True,
            "arm_possible_when_live_on": True,
            "arm_ttl_seconds_default": DEFAULT_ARM_TTL_SECONDS,
            "admin_role_required": True,
            "arm_token_security": (
                "one-time hash only; plaintext never stored/logged"
            ),
            "rearm_invalidates_previous_token": True,
            "disarm_supported": True,
            "expire_turns_live_off": True,
            "armed_this_step": False,
            "arm_token_created": False,
            "note": "STEP 8-9B에서는 ARM을 실행하지 않음",
        }

    def _build_dry_run_commands(
        self,
        *,
        candidates: list[dict[str, Any]],
        markets: list[dict[str, Any]],
        amount: Decimal,
    ) -> list[dict[str, Any]]:
        cmds: list[dict[str, Any]] = []
        uba_placeholder = (
            str(candidates[0]["uba_id"]) if candidates else "<UBA_ID>"
        )
        for m in markets:
            market = m["market"]
            for cand in m.get("candidates") or []:
                if not cand.get("orderable"):
                    continue
                price = cand["limit_price"]
                ps = (
                    "python scripts/run_upbit_live_smoke_test.py `\n"
                    f"  --uba-id {uba_placeholder} `\n"
                    f"  --market {market} `\n"
                    "  --side BUY `\n"
                    f"  --amount {amount} `\n"
                    f"  --limit-price {price} `\n"
                    "  --dry-run"
                )
                cmds.append(
                    {
                        "market": market,
                        "candidate": cand["label"],
                        "limit_price": price,
                        "uba_id": uba_placeholder,
                        "powershell": ps,
                        "note": (
                            "UBA 자동선택 금지 — placeholder는 첫 후보 또는 "
                            "<UBA_ID>. 운영자가 교체."
                        ),
                    }
                )
        if not cmds:
            cmds.append(
                {
                    "market": "<MARKET>",
                    "candidate": "template",
                    "limit_price": "<PRICE>",
                    "uba_id": "<UBA_ID>",
                    "powershell": (
                        "python scripts/run_upbit_live_smoke_test.py `\n"
                        "  --uba-id <UBA_ID> `\n"
                        "  --market <MARKET> `\n"
                        "  --side BUY `\n"
                        f"  --amount {amount} `\n"
                        "  --limit-price <PRICE> `\n"
                        "  --dry-run"
                    ),
                    "note": "주문 가능 후보 없음 — 템플릿만 제공",
                }
            )
        return cmds

    def _build_live_template(
        self, *, amount: Decimal, markets: list[dict[str, Any]]
    ) -> dict[str, Any]:
        # 추천은 참고용 — 자동 확정 아님
        pick_market = None
        pick_price = None
        for m in markets:
            for cand in m.get("candidates") or []:
                if cand.get("orderable") and cand.get("label") == (
                    "ask_1_minus_1tick"
                ):
                    pick_market = m["market"]
                    pick_price = cand["limit_price"]
                    break
            if pick_market:
                break
        if not pick_market:
            for m in markets:
                for cand in m.get("candidates") or []:
                    if cand.get("orderable"):
                        pick_market = m["market"]
                        pick_price = cand["limit_price"]
                        break
                if pick_market:
                    break
        return {
            "powershell": (
                "python scripts/run_upbit_live_smoke_test.py `\n"
                "  --uba-id <UBA_ID> `\n"
                f"  --market {pick_market or '<MARKET>'} `\n"
                "  --side BUY `\n"
                f"  --amount {amount} `\n"
                f"  --limit-price {pick_price or '<PRICE>'} `\n"
                "  --execute-live `\n"
                '  --confirmation-text "UPBIT-LIVE-ONE-ORDER" `\n'
                "  --arm-token <ONE_TIME_TOKEN>"
            ),
            "recommended_market_hint": pick_market,
            "recommended_limit_price_hint": pick_price,
            "warning": "생성만 함. Cursor/에이전트는 실행하지 않음.",
        }

    def _post_execution_check_commands(self) -> dict[str, Any]:
        return {
            "powershell": [
                "# live_validation_run 최근 조회",
                (
                    '.venv\\Scripts\\python -c "from sqlalchemy import text; '
                    "from stock_platform.database.session import get_session_factory; "
                    "s=get_session_factory()(); "
                    "rows=s.execute(text('SELECT run_id,status_code,broker_order_status,"
                    "manual_review_required,created_at FROM trading.live_validation_run "
                    "ORDER BY created_at DESC LIMIT 5')).mappings().all(); "
                    'print([dict(r) for r in rows]); s.close()"'
                ),
                "# Kill Switch / LIVE / ARM 상태 점검은 Admin UI 또는 기존 조회 API 사용",
                "# Broker 미체결: Upbit Open API list_orders(state=wait) — 주문/취소 호출 금지",
            ],
            "sql_readonly": [
                (
                    "SELECT run_id, status_code, broker_order_status, "
                    "manual_review_required, created_at "
                    "FROM trading.live_validation_run "
                    "ORDER BY created_at DESC LIMIT 20;"
                ),
                (
                    "SELECT status_code, count(*) "
                    "FROM trading.post_fill_verification GROUP BY 1;"
                ),
                (
                    "SELECT user_broker_account_id, live_order_enabled, "
                    "live_armed, arm_expires_at "
                    "FROM trading.user_broker_account "
                    "WHERE upper(broker_code)='UPBIT';"
                ),
                (
                    "SELECT active, reason, activated_at "
                    "FROM operation.kill_switch "
                    "WHERE scope_code='GLOBAL' LIMIT 1;"
                ),
                (
                    "SELECT order_id, status_code, broker_order_id, created_at "
                    "FROM trading.trading_order "
                    "WHERE broker_code='UPBIT' "
                    "ORDER BY created_at DESC LIMIT 20;"
                ),
            ],
            "manual_checks": [
                "Telegram 알림 수신 여부",
                "LIVE OFF / DISARM 확인",
                "Runtime Pause / 거래 Scheduler Pause 유지",
                "Tracking Scheduler 정상(미확정 주문 폴링)",
                "Audit 이벤트 존재",
            ],
        }

    def _emergency_procedures(self) -> dict[str, Any]:
        return {
            "UNKNOWN": [
                "추가 주문 금지",
                "Admin Live Validation 대시보드에서 Broker 재조회",
                "Manual Review Required 표시 확인",
                "Kill Switch 검토",
            ],
            "CANCEL_FAILED": [
                "Kill Switch ON (Admin Risk API)",
                "LIVE OFF / DISARM (정상 API)",
                "거래 Scheduler Pause 유지",
                "Broker 콘솔에서 미체결 수동 확인",
            ],
            "PARTIAL_FILL": [
                "Post-fill Verification 상태 조회",
                "부분 체결 잔량 자동취소 여부 확인",
                "추가 주문 금지",
            ],
            "BROKER_DOWN": [
                "신규 주문 금지",
                "Kill Switch 검토",
                "Tracker/Recovery Scheduler 상태 확인",
            ],
            "POST_FILL_MISMATCH": [
                "Manual Review",
                "잔고 스냅샷 재동기화(조회/sync API)",
                "추가 주문 금지",
            ],
            "POST_FILL_EXPIRED": [
                "TTL/재시도 설정 확인",
                "Manual Review",
                "추가 주문 금지",
            ],
            "LIVE_OFF_FAILED": [
                "Admin API 재시도",
                "Kill Switch ON",
                "ARM expire / DISARM API",
            ],
            "DISARM_FAILED": [
                "Admin DISARM 재시도",
                "ARM TTL 만료 대기(자동 LIVE OFF)",
                "Kill Switch 검토",
            ],
            "TRACKER_STOPPED": [
                "upbit_live_track_enabled 설정 확인",
                "프로세스/스케줄러 재기동(정상 기동 경로)",
                "미확정 주문 Manual Review",
            ],
            "TELEGRAM_MISSING": [
                "publisher 설정·dry-run 점검",
                "Audit 로그로 이벤트 대체 확인",
            ],
            "note": "DB 직접 UPDATE/DELETE SQL은 제공하지 않음",
        }

    def _allowlist(self) -> list[str]:
        raw = getattr(self._settings, "upbit_live_smoke_allowlist", "") or ""
        items = [
            x.strip().upper() for x in str(raw).split(",") if x.strip()
        ]
        return items or list(DEFAULT_ALLOWLIST)

    @staticmethod
    def _qty_for_amount(amount: Decimal, price: Decimal) -> Decimal:
        """KRW BUY 금액→수량 — 공통 volume_from_krw_buy_amount 재사용."""

        return volume_from_krw_buy_amount(amount=amount, price=price)

    def _db_open_orders(self, uba_id: int) -> int:
        open_statuses = (
            "CREATED",
            "PENDING",
            "SENT",
            "ACCEPTED",
            "PARTIALLY_FILLED",
            "CANCEL_REQUESTED",
            "REPLACE_REQUESTED",
            "UNKNOWN",
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

    def _daily_orders(self, uba_id: int) -> int:
        # LIVE Risk daily_order_limit 과 동일 집계 (미전송 retire 제외)
        from stock_platform.order.daily_risk_order_count import (
            count_daily_risk_orders,
        )

        return count_daily_risk_orders(self._session, int(uba_id))

    def _risk_for_uba(self, uba_id: int) -> dict[str, str | None]:
        try:
            from stock_platform.risk_engine.resolved_policy import (
                ResolvedRiskPolicyResolver,
            )

            uba = self._session.get(UserBrokerAccount, uba_id)
            policy = ResolvedRiskPolicyResolver(self._session).resolve(
                user_id=int(uba.user_id) if uba else None,
                user_broker_account_id=uba_id,
            )
            max_amt = getattr(policy, "max_order_amount", None)
            max_qty = getattr(policy, "max_order_quantity", None) or getattr(
                policy, "max_order_qty", None
            )
            open_lim = getattr(policy, "max_open_orders", None)
            # LIVE 스모크 한도 검사 (5,000~10,000)
            if max_amt is not None:
                amt = Decimal(str(max_amt))
                if amt < DEFAULT_SMOKE_AMOUNT:
                    self._blockers.append(
                        f"RISK_MAX_ORDER_AMOUNT<{DEFAULT_SMOKE_AMOUNT}:{amt}"
                    )
                if amt > MAX_SMOKE_AMOUNT:
                    self._warnings.append(
                        f"RISK_MAX_ORDER_AMOUNT>{MAX_SMOKE_AMOUNT}:{amt}"
                        " (스모크는 10,000 캡)"
                    )
            return {
                "max_order_amount": str(max_amt) if max_amt is not None else None,
                "max_order_qty": str(max_qty) if max_qty is not None else None,
                "open_order_limit": (
                    str(open_lim) if open_lim is not None else None
                ),
            }
        except Exception as exc:  # noqa: BLE001
            self._warnings.append(f"risk_resolve:{type(exc).__name__}")
            return {
                "max_order_amount": None,
                "max_order_qty": None,
                "open_order_limit": None,
            }

    def _runtime_paused(self, uba_id: int) -> bool | None:
        try:
            from stock_platform.strategy_deployment.runtime_manager import (
                dynamic_strategy_runtime_manager,
            )

            mgr = dynamic_strategy_runtime_manager
            if hasattr(mgr, "is_account_paused"):
                return bool(mgr.is_account_paused(uba_id))
            if hasattr(mgr, "account_runtimes_paused"):
                return bool(mgr.account_runtimes_paused(uba_id))
            # 런타임 미기동 시 Pause로 간주 (자동주문 없음)
            self._warnings.append("runtime_manager_no_pause_api")
            return True
        except Exception as exc:  # noqa: BLE001
            self._warnings.append(f"runtime_check:{type(exc).__name__}")
            return True

    def _trading_scheduler_paused(self) -> bool | None:
        settings = self._settings
        if bool(
            getattr(settings, "upbit_live_smoke_treat_scheduler_paused", False)
        ):
            return True
        try:
            from stock_platform.realtime.session_runtime import (
                realtime_trading_scheduler,
            )

            sched = realtime_trading_scheduler.scheduler
            # running=False → pause로 간주
            return not bool(getattr(sched, "running", False))
        except Exception as exc:  # noqa: BLE001
            self._warnings.append(f"scheduler_check:{type(exc).__name__}")
            # 프로세스 외부 점검이면 알 수 없음 → Warning, Blocker 아님
            return None

    def _write_report(
        self,
        payload: dict[str, Any],
        *,
        report_dir: Path | None,
        now: datetime,
    ) -> Path:
        root = Path(__file__).resolve().parents[3]
        out_dir = report_dir or (
            root / "docs" / "operations" / "reports"
        )
        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = now.astimezone(KST).strftime("%Y%m%d_%H%M%S")
        path = out_dir / f"UPBIT_LIVE_PREFLIGHT_{stamp}.md"

        # 완료보고용 마스킹 후보만 본문에 강조
        lines: list[str] = [
            f"# Upbit LIVE Preflight — STEP 8-9B ({stamp})",
            "",
            f"- checked_at: `{payload['checked_at']}`",
            f"- verdict: **{payload['verdict']}**",
            f"- execute_live_ran: `{payload['execute_live_ran']}`",
            f"- release_blocker_count: `{payload['release_blocker_count']}`",
            "",
            "## 1. DB",
            "```json",
            json.dumps(payload["db"], ensure_ascii=False, indent=2),
            "```",
            "",
            "## 2. UBA 후보 (마스킹)",
            "```json",
            json.dumps(
                payload["uba_candidates_masked"],
                ensure_ascii=False,
                indent=2,
            ),
            "```",
            "",
            "> 대상 UBA는 운영자가 직접 선택. 자동 선택 금지.",
            "",
            "## 3. Kill Switch / System",
            "```json",
            json.dumps(
                {
                    "kill_switch": payload["kill_switch"],
                    "system": payload["system"],
                },
                ensure_ascii=False,
                indent=2,
            ),
            "```",
            "",
            "## 4. Risk / Open / Post-fill",
            "```json",
            json.dumps(payload["risk_states"], ensure_ascii=False, indent=2),
            "```",
            "",
            "## 5. Market Quotes & Limit Candidates",
            "```json",
            json.dumps(payload["markets"], ensure_ascii=False, indent=2),
            "```",
            "",
            "## 6. ARM Readiness (미실행)",
            "```json",
            json.dumps(
                payload["arm_readiness"], ensure_ascii=False, indent=2
            ),
            "```",
            "",
            "## 7. DRY RUN Commands (PowerShell)",
        ]
        for cmd in payload["dry_run_commands"]:
            lines.append(f"### {cmd.get('market')} / {cmd.get('candidate')}")
            lines.append("```powershell")
            lines.append(cmd["powershell"])
            lines.append("```")
            lines.append("")

        lines.extend(
            [
                "## 8. DRY RUN Results",
                "```json",
                json.dumps(
                    payload.get("dry_run_results") or [],
                    ensure_ascii=False,
                    indent=2,
                ),
                "```",
                "",
                "## 9. Blockers / Warnings",
                "```json",
                json.dumps(
                    {
                        "blockers": payload["blockers"],
                        "warnings": payload["warnings"],
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                "```",
                "",
                "## 10. Live Command Template (실행 금지)",
                "```json",
                json.dumps(
                    payload.get("live_command_template"),
                    ensure_ascii=False,
                    indent=2,
                ),
                "```",
                "",
                "## 11. Post-execution Checks",
                "```json",
                json.dumps(
                    payload["post_execution_checks"],
                    ensure_ascii=False,
                    indent=2,
                ),
                "```",
                "",
                "## 12. Emergency Procedures",
                "```json",
                json.dumps(
                    payload["emergency_procedures"],
                    ensure_ascii=False,
                    indent=2,
                ),
                "```",
                "",
                "## 13. UBA Detail (운영자 선택용 — 시크릿 없음)",
                "```json",
                json.dumps(
                    payload.get("uba_candidates_detail") or [],
                    ensure_ascii=False,
                    indent=2,
                ),
                "```",
                "",
                "## Notes",
            ]
        )
        for n in payload.get("notes") or []:
            lines.append(f"- {n}")
        lines.append("")
        path.write_text("\n".join(lines), encoding="utf-8")
        return path
