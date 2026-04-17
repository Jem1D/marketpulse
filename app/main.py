from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import desc

from app.db import models
from app.db.session import SessionLocal

from app.watchlist import (
    add_user_ticker,
    get_effective_tickers,
    get_watchlist_details,
    normalize_ticker,
    remove_user_ticker,
)


app = FastAPI(
    title="MarketPulse API",
    description="Real-Time Reddit x Stock Correlation Engine",
    version="0.1.0",
)

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class WatchlistRequest(BaseModel):
    ticker: str


@app.get("/health", tags=["system"])
def health_check() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/", tags=["system"])
def root() -> dict[str, str]:
    return {"message": "MarketPulse API is running"}


@app.get("/ui", tags=["ui"], include_in_schema=False)
def dashboard() -> FileResponse:
    return FileResponse(STATIC_DIR / "dashboard.html")


@app.get("/reports", tags=["reports"])
def get_reports(
    limit: int = Query(default=50, ge=1, le=200),
    ticker: str | None = Query(default=None),
    latest_only: bool = Query(default=True),
) -> dict[str, object]:
    session = SessionLocal()
    try:
        query = session.query(models.CorrelationReport)
        active_tickers = set(get_effective_tickers())

        if ticker:
            query = query.filter(models.CorrelationReport.ticker == ticker.upper())
        else:
            query = query.filter(models.CorrelationReport.ticker.in_(active_tickers))

        rows = (
            query.order_by(desc(models.CorrelationReport.detected_at), desc(models.CorrelationReport.id))
            .limit(limit if not latest_only else 2000)
            .all()
        )

        if latest_only:
            deduped_rows = []
            seen_tickers: set[str] = set()
            for row in rows:
                if row.ticker in seen_tickers:
                    continue
                seen_tickers.add(row.ticker)
                deduped_rows.append(row)
                if len(deduped_rows) >= limit:
                    break
            rows = deduped_rows

        reports = [
            {
                "id": r.id,
                "ticker": r.ticker,
                "price": r.price,
                "price_change_pct": r.price_change_pct,
                "news_count": r.news_count,
                "headlines": r.headlines,
                "summary": r.summary,
                "detected_at": r.detected_at.isoformat() if r.detected_at else None,
                "created_at": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]

        return {
            "count": len(reports),
            "reports": reports,
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to load reports: {e}") from e
    finally:
        session.close()


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
