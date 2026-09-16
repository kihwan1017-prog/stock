"""ops_account_classification unit tests."""

from stock_platform.trading.ops_account_classification import (
    classify_uba_ops_class,
    is_ops_visible,
    is_safe_to_soft_delete_candidate,
)


def test_protected_uba_is_real_operation() -> None:
    assert (
        classify_uba_ops_class(
            uba_id=1380,
            broker_code="UPBIT",
            account_alias="업비트계좌",
            username="kikicom",
            live_order_enabled=True,
        )
        == "REAL_OPERATION"
    )
    assert (
        classify_uba_ops_class(
            uba_id=1381,
            broker_code="KIWOOM",
            account_alias="키움계좌",
            username="kikicom",
            live_order_enabled=False,
            last_synced_at="2026-08-18",
        )
        == "REAL_OPERATION"
    )


def test_test_alias_and_legadopt_user() -> None:
    assert (
        classify_uba_ops_class(
            uba_id=1400,
            broker_code="KIWOOM",
            account_alias="test-abc",
            username="legadopt_xyz",
        )
        == "TEST"
    )


def test_ops_visible_default_hides_test() -> None:
    assert is_ops_visible("REAL_OPERATION", include_test_accounts=False)
    assert not is_ops_visible("TEST", include_test_accounts=False)
    assert not is_ops_visible("UNKNOWN", include_test_accounts=False)
    assert is_ops_visible("TEST", include_test_accounts=True)


def test_safe_soft_delete_requires_zero_refs() -> None:
    assert is_safe_to_soft_delete_candidate(
        ops_class="TEST",
        uba_id=1400,
        order_count=0,
        outbox_count=0,
        position_snap_count=0,
    )
    assert not is_safe_to_soft_delete_candidate(
        ops_class="TEST",
        uba_id=1400,
        order_count=1,
        outbox_count=0,
        position_snap_count=0,
    )
    assert not is_safe_to_soft_delete_candidate(
        ops_class="TEST",
        uba_id=1380,
        order_count=0,
        outbox_count=0,
        position_snap_count=0,
    )
