from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import ORJSONResponse

from stock_platform.api.router import api_router
from stock_platform.common.logger import configure_logging, logger
from stock_platform.realtime.manager import realtime_manager
from stock_platform.realtime.runtime import (realtime_execution_runner,realtime_strategy_runner,)
from stock_platform.realtime.session_runtime import (realtime_trading_scheduler,)
from stock_platform.broker.kiwoom.ws_manager import (kiwoom_order_websocket_manager,)
from stock_platform.broker.recovery_runtime import (broker_recovery_manager,)
from stock_platform.risk_engine.daily_loss_scheduler import (daily_loss_monitor_scheduler,)

@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    logger.info("Stock Platform starting...")

    # 서버 시작 시 복구
    try:
        await broker_recovery_manager.recover()
    except Exception:
        logger.exception(
            "Broker recovery failed during startup"
        )
    
    # 2. 스케줄러 시작
    daily_loss_monitor_scheduler.start()

    yield

    # 서버 종료
    logger.info("Stopping realtime services...")
    await daily_loss_monitor_scheduler.shutdown()
    await kiwoom_order_websocket_manager.stop()
    await realtime_trading_scheduler.shutdown()
    await realtime_execution_runner.stop()
    await realtime_strategy_runner.stop()
    await realtime_manager.stop_all()
    
    logger.info("Stock Platform stopped.")


app = FastAPI(
    title="Stock Platform API",
    description="AI 기반 주식·암호화폐 자동매매 플랫폼",
    version="0.1.0",
    default_response_class=ORJSONResponse,
    lifespan=lifespan,
)


@app.get("/")
def root():
    return {
        "service": "stock-platform",
        "status": "running",
    }


app.include_router(api_router)