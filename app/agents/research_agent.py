"""
LLM Research Agent — the final brain of MarketPulse.

Consumes correlation events from Kafka, then:
  1. Builds a context prompt from the ticker, price move, and headlines.
  2. Calls Gemini via its REST API to generate a concise, human-readable
     explanation of what happened and why.
  3. Generates an embedding of the summary for vector search.
  4. Stores everything in Postgres (correlation_reports table).

Key concepts:
  - We call Gemini's REST API directly with httpx (already installed)
    to avoid OpenAI SDK auth conflicts.
  - Embeddings are 1536-dim vectors stored in pgvector for semantic search.
"""

import logging
import os

from dotenv import load_dotenv
load_dotenv()

import httpx
from confluent_kafka import Consumer

from app.db import models  # noqa: F401
from app.db.session import SessionLocal, engine, Base
from app.schemas.correlation import CorrelationEvent
from sqlalchemy import text

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger("research_agent")

SYSTEM_PROMPT = """You are a financial research analyst. Given a stock ticker, 
its price movement, and recent news headlines, write a concise 2-3 sentence 
summary explaining what happened and why the stock moved. 

Be specific about the causal link between the news and the price move. 
Write for an informed reader — no filler, no disclaimers."""

GEMINI_API_BASE = "https://generativelanguage.googleapis.com/v1beta"


def create_consumer() -> Consumer:
    bootstrap = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
    return Consumer({
        "bootstrap.servers": bootstrap,
        "group.id": "research-agent",
        "auto.offset.reset": "earliest",
        "enable.auto.commit": True,
    })


def init_db():
    """Ensure pgvector extension and tables exist."""
    with engine.connect() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        conn.commit()
    Base.metadata.create_all(bind=engine)


def generate_summary(client: httpx.Client, api_key: str, event: CorrelationEvent) -> str:
    """Call Gemini REST API to produce a human-readable explanation."""
    direction = "rose" if event.price_change_pct >= 0 else "fell"
    headlines_text = "\n".join(f"- {h}" for h in event.headlines)

    user_prompt = f"""Stock: ${event.ticker}
Price: ${event.price:.2f} ({direction} {abs(event.price_change_pct):.2f}% from previous close)
Number of recent news articles: {event.news_count}

Recent headlines:
{headlines_text}

Explain what happened and why the stock moved."""

    model = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
    url = f"{GEMINI_API_BASE}/models/{model}:generateContent?key={api_key}"

    payload = {
        "system_instruction": {"parts": [{"text": SYSTEM_PROMPT}]},
        "contents": [{"parts": [{"text": user_prompt}]}],
        "generationConfig": {
            "temperature": 0.3,
            "maxOutputTokens": 300,
        },
    }

    resp = client.post(url, json=payload)
    resp.raise_for_status()
    data = resp.json()

    return data["candidates"][0]["content"]["parts"][0]["text"].strip()


def generate_embedding(client: httpx.Client, api_key: str, text: str) -> list[float]:
    """Create a 1536-dim embedding via Gemini's embedding API."""
    url = f"{GEMINI_API_BASE}/models/gemini-embedding-001:embedContent?key={api_key}"

    payload = {
        "content": {"parts": [{"text": text}]},
        "outputDimensionality": 1536,
    }

    resp = client.post(url, json=payload)
    resp.raise_for_status()
    data = resp.json()

    return data["embedding"]["values"]


def store_report(
    event: CorrelationEvent,
    summary: str,
    embedding: list[float],
):
    """Persist the correlation report + embedding to Postgres."""
    session = SessionLocal()
    try:
        report = models.CorrelationReport(
            ticker=event.ticker,
            price=event.price,
            price_change_pct=event.price_change_pct,
            news_count=event.news_count,
            headlines=event.headlines,
            summary=summary,
            embedding=embedding,
            detected_at=event.detected_at,
        )
        session.add(report)
        session.commit()
        logger.info("Stored report #%d for $%s", report.id, event.ticker)
    except Exception as e:
        session.rollback()
        logger.error("Failed to store report: %s", e)
    finally:
        session.close()


def run():
    topic = os.getenv("KAFKA_TOPIC_CORRELATION_EVENTS", "correlation-events")
    consumer = create_consumer()
    consumer.subscribe([topic])

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key or api_key == "replace_me":
        logger.error("GEMINI_API_KEY not set in .env — cannot start research agent")
        return

    http_client = httpx.Client(timeout=30.0)

    init_db()
    logger.info("Research agent started (Gemini) — consuming '%s'", topic)

    try:
        while True:
            msg = consumer.poll(1.0)
            if msg is None:
                continue
            if msg.error():
                logger.warning("Consumer error: %s", msg.error())
                continue

            try:
                event = CorrelationEvent.model_validate_json(msg.value())
                direction = "▲" if event.price_change_pct >= 0 else "▼"
                logger.info(
                    "Processing: $%s %s%.2f%% (%d headlines)",
                    event.ticker, direction, abs(event.price_change_pct), event.news_count,
                )

                summary = generate_summary(http_client, api_key, event)
                logger.info("Summary: %s", summary)

                embedding = generate_embedding(http_client, api_key, summary)
                logger.info("Embedding generated (%d dimensions)", len(embedding))

                store_report(event, summary, embedding)

            except Exception as e:
                logger.error("Failed to process correlation event: %s", e)

    except KeyboardInterrupt:
        logger.info("Shutting down…")
    finally:
        http_client.close()
        consumer.close()


if __name__ == "__main__":
    run()
