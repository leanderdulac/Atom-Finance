
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from app.core.security import get_current_user
from app.services.binance_service import BinanceService

router = APIRouter(dependencies=[Depends(get_current_user)])

class KellyCryptoRequest(BaseModel):
    symbol: str = Field(..., description="Binance symbol, e.g. BTCUSDT")
    win_prob: float = Field(..., gt=0, lt=1)
    payout_ratio: float = Field(..., gt=0)
    bankroll_override: float | None = Field(None, description="Manual bankroll. If None, tries to fetch from Binance USDT balance.")
    fraction: float = Field(0.25, gt=0, le=1)

class LeverageRequest(BaseModel):
    symbol: str = Field(..., description="Symbol for the futures contract")
    leverage: int = Field(..., ge=1, le=125)

@router.get("/price/{symbol}")
async def get_price(symbol: str):
    price = await BinanceService.get_ticker_price(symbol)
    if not price:
        raise HTTPException(status_code=404, detail=f"Symbol {symbol} not found on Binance")
    return price

@router.get("/tickers")
async def get_all_tickers():
    tickers = await BinanceService.get_all_tickers()
    if not tickers:
        raise HTTPException(status_code=400, detail="Could not fetch all tickers")
    return tickers

@router.get("/depth/{symbol}")
async def get_depth(symbol: str, limit: int = Query(100, ge=1, le=5000)):
    depth = await BinanceService.get_order_book(symbol, limit)
    if not depth:
        raise HTTPException(status_code=404, detail=f"Depth not found for {symbol}")
    return depth

@router.get("/account")
async def get_account():
    raise HTTPException(410, "ATOM Research não acessa contas nem altera posições na corretora.")

@router.get("/futures/price/{symbol}")
async def get_futures_price(symbol: str):
    price = await BinanceService.get_futures_ticker(symbol)
    if not price:
        raise HTTPException(status_code=404, detail=f"Futures contract {symbol} not found")
    return price

@router.get("/futures/account")
async def get_futures_account():
    raise HTTPException(410, "ATOM Research não acessa contas nem altera posições na corretora.")

@router.post("/futures/leverage")
async def set_leverage(req: LeverageRequest):
    raise HTTPException(410, "ATOM Research não acessa contas nem altera posições na corretora.")

@router.post("/kelly-sizing")
async def get_kelly_sizing(req: KellyCryptoRequest):
    if req.bankroll_override is None or req.bankroll_override <= 0:
        raise HTTPException(422, "Informe um capital positivo para a simulação; a conta da corretora não será consultada.")
    result = await BinanceService.calculate_kelly_sizing(
        req.symbol, req.win_prob, req.payout_ratio, req.bankroll_override, req.fraction
    )
    if "error" in result or "erro" in result:
        raise HTTPException(status_code=400, detail=result.get("error") or result.get("erro"))
    return result

@router.get("/klines/{symbol}")
async def get_klines(
    symbol: str, 
    interval: str = Query("1d", description="1m, 5m, 1h, 1d, etc."), 
    limit: int = Query(100, ge=1, le=1000)
):
    data = await BinanceService.get_klines(symbol, interval, limit)
    if not data:
        raise HTTPException(status_code=404, detail="Could not fetch candle data")
    return data
