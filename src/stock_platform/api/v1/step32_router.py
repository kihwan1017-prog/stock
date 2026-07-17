from decimal import Decimal
from fastapi import APIRouter
from pydantic import BaseModel, Field
from stock_platform.position.models import Side
from stock_platform.position.repository import InMemoryPositionRepository
from stock_platform.position.service import PositionService
from stock_platform.portfolio.service import PortfolioService
from stock_platform.risk.models import RiskLimits, RiskRequest
from stock_platform.risk.service import RiskService
router=APIRouter(prefix="/api/v1",tags=["step32"])
repo=InMemoryPositionRepository(); positions=PositionService(repo); portfolio=PortfolioService(repo)
risk=RiskService(RiskLimits(Decimal("1000000"),Decimal("5000000"),Decimal("300000"),5))
class ExecutionRequest(BaseModel):
    account_id:str; market:str="KRX"; symbol:str; side:Side
    quantity:Decimal=Field(gt=0); price:Decimal=Field(gt=0); execution_id:str
class RiskCheckRequest(BaseModel):
    order_amount:Decimal; current_position_amount:Decimal; daily_realized_pnl:Decimal
    open_positions:int; creates_new_position:bool
@router.post("/positions/executions")
def apply_execution(request:ExecutionRequest): return positions.apply_execution(**request.model_dump())
@router.get("/positions")
def list_positions(account_id:str|None=None): return repo.list(account_id)
@router.get("/portfolio/summary")
def portfolio_summary(account_id:str): return portfolio.summarize(account_id)
@router.post("/risk/check")
def risk_check(request:RiskCheckRequest): return risk.evaluate(RiskRequest(**request.model_dump()))
@router.get("/dashboard/summary")
def dashboard_summary(account_id:str): return {"portfolio":portfolio.summarize(account_id),"positions":repo.list(account_id),"risk":{"kill_switch_enabled":risk.kill_switch_enabled}}
