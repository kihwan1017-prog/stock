from stock_platform.broker.kiwoom.execution_ws_client import (
    KiwoomExecutionWebSocketClient,
)


def test_login_message():
    assert (
        KiwoomExecutionWebSocketClient
        ._login_message("TOKEN")
    ) == {
        "trnm": "LOGIN",
        "token": "TOKEN",
    }


def test_ping_detection():
    assert (
        KiwoomExecutionWebSocketClient
        ._is_ping({"trnm": "PING"})
        is True
    )
