"""REAL runtime ↔ hot-reload isolation (History #92)."""

from __future__ import annotations

import pytest

from stock_platform.broker.open_order_gate_classification import (
    OPEN_CLASS_AUTO_ENTRY_BUY,
    OPEN_CLASS_AUTO_EXIT_SELL,
)
from stock_platform.operation.runtime_process_stability import (
    CODE_REAL_RUNTIME_REQUIRES_STABLE_PROCESS,
    MSG_REAL_RUNTIME_REQUIRES_STABLE_PROCESS_KO,
    RealRuntimeUnstableError,
    assert_stable_runtime_for_real_trading,
    build_runtime_stability_snapshot,
    classify_startup_fail_closed_cause,
    is_hot_reload_enabled,
    is_stable_runtime,
    real_runtime_unstable_health_reason,
    resolve_runtime_mode,
)


@pytest.mark.unit
def test_production_mode_reload_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_RUNTIME_MODE", "production")
    monkeypatch.setenv("HOT_RELOAD_ENABLED", "false")
    monkeypatch.delenv("STOCK_PLATFORM_LAUNCH_MODE", raising=False)
    assert resolve_runtime_mode() == "production"
    assert is_hot_reload_enabled() is False
    assert is_stable_runtime() is True
    assert_stable_runtime_for_real_trading(context="TEST")


@pytest.mark.unit
def test_development_reload_blocks_real_activation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_RUNTIME_MODE", "development")
    monkeypatch.setenv("HOT_RELOAD_ENABLED", "true")
    # testing runtime bypass를 잠깐 끄기 위해 환경 플래그 사용은 불가 —
    # assert는 is_testing_runtime() 에서 bypass 되므로 직접 raise 경로 검증
    monkeypatch.setattr(
        "stock_platform.operation.runtime_process_stability.is_testing_runtime",
        lambda: False,
    )
    assert is_stable_runtime() is False
    with pytest.raises(RealRuntimeUnstableError) as exc:
        assert_stable_runtime_for_real_trading(context="LIVE_ENABLE")
    assert exc.value.code == CODE_REAL_RUNTIME_REQUIRES_STABLE_PROCESS
    assert "실거래 자동매매는 개발 자동 재시작 모드" in exc.value.message


@pytest.mark.unit
def test_development_paper_path_stable_check_not_required_for_mode_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """development 자체는 허용 — REAL activation 호출 시에만 차단."""

    monkeypatch.setenv("APP_RUNTIME_MODE", "development")
    monkeypatch.setenv("HOT_RELOAD_ENABLED", "true")
    assert resolve_runtime_mode() == "development"
    assert is_hot_reload_enabled() is True
    # PAPER 개발은 모드 존재만으로 충분
    snap = build_runtime_stability_snapshot()
    assert snap["RUNTIME_MODE"] == "development"
    assert snap["HOT_RELOAD_ENABLED"] is True
    assert snap["REAL_RUNTIME_STABLE"] is False


@pytest.mark.unit
def test_production_stable_activation_allowed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("STOCK_PLATFORM_LAUNCH_MODE", "PROD")
    monkeypatch.delenv("APP_RUNTIME_MODE", raising=False)
    monkeypatch.setenv("HOT_RELOAD_ENABLED", "false")
    monkeypatch.setattr(
        "stock_platform.operation.runtime_process_stability.is_testing_runtime",
        lambda: False,
    )
    assert resolve_runtime_mode() == "production"
    assert_stable_runtime_for_real_trading(context="ARM_ENABLE")


@pytest.mark.unit
def test_frontend_excluded_from_reload_watch_hint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_RUNTIME_MODE", "development")
    monkeypatch.setenv("HOT_RELOAD_ENABLED", "true")
    snap = build_runtime_stability_snapshot()
    assert "src only" in str(snap["reload_watch_hint"])
    assert "frontend" in str(snap["reload_watch_hint"]).lower()


@pytest.mark.unit
def test_observability_fields_present(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("APP_RUNTIME_MODE", "production")
    monkeypatch.setenv("HOT_RELOAD_ENABLED", "false")
    snap = build_runtime_stability_snapshot()
    for key in (
        "RUNTIME_MODE",
        "HOT_RELOAD_ENABLED",
        "STABLE_RUNTIME_REQUIRED",
        "REAL_RUNTIME_STABLE",
        "pid",
    ):
        assert key in snap


@pytest.mark.unit
def test_health_reason_when_real_on_dev_reload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_RUNTIME_MODE", "development")
    monkeypatch.setenv("HOT_RELOAD_ENABLED", "true")
    monkeypatch.setattr(
        "stock_platform.operation.runtime_process_stability.is_testing_runtime",
        lambda: False,
    )
    assert (
        real_runtime_unstable_health_reason(
            live_on=True, arm_on=True, lease_active=True
        )
        == "REAL_RUNTIME_UNSTABLE_DEV_RELOAD"
    )
    assert (
        real_runtime_unstable_health_reason(
            live_on=False, arm_on=False, lease_active=False
        )
        is None
    )


@pytest.mark.unit
def test_startup_fail_closed_cause_dev_hot_reload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("HOT_RELOAD_ENABLED", "true")
    monkeypatch.setenv("APP_RUNTIME_MODE", "development")
    assert classify_startup_fail_closed_cause() == "DEV_HOT_RELOAD"


@pytest.mark.unit
def test_restore_db_open_strict_semantics_unchanged() -> None:
    """gate_mode=restore 는 AUTO_ENTRY/EXIT 모두 blocking (hardening renew와 분리)."""

    # 단위: OpenOrderGateSummary.blocking 정책 상수 경로만 확인
    # (DB session 없이 mode 분기 문서화 테스트)
    from stock_platform.broker import open_order_gate_classification as mod

    assert hasattr(mod, "evaluate_open_order_gate_for_uba")
    assert OPEN_CLASS_AUTO_ENTRY_BUY == "AUTO_ENTRY_BUY_OPEN"
    assert OPEN_CLASS_AUTO_EXIT_SELL == "AUTO_EXIT_SELL_OPEN"


@pytest.mark.unit
def test_arm_renew_hardening_exclude_flags_still_present() -> None:
    """ARM renew 시 entry/exit exclude 필드가 모듈에 유지됨."""

    from stock_platform.broker.open_order_gate_classification import (
        OpenOrderGateSummary,
    )

    fields = getattr(OpenOrderGateSummary, "__dataclass_fields__", {})
    assert "auto_entry_buy_excluded" in fields
    assert "auto_protective_excluded" in fields


@pytest.mark.unit
def test_korean_guard_message_constant() -> None:
    assert "실거래 자동매매는 개발 자동 재시작 모드" in (
        MSG_REAL_RUNTIME_REQUIRES_STABLE_PROCESS_KO
    )
