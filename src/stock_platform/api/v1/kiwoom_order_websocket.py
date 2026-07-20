from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    status,
)

from stock_platform.api.deps_admin import require_admin
from stock_platform.broker.kiwoom.ws_manager import (
    kiwoom_order_websocket_manager,
)


router = APIRouter(
    prefix="/api/v1/broker/kiwoom/order-websocket",
    tags=["Kiwoom Order WebSocket"],
    dependencies=[Depends(require_admin)],
)


@router.post("/start")
async def start_kiwoom_order_websocket():
    try:
        return await (
            kiwoom_order_websocket_manager.start()
        )
    except (
        ValueError,
        RuntimeError,
    ) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.post("/stop")
async def stop_kiwoom_order_websocket():
    await kiwoom_order_websocket_manager.stop()
    return {"stopped": True}


@router.get("/status")
def get_kiwoom_order_websocket_status():
    return kiwoom_order_websocket_manager.status()


@router.get("/history")
def get_kiwoom_order_websocket_history():
    return kiwoom_order_websocket_manager.history()
