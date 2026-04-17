"""
LLM Research Agent — uses local Ollama (no API keys, no cloud rate limits).

  1. gemma3:4b (or OLLAMA_CHAT_MODEL) — summary from headlines + price
  2. nomic-embed-text (or OLLAMA_EMBED_MODEL) — 768-dim vectors for pgvector

Requires: `ollama serve` running, models pulled (see Makefile ollama-pull).
"""

import logging
import os

from dotenv import load_dotenv
load_dotenv(override=True)

import httpx
from confluent_kafka import Consumer

from app.db import models  # noqa: F401
from app.db.session import SessionLocal, engine, Base
from app.schemas.correlation import CorrelationEvent
from sqlalchemy import desc, text

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

OLLAMA_BASE = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434").rstrip("/")
PRICE_DELTA_MIN = float(os.getenv("REPORT_MIN_PRICE_DELTA", "0.10"))
PCT_DELTA_MIN = float(os.getenv("REPORT_MIN_PCT_DELTA", "0.15"))


def create_consumer() -> Consumer:
    bootstrap = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
    return Consumer({
        "bootstrap.servers": bootstrap,
        "group.id": "research-agent-ollama",
        "auto.offset.reset": "latest",
        "enable.auto.commit": True,
    })


def init_db():
    with engine.connect() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        conn.commit()
    from app.db.init_db import _drop_correlation_reports_if_wrong_embedding_dim
    _drop_correlation_reports_if_wrong_embedding_dim()
    Base.metadata.create_all(bind=engine)


def ollama_chat(client: httpx.Client, model: str, system: str, user: str) -> str:
    url = f"{OLLAMA_BASE}/api/chat"
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "stream": False,
        "options": {"temperature": 0.3},
    }
    resp = client.post(url, json=payload, timeout=120.0)
    resp.raise_for_status()
    data = resp.json()
    return data["message"]["content"].strip()


def ollama_embed(client: httpx.Client, model: str, prompt: str) -> list[float]:
    url = f"{OLLAMA_BASE}/api/embeddings"
    payload = {"model": model, "prompt": prompt}
    resp = client.post(url, json=payload, timeout=120.0)
    resp.raise_for_status()
    data = resp.json()
    return data["embedding"]


def generate_summary(client: httpx.Client, chat_model: str, event: CorrelationEvent) -> str:
    direction = "rose" if event.price_change_pct >= 0 else "fell"
    headlines_text = "\n".join(f"- {h}" for h in event.headlines)

    user_prompt = f"""Stock: ${event.ticker}
Price: ${event.price:.2f} ({direction} {abs(event.price_change_pct):.2f}% from previous close)
Number of recent news articles: {event.news_count}

Recent headlines:
{headlines_text}

Explain what happened and why the stock moved."""

    return ollama_chat(client, chat_model, SYSTEM_PROMPT, user_prompt)


def generate_embedding(client: httpx.Client, embed_model: str, summary: str) -> list[float]:
    return ollama_embed(client, embed_model, summary)


def should_store_report(event: CorrelationEvent, summary: str) -> bool:
    """Store only materially updated insights to avoid repeated UI noise."""
    session = SessionLocal()
    try:
        previous = (
            session.query(models.CorrelationReport)
            .filter(models.CorrelationReport.ticker == event.ticker)
            .order_by(desc(models.CorrelationReport.detected_at), desc(models.CorrelationReport.id))
            .first()
        )
        if previous is None:
            return True

        summary_changed = (previous.summary or "").strip() != (summary or "").strip()
        headlines_changed = list(previous.headlines or []) != list(event.headlines or [])
        news_count_changed = previous.news_count != event.news_count
        price_moved = abs((previous.price or 0) - event.price) >= PRICE_DELTA_MIN
        pct_moved = abs((previous.price_change_pct or 0) - event.price_change_pct) >= PCT_DELTA_MIN

        return any([
            summary_changed,
            headlines_changed,
            news_count_changed,
            price_moved,
            pct_moved,
        ])
    finally:
        session.close()


def store_report(event: CorrelationEvent, summary: str, embedding: list[float]):
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

    chat_model = os.getenv("OLLAMA_CHAT_MODEL", "gemma3:4b")
    embed_model = os.getenv("OLLAMA_EMBED_MODEL", "nomic-embed-text")

    http_client = httpx.Client(timeout=120.0)

    init_db()
    logger.info(
        "Research agent (Ollama) — chat=%s embed=%s — topic '%s'",
        chat_model, embed_model, topic,
    )
    logger.info("Waiting for NEW correlation events (offset=latest)…")

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

                summary = generate_summary(http_client, chat_model, event)
                logger.info("Summary: %s", summary)

                if not should_store_report(event, summary):
                    logger.info("No material update for $%s, skipping duplicate report", event.ticker)
                    continue

                embedding = generate_embedding(http_client, embed_model, summary)
                logger.info("Embedding generated (%d dimensions)", len(embedding))

                store_report(event, summary, embedding)

            except Exception as e:
                logger.error("Failed to process event: %s", e)

    except KeyboardInterrupt:
        logger.info("Shutting down…")
    finally:
        http_client.close()
        consumer.close()


if __name__ == "__main__":
    run()
