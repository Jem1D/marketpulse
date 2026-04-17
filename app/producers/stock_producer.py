"""
Stock Tick Producer — polls Yahoo Finance for price snapshots and publishes
events to Kafka topic `stock-ticks`.

No API keys required. yfinance wraps Yahoo Finance's public endpoints.

Key concepts:
  - We track a fixed watchlist of popular tickers (the same ones the
    Reddit producer looks for). This keeps both topics aligned so the
    downstream correlation detector can join them by symbol.
  - Each poll cycle fetches current price info for all tickers in one
    batch call (yfinance supports this natively).
  - Events are keyed by ticker symbol → same partitioning strategy as
    the Reddit producer, so a stream join by key is straightforward.
  - We store the previous close so downstream can compute intraday
    percent change without needing historical state.
"""

import logging
import os
import time
from datetime import datetime, timezone

from dotenv import load_dotenv
load_dotenv()

import yfinance as yf
from confluent_kafka import Producer

from app.schemas.stock import StockTickEvent
from app.watchlist import get_effective_tickers

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger("stock_producer")

POLL_INTERVAL = int(os.getenv("STOCK_POLL_INTERVAL", "30"))


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


def fetch_ticks(tickers: list[str]) -> list[StockTickEvent]:
    """Fetch current price data for all watched tickers individually.

    Uses .info instead of .fast_info because fast_info.previous_close
    returns the after-hours adjusted close, not the official market close.
    The .info endpoint gives regularMarketPreviousClose which matches
    what financial sites display.
    """
    events = []

    for symbol in tickers:
        try:
            ticker = yf.Ticker(symbol)
            info = ticker.info

            price = info.get("regularMarketPrice") or info.get("currentPrice")
            prev_close = info.get("regularMarketPreviousClose")

            if price is None or prev_close is None or prev_close == 0:
                logger.warning("Skipping %s — incomplete data", symbol)
                continue

            change_pct = ((price - prev_close) / prev_close) * 100

            event = StockTickEvent(
                ticker=symbol,
                price=round(price, 2),
                open=round(info.get("regularMarketOpen", 0), 2),
                high=round(info.get("regularMarketDayHigh", 0), 2),
                low=round(info.get("regularMarketDayLow", 0), 2),
                volume=int(info.get("regularMarketVolume", 0)),
                change_pct=round(change_pct, 4),
                previous_close=round(prev_close, 2),
                market_time=datetime.now(timezone.utc),
            )
            events.append(event)

        except Exception as e:
            logger.warning("Failed to fetch %s: %s", symbol, e)

    return events


def run():
    topic = os.getenv("KAFKA_TOPIC_STOCK_TICKS", "stock-ticks")
    producer = create_producer()

    logger.info("Polling stock ticks every %ds → Kafka topic '%s'", POLL_INTERVAL, topic)

    try:
        while True:
            processed: set[str] = set()
            events: list[StockTickEvent] = []

            while True:
                tickers = get_effective_tickers()
                pending = [symbol for symbol in tickers if symbol not in processed]
                if not pending:
                    break

                logger.info("Stock cycle watchlist size: %d", len(tickers))
                batch = fetch_ticks(pending)
                events.extend(batch)

                for symbol in pending:
                    processed.add(symbol)

            for event in events:
                producer.produce(
                    topic=topic,
                    key=event.to_kafka_key(),
                    value=event.model_dump_json(),
                    callback=delivery_callback,
                )
                direction = "▲" if event.change_pct >= 0 else "▼"
                logger.info(
                    "→ %s $%.2f %s %.2f%%",
                    event.ticker, event.price, direction, abs(event.change_pct),
                )

            producer.poll(0)
            logger.info("— tick cycle complete (%d tickers), sleeping %ds —", len(events), POLL_INTERVAL)
            time.sleep(POLL_INTERVAL)

    except KeyboardInterrupt:
        logger.info("Shutting down…")
    finally:
        remaining = producer.flush(timeout=10)
        if remaining:
            logger.warning("%d messages were not delivered", remaining)


if __name__ == "__main__":
    run()
