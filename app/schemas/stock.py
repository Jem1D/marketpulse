"""Schema for stock tick events flowing through Kafka."""

from datetime import datetime, timezone

from pydantic import BaseModel, Field


class StockTickEvent(BaseModel):
    """A single price snapshot for a stock symbol."""

    ticker: str = Field(description="Symbol, e.g. AAPL")
    price: float = Field(description="Current / latest price")
    open: float
    high: float
    low: float
    volume: int
    change_pct: float = Field(description="Percent change from previous close")
    previous_close: float
    market_time: datetime = Field(description="Timestamp of the price data")
    ingested_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def to_kafka_key(self) -> str:
        """Partition by ticker, same as Reddit events."""
        return self.ticker
