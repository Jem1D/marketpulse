"""Schema for Reddit post events flowing through Kafka."""

from datetime import datetime, timezone

from pydantic import BaseModel, Field


class RedditPostEvent(BaseModel):
    """A single Reddit post/comment mentioning a stock ticker."""

    event_id: str = Field(description="Unique ID: {subreddit}:{post_id}")
    ticker: str = Field(description="Detected ticker symbol, e.g. AAPL")
    title: str
    body: str = ""
    subreddit: str
    author: str
    url: str
    score: int = 0
    created_utc: datetime
    ingested_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def to_kafka_key(self) -> str:
        """Partition by ticker so all AAPL events hit the same partition."""
        return self.ticker
