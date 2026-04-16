"""Schema for correlation events — fired when news activity aligns with a price move."""

from datetime import datetime, timezone

from pydantic import BaseModel, Field


class CorrelationEvent(BaseModel):
    """Emitted when a ticker has recent news headlines while its price moves significantly."""

    ticker: str
    news_count: int = Field(description="Number of news articles in the window")
    price: float = Field(description="Current price at detection time")
    price_change_pct: float = Field(description="Percent change from previous close")
    window_minutes: int = Field(description="Size of the rolling window")
    headlines: list[str] = Field(
        default_factory=list,
        description="Up to 5 recent headlines for context",
    )
    detected_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def to_kafka_key(self) -> str:
        return self.ticker
