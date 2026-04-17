from fastapi import FastAPI, HTTPException, Response
from pydantic import BaseModel

from app.watchlist import (
    add_user_ticker,
    get_watchlist_details,
    normalize_ticker,
    remove_user_ticker,
)


app = FastAPI(
    title="MarketPulse API",
    description="Real-Time Reddit x Stock Correlation Engine",
    version="0.1.0",
)


class WatchlistRequest(BaseModel):
    ticker: str


@app.get("/health", tags=["system"])
def health_check() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/", tags=["system"])
def root() -> dict[str, str]:
    return {"message": "MarketPulse API is running"}


@app.get("/watchlist", tags=["watchlist"])
def get_watchlist() -> dict[str, object]:
    return get_watchlist_details()


@app.head("/watchlist", tags=["watchlist"], include_in_schema=False)
def head_watchlist() -> Response:
    return Response(status_code=200)


@app.post("/watchlist", tags=["watchlist"])
def add_watchlist_ticker(payload: WatchlistRequest) -> dict[str, object]:
    try:
        symbol = normalize_ticker(payload.ticker)
        user_tickers = add_user_ticker(symbol)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    details = get_watchlist_details()
    details["user_tickers"] = user_tickers
    return details


@app.delete("/watchlist/{ticker}", tags=["watchlist"])
def remove_watchlist_ticker(ticker: str) -> dict[str, object]:
    try:
        user_tickers = remove_user_ticker(ticker)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    details = get_watchlist_details()
    details["user_tickers"] = user_tickers
    return details
