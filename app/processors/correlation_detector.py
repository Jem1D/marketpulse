"""
Correlation Detector — the brain of MarketPulse.

Consumes two Kafka topics simultaneously:
  - news-headlines (financial news events per ticker)
  - stock-ticks    (price snapshot events)

Maintains rolling time windows per ticker and fires a CorrelationEvent
when BOTH conditions are true within the same window:
  1. At least one news headline exists for the ticker
  2. Stock price has moved significantly (>= PRICE_CHANGE_THRESHOLD %)

This is a much stronger signal than Reddit mentions — news headlines
(earnings, analyst upgrades, FDA rulings) are the actual catalysts
behind most big stock moves.

Architecture:
  - Two consumer threads (one per topic) write into shared, thread-safe
    data structures.
  - A detector loop runs every EVAL_INTERVAL seconds, scans the windows,
    checks the thresholds, and publishes correlation events to Kafka
    topic `correlation-events`.
"""

import logging
import os
import threading
import time
from collections import defaultdict
from datetime import datetime, timezone

from dotenv import load_dotenv
load_dotenv()

from confluent_kafka import Consumer, Producer

from app.schemas.correlation import CorrelationEvent
from app.schemas.news import NewsEvent
from app.schemas.stock import StockTickEvent

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger("correlation_detector")

WINDOW_MINUTES = int(os.getenv("WINDOW_MINUTES", "60"))
NEWS_THRESHOLD = int(os.getenv("NEWS_THRESHOLD", "1"))
PRICE_CHANGE_THRESHOLD = float(os.getenv("PRICE_CHANGE_THRESHOLD", "2.0"))
EVAL_INTERVAL = int(os.getenv("EVAL_INTERVAL", "15"))
COOLDOWN_SECONDS = int(os.getenv("COOLDOWN_SECONDS", "300"))


class TickerWindow:
    """Thread-safe rolling window of news headlines and latest price for one ticker."""

    def __init__(self):
        self.lock = threading.Lock()
        self.headlines: list[tuple[float, str]] = []  # (timestamp, headline)
        self.latest_price: float | None = None
        self.price_change_pct: float | None = None

    def add_headline(self, timestamp: float, title: str):
        with self.lock:
            self.headlines.append((timestamp, title))

    def update_price(self, price: float, change_pct: float):
        with self.lock:
            self.latest_price = price
            self.price_change_pct = change_pct

    def get_window_state(self, window_seconds: int) -> tuple[int, list[str], float | None, float | None]:
        """Return (news_count, sample_headlines, price, change_pct) for the current window."""
        cutoff = time.time() - window_seconds
        with self.lock:
            self.headlines = [(ts, h) for ts, h in self.headlines if ts > cutoff]
            count = len(self.headlines)
            titles = [h for _, h in self.headlines[-5:]]
            return count, titles, self.latest_price, self.price_change_pct


windows: dict[str, TickerWindow] = defaultdict(TickerWindow)
last_fired: dict[str, float] = {}


def create_consumer(group_id: str, topics: list[str]) -> Consumer:
    bootstrap = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
    consumer = Consumer({
        "bootstrap.servers": bootstrap,
        "group.id": group_id,
        "auto.offset.reset": "earliest",
        "enable.auto.commit": True,
    })
    consumer.subscribe(topics)
    return consumer


def create_producer() -> Producer:
    bootstrap = os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092")
    return Producer({
        "bootstrap.servers": bootstrap,
        "acks": "all",
    })


def consume_news(stop_event: threading.Event):
    """Thread: consume news-headlines and update headline windows."""
    topic = os.getenv("KAFKA_TOPIC_NEWS_HEADLINES", "news-headlines")
    consumer = create_consumer("correlation-news-v2", [topic])
    logger.info("News consumer started on '%s'", topic)

    while not stop_event.is_set():
        msg = consumer.poll(1.0)
        if msg is None:
            continue
        if msg.error():
            logger.warning("News consumer error: %s", msg.error())
            continue

        try:
            event = NewsEvent.model_validate_json(msg.value())
            windows[event.ticker].add_headline(time.time(), event.title)
            logger.debug("News headline: $%s — %s", event.ticker, event.title[:60])
        except Exception as e:
            logger.warning("Bad news event: %s", e)

    consumer.close()


def consume_stocks(stop_event: threading.Event):
    """Thread: consume stock-ticks and update price state."""
    topic = os.getenv("KAFKA_TOPIC_STOCK_TICKS", "stock-ticks")
    consumer = create_consumer("correlation-stocks-v2", [topic])
    logger.info("Stock consumer started on '%s'", topic)

    while not stop_event.is_set():
        msg = consumer.poll(1.0)
        if msg is None:
            continue
        if msg.error():
            logger.warning("Stock consumer error: %s", msg.error())
            continue

        try:
            event = StockTickEvent.model_validate_json(msg.value())
            windows[event.ticker].update_price(event.price, event.change_pct)
            logger.debug("Price update: $%s @ $%.2f (%.2f%%)", event.ticker, event.price, event.change_pct)
        except Exception as e:
            logger.warning("Bad stock event: %s", e)

    consumer.close()


def run_detector(stop_event: threading.Event, producer: Producer):
    """Main loop: evaluate windows and fire correlation events."""
    output_topic = os.getenv("KAFKA_TOPIC_CORRELATION_EVENTS", "correlation-events")
    window_seconds = WINDOW_MINUTES * 60

    logger.info(
        "Detector running — window=%dmin, news_threshold=%d, price_threshold=%.1f%%, eval_interval=%ds",
        WINDOW_MINUTES, NEWS_THRESHOLD, PRICE_CHANGE_THRESHOLD, EVAL_INTERVAL,
    )

    while not stop_event.is_set():
        time.sleep(EVAL_INTERVAL)

        now = time.time()
        for ticker, window in list(windows.items()):
            count, headlines, price, change_pct = window.get_window_state(window_seconds)

            if count < NEWS_THRESHOLD:
                continue
            if change_pct is None or abs(change_pct) < PRICE_CHANGE_THRESHOLD:
                continue
            if now - last_fired.get(ticker, 0) < COOLDOWN_SECONDS:
                continue

            correlation = CorrelationEvent(
                ticker=ticker,
                news_count=count,
                price=price,
                price_change_pct=change_pct,
                window_minutes=WINDOW_MINUTES,
                headlines=headlines,
            )

            producer.produce(
                topic=output_topic,
                key=correlation.to_kafka_key(),
                value=correlation.model_dump_json(),
            )
            producer.poll(0)
            last_fired[ticker] = now

            direction = "▲" if change_pct >= 0 else "▼"
            logger.info(
                "🔔 CORRELATION: $%s — %d headlines + %s%.2f%% @ $%.2f",
                ticker, count, direction, abs(change_pct), price,
            )
            for h in headlines:
                logger.info("   └─ %s", h[:120])


def run():
    stop_event = threading.Event()
    producer = create_producer()

    news_thread = threading.Thread(target=consume_news, args=(stop_event,), daemon=True)
    stock_thread = threading.Thread(target=consume_stocks, args=(stop_event,), daemon=True)

    news_thread.start()
    stock_thread.start()

    try:
        run_detector(stop_event, producer)
    except KeyboardInterrupt:
        logger.info("Shutting down…")
        stop_event.set()

    news_thread.join(timeout=5)
    stock_thread.join(timeout=5)
    producer.flush(timeout=10)


if __name__ == "__main__":
    run()
