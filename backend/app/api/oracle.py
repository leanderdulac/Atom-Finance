"""Oracle API: arbitrated spot, provider heartbeat, US option chains."""
from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.core.limiter import limiter
from app.core.security import get_current_user
from app.services import oracle
from app.services.market_sources import SourceError

router = APIRouter()


@router.get("/spot")
@limiter.limit("30/minute")
async def spot(
    request: Request,
    ticker: str = Query(..., min_length=1, max_length=25),
    owner: str = Depends(get_current_user),
):
    try:
        return await oracle.spot(ticker, owner)
    except SourceError as exc:
        raise HTTPException(exc.status, exc.message) from exc


@router.get("/heartbeat")
@limiter.limit("30/minute")
async def heartbeat(request: Request, _owner: str = Depends(get_current_user)):
    return oracle.heartbeat()


@router.get("/chain")
@limiter.limit("10/minute")
async def chain(
    request: Request,
    ticker: str = Query(..., min_length=1, max_length=25),
    expiries: str = Query("", max_length=200),
    _owner: str = Depends(get_current_user),
):
    wanted = [e.strip() for e in expiries.split(",") if e.strip()] or None
    try:
        return await oracle.chain_us(ticker, wanted)
    except SourceError as exc:
        raise HTTPException(exc.status, exc.message) from exc
