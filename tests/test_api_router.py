from stock_platform.api.main import app
from stock_platform.api.router import collect_duplicate_operation_ids


def test_api_router_has_no_duplicate_operation_ids() -> None:
    duplicates = collect_duplicate_operation_ids(app.router)

    assert duplicates == []
