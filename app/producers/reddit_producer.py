"""
Reddit Producer — polls public Reddit JSON endpoints for new posts
mentioning stock tickers and publishes events to Kafka topic `reddit-posts`.

No API keys required. Reddit serves JSON at any subreddit URL + `.json`.
Example: https://www.reddit.com/r/wallstreetbets/new.json

Key concepts:
  - We poll /new.json for each subreddit, tracking the latest post ID
    we've seen so we only process new posts each cycle.
  - Each post is scanned for $TICKER patterns (e.g. $AAPL, $TSLA).
  - Matching events are published to Kafka keyed by ticker symbol,
    ensuring all events for a symbol land on the same partition.
  - Rate limit: ~60 req/min unauthenticated. We stay well under this
    by polling every 10 seconds across a handful of subreddits.
"""

import logging
import os
import re
import time
from datetime import datetime, timezone

import httpx
from confluent_kafka import Producer

from app.schemas.reddit import RedditPostEvent

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger("reddit_producer")

TICKER_PATTERN = re.compile(r"\$([A-Z]{1,5})\b")

WATCHED_SUBREDDITS = [
    "wallstreetbets",
    "stocks",
    "investing",
    "options",
    "stockmarket",
]

REDDIT_BASE = "https://www.reddit.com"
USER_AGENT = "MarketPulse/0.1 (educational project)"
POLL_INTERVAL = int(os.getenv("REDDIT_POLL_INTERVAL", "10"))


def extract_tickers(text: str) -> list[str]:
    return list(set(TICKER_PATTERN.findall(text)))


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


def fetch_new_posts(client: httpx.Client, subreddit: str, after: str | None) -> tuple[list[dict], str | None]:
    """
    Fetch newest posts from a subreddit's public JSON endpoint.
    Returns (list_of_post_dicts, new_after_cursor).
    """
    url = f"{REDDIT_BASE}/r/{subreddit}/new.json"
    params = {"limit": 25, "raw_json": 1}
    if after:
        params["before"] = after

    try:
        resp = client.get(url, params=params)
        resp.raise_for_status()
    except httpx.HTTPError as e:
        logger.warning("Failed to fetch r/%s: %s", subreddit, e)
        return [], after

    data = resp.json().get("data", {})
    children = data.get("children", [])

    if not children:
        return [], after

    posts = [c["data"] for c in children if c["kind"] == "t3"]
    newest_fullname = f"t3_{posts[0]['id']}" if posts else after
    return posts, newest_fullname


def run():
    topic = os.getenv("KAFKA_TOPIC_REDDIT_POSTS", "reddit-posts")
    producer = create_producer()

    client = httpx.Client(
        headers={"User-Agent": USER_AGENT},
        timeout=15.0,
        follow_redirects=True,
    )

    cursors: dict[str, str | None] = {sub: None for sub in WATCHED_SUBREDDITS}

    logger.info(
        "Polling %d subreddits every %ds → Kafka topic '%s'",
        len(WATCHED_SUBREDDITS), POLL_INTERVAL, topic,
    )

    published_ids: set[str] = set()
    MAX_SEEN = 10_000

    try:
        while True:
            for subreddit in WATCHED_SUBREDDITS:
                posts, new_cursor = fetch_new_posts(client, subreddit, cursors[subreddit])
                cursors[subreddit] = new_cursor

                for post in posts:
                    post_id = post["id"]
                    if post_id in published_ids:
                        continue

                    combined = f"{post.get('title', '')} {post.get('selftext', '')}"
                    tickers = extract_tickers(combined)
                    if not tickers:
                        continue

                    for ticker in tickers:
                        event = RedditPostEvent(
                            event_id=f"{subreddit}:{post_id}",
                            ticker=ticker,
                            title=post.get("title", ""),
                            body=post.get("selftext", "")[:2000],
                            subreddit=subreddit,
                            author=post.get("author", "[deleted]"),
                            url=f"https://reddit.com{post.get('permalink', '')}",
                            score=post.get("score", 0),
                            created_utc=datetime.fromtimestamp(
                                post.get("created_utc", 0), tz=timezone.utc
                            ),
                        )
                        producer.produce(
                            topic=topic,
                            key=event.to_kafka_key(),
                            value=event.model_dump_json(),
                            callback=delivery_callback,
                        )
                        logger.info("→ $%s | r/%s | %s", ticker, subreddit, event.title[:80])

                    published_ids.add(post_id)
                    if len(published_ids) > MAX_SEEN:
                        published_ids.clear()

                producer.poll(0)
                time.sleep(1)

            logger.info("— cycle complete, sleeping %ds —", POLL_INTERVAL)
            time.sleep(POLL_INTERVAL)

    except KeyboardInterrupt:
        logger.info("Shutting down…")
    finally:
        client.close()
        remaining = producer.flush(timeout=10)
        if remaining:
            logger.warning("%d messages were not delivered", remaining)


if __name__ == "__main__":
    run()
