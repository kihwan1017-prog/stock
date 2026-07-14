from __future__ import annotations
from collections import defaultdict
from datetime import date
from decimal import Decimal
from sqlalchemy.orm import Session
from stock_platform.backtest.portfolio_models import PortfolioBacktestAsset, PortfolioBacktestAssetResult, PortfolioBacktestResult, PortfolioBacktestSummary
from stock_platform.backtest.service import BacktestService

ZERO=Decimal('0'); ONE=Decimal('1')

class PortfolioBacktestService:
    def __init__(self, session: Session) -> None:
        self._backtest_service=BacktestService(session)

    def run(self, *, assets:list[PortfolioBacktestAsset], start_date:date, end_date:date,
            initial_capital:Decimal, short_window:int, long_window:int,
            stop_loss_ratio:Decimal, take_profit_ratio:Decimal,
            fee_ratio:Decimal, sell_tax_ratio:Decimal, slippage_ratio:Decimal) -> PortfolioBacktestResult:
        self._validate(assets=assets,start_date=start_date,end_date=end_date,initial_capital=initial_capital,short_window=short_window,long_window=long_window)
        asset_results=[]; failures=[]; curves=[]; invested=ZERO; final_equity=ZERO
        for asset in assets:
            allocated=(initial_capital*asset.weight).quantize(Decimal('0.01')); invested+=allocated
            try:
                result=self._backtest_service.run_moving_average_backtest(
                    exchange_code=asset.exchange_code,symbol=asset.symbol,start_date=start_date,end_date=end_date,
                    initial_capital=allocated,short_window=short_window,long_window=long_window,
                    stop_loss_ratio=stop_loss_ratio,take_profit_ratio=take_profit_ratio,position_ratio=ONE,
                    fee_ratio=fee_ratio,sell_tax_ratio=(ZERO if asset.exchange_code.upper()=='UPBIT' else sell_tax_ratio),
                    slippage_ratio=slippage_ratio)
            except Exception as exc:
                failures.append({'exchange_code':asset.exchange_code.upper(),'symbol':asset.symbol.upper(),'weight':str(asset.weight),'error':str(exc)})
                final_equity+=allocated; continue
            s=result.summary; final_equity+=s.final_equity
            asset_results.append(PortfolioBacktestAssetResult(asset.exchange_code.upper(),asset.symbol.upper(),asset.weight,allocated,s.final_equity,s.total_profit_loss,s.total_return_rate,s.maximum_drawdown_rate,s.trade_count,s.win_rate))
            curves.append(result.equity_curve)
        unallocated=(initial_capital-invested).quantize(Decimal('0.01')); final_equity=(final_equity+unallocated).quantize(Decimal('0.01'))
        curve=self._merge_equity_curves(curves=curves,unallocated_capital=unallocated)
        total_pnl=(final_equity-initial_capital).quantize(Decimal('0.01'))
        total_return=(total_pnl/initial_capital*Decimal('100')).quantize(Decimal('0.0001'))
        profitable=sum(1 for x in asset_results if x.total_profit_loss>ZERO)
        losing=sum(1 for x in asset_results if x.total_profit_loss<=ZERO)
        return PortfolioBacktestResult(start_date,end_date,PortfolioBacktestSummary(initial_capital,invested,unallocated,final_equity,total_pnl,total_return,self._calculate_maximum_drawdown(curve),profitable,losing,len(assets)),asset_results,curve,failures)

    @staticmethod
    def _merge_equity_curves(*, curves:list[list[tuple[date,Decimal]]], unallocated_capital:Decimal)->list[tuple[date,Decimal]]:
        values=defaultdict(lambda:unallocated_capital)
        for curve in curves:
            for d,v in curve: values[d]+=v
        return [(d,values[d].quantize(Decimal('0.01'))) for d in sorted(values)]

    @staticmethod
    def _calculate_maximum_drawdown(curve:list[tuple[date,Decimal]])->Decimal:
        if not curve:return ZERO
        peak=curve[0][1]; mdd=ZERO
        for _,equity in curve:
            peak=max(peak,equity)
            if peak>ZERO:mdd=max(mdd,(peak-equity)/peak*Decimal('100'))
        return mdd.quantize(Decimal('0.0001'))

    @staticmethod
    def _validate(*,assets,start_date,end_date,initial_capital,short_window,long_window)->None:
        if not assets: raise ValueError('assets must not be empty')
        if len(assets)>50: raise ValueError('asset count must not exceed 50')
        if start_date>end_date: raise ValueError('start_date must not be after end_date')
        if initial_capital<=ZERO: raise ValueError('initial_capital must be greater than zero')
        if short_window>=long_window: raise ValueError('short_window must be smaller than long_window')
        total=ZERO; seen=set()
        for a in assets:
            if a.weight<=ZERO: raise ValueError('asset weight must be greater than zero')
            key=(a.exchange_code.upper(),a.symbol.upper())
            if key in seen: raise ValueError(f'duplicate asset: {key[0]}/{key[1]}')
            seen.add(key); total+=a.weight
        if total>ONE: raise ValueError('total asset weight must not exceed 1')
