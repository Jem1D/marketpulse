"""Schema for financial news events flowing through Kafka."""

from datetime import datetime, timezone

from pydantic import BaseModel, Field


class NewsEvent(BaseModel):
    """A financial news headline related to a stock ticker."""

    article_id: str = Field(description="Unique article identifier from source")
    ticker: str = Field(description="Stock symbol this article relates to")
    title: str
    summary: str = ""
    publisher: str = ""
    url: str = ""
    published_at: datetime
    ingested_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

    def to_kafka_key(self) -> str:
        return self.ticker
