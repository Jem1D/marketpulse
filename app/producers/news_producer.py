"""
News Producer — polls Yahoo Finance for recent news headlines per ticker
and publishes events to Kafka topic `news-headlines`.

No API keys required. yfinance exposes a .news property for every ticker
that returns the latest ~10 articles from Yahoo Finance's news feed.

Why news instead of Reddit:
  Reddit mentions are noisy — memes, old discussions, random opinions.
  Financial news headlines (earnings, FDA rulings, analyst upgrades)
  are the actual catalysts behind most big stock moves. Correlating
  news with price changes produces much more meaningful signals.

Key concepts:
  - Each poll cycle iterates over the watchlist and fetches news per ticker.
  - We deduplicate by article_id so we never publish the same headline twice.
  - Events are keyed by ticker for partition alignment with stock-ticks.
"""

import logging
import os
import time
from datetime import datetime, timezone

from dotenv import load_dotenv
load_dotenv()

import yfinance as yf
from confluent_kafka import Producer

from app.schemas.news import NewsEvent
from app.watchlist import get_effective_tickers

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger("news_producer")

POLL_INTERVAL = int(os.getenv("NEWS_POLL_INTERVAL", "60"))


def delivery_callback(err, msg):
    if err:
        logger.error("Delivery failed for %s: %s", msg.key(), err)
    else:
        logger.debug(
            "Delivered to %s [partition %d] @ offset %d",
            msg.topic(), msg.partition(), msg.offset(),
        )


def create_producer() -> Producer:
    bootstrap = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
    return Producer({
        "bootstrap.servers": bootstrap,
        "acks": "all",
        "retries": 5,
        "retry.backoff.ms": 500,
        "linger.ms": 50,
    })


def fetch_news(symbol: str) -> list[NewsEvent]:
    """Fetch recent news articles for a single ticker."""
    try:
        ticker = yf.Ticker(symbol)
        raw_news = ticker.news or []
    except Exception as e:
        logger.warning("Failed to fetch news for %s: %s", symbol, e)
        return []

    events = []
    for article in raw_news:
        content = article.get("content", {})

        title = content.get("title", "")
        if not title:
            continue

        pub_date_str = content.get("pubDate")
        if pub_date_str:
            try:
                published_at = datetime.fromisoformat(pub_date_str.replace("Z", "+00:00"))
            except ValueError:
                published_at = datetime.now(timezone.utc)
        else:
            published_at = datetime.now(timezone.utc)

        url_info = content.get("canonicalUrl", {}) or content.get("clickThroughUrl", {})

        event = NewsEvent(
            article_id=content.get("id", article.get("id", "")),
            ticker=symbol,
            title=title,
            summary=content.get("summary", ""),
            publisher=content.get("provider", {}).get("displayName", ""),
            url=url_info.get("url", ""),
            published_at=published_at,
        )
        events.append(event)

    return events


def run():
    topic = os.getenv("KAFKA_TOPIC_NEWS_HEADLINES", "news-headlines")
    producer = create_producer()

    seen_ids: set[str] = set()
    MAX_SEEN = 10_000

    logger.info("Polling news every %ds → Kafka topic '%s'", POLL_INTERVAL, topic)

    try:
        while True:
            total_new = 0
            processed: set[str] = set()

            while True:
                tickers = get_effective_tickers()
                pending = [symbol for symbol in tickers if symbol not in processed]
                if not pending:
                    break

                logger.info("News cycle watchlist size: %d", len(tickers))

                for symbol in pending:
                    articles = fetch_news(symbol)

                    for event in articles:
                        if event.article_id in seen_ids:
                            continue

                        producer.produce(
                            topic=topic,
                            key=event.to_kafka_key(),
                            value=event.model_dump_json(),
                            callback=delivery_callback,
                        )
                        logger.info(
                            "→ %s | %s | %s",
                            event.ticker, event.publisher, event.title[:90],
                        )
                        seen_ids.add(event.article_id)
                        total_new += 1

                    processed.add(symbol)

                    producer.poll(0)
                    time.sleep(0.5)

            if len(seen_ids) > MAX_SEEN:
                seen_ids.clear()

            logger.info("— news cycle complete (%d new articles), sleeping %ds —", total_new, POLL_INTERVAL)
            time.sleep(POLL_INTERVAL)

    except KeyboardInterrupt:
        logger.info("Shutting down…")
    finally:
        remaining = producer.flush(timeout=10)
        if remaining:
            logger.warning("%d messages were not delivered", remaining)


if __name__ == "__main__":
    run()
