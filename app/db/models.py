"""SQLAlchemy models for storing correlation reports and their embeddings."""

from datetime import datetime, timezone

from pgvector.sqlalchemy import Vector
from sqlalchemy import Column, DateTime, Float, Integer, String, Text
from sqlalchemy.dialects.postgresql import ARRAY

from app.db.session import Base


class CorrelationReport(Base):
    """A processed correlation event with LLM-generated summary and embedding."""

    __tablename__ = "correlation_reports"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ticker = Column(String(10), nullable=False, index=True)
    price = Column(Float, nullable=False)
    price_change_pct = Column(Float, nullable=False)
    news_count = Column(Integer, nullable=False)
    headlines = Column(ARRAY(String), default=[])
    summary = Column(Text, nullable=False)
    embedding = Column(Vector(1536))
    detected_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
