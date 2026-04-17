# MarketPulse Project Handoff Guide

## 1. Purpose
MarketPulse is a real-time pipeline that correlates stock price moves with recent financial news headlines, then uses a local LLM (Ollama) to generate a concise analyst-style explanation and embedding for storage/querying.

Core objective:
- Detect meaningful events: significant price change + recent news activity for the same ticker.
- Generate human-readable explanation.
- Persist enriched reports in PostgreSQL with pgvector embeddings.

## 2. High-Level Architecture
Pipeline stages:
1. Producers publish raw events to Kafka:
- News producer -> `news-headlines`
- Stock producer -> `stock-ticks`
- (Optional) Reddit producer -> `reddit-posts`

2. Correlation detector consumes `news-headlines` + `stock-ticks`:
- Maintains rolling per-ticker windows.
- Emits `correlation-events` when thresholds are met.

3. Research agent consumes `correlation-events`:
- Calls Ollama chat model for summary.
- Calls Ollama embedding model for vector.
- Stores result in PostgreSQL table `correlation_reports`.

4. API service:
- Provides service health/root endpoints.

## 3. Repository Structure
- `app/main.py`: FastAPI app (`/` and `/health` only).
- `app/producers/news_producer.py`: Yahoo Finance news ingestor.
- `app/producers/stock_producer.py`: Yahoo Finance quote ingestor.
- `app/producers/reddit_producer.py`: Reddit ingestor (currently separate from correlation logic).
- `app/processors/correlation_detector.py`: Event correlation engine.
- `app/agents/research_agent.py`: LLM enrichment + DB persistence.
- `app/db/session.py`: SQLAlchemy engine/session config from env vars.
- `app/db/models.py`: `CorrelationReport` model with `Vector(768)` embedding column.
- `app/db/init_db.py`: DB initialization + pgvector extension enablement.
- `app/schemas/*.py`: Pydantic contracts for Kafka events.
- `docker-compose.yml`: Kafka + PostgreSQL services.
- `Dockerfile`: API image build.
- `Makefile`: Dev commands.

## 4. Runtime Dependencies
Infrastructure:
- Kafka broker (Docker Compose)
- PostgreSQL (pgvector image)

Application/runtime:
- Python 3.11+
- Ollama running locally (for research agent)

Python packages (from `requirements.txt`):
- fastapi, uvicorn[standard], pydantic-settings
- confluent-kafka, httpx, yfinance
- sqlalchemy, psycopg2-binary, pgvector
- openai (currently not used in active code path)

## 5. Environment Variables
Baseline values are in `.env.example`.

General:
- `APP_ENV=development`
- `APP_PORT=8000`

Kafka:
- `KAFKA_BOOTSTRAP_SERVERS=localhost:9092`
- `KAFKA_TOPIC_NEWS_HEADLINES=news-headlines`
- `KAFKA_TOPIC_STOCK_TICKS=stock-ticks`
- `KAFKA_TOPIC_CORRELATION_EVENTS=correlation-events`
- `KAFKA_TOPIC_REDDIT_POSTS=reddit-posts` (used by reddit producer default)

PostgreSQL:
- `POSTGRES_HOST=localhost`
- `POSTGRES_PORT=5432`
- `POSTGRES_DB=marketpulse`
- `POSTGRES_USER=marketpulse`
- `POSTGRES_PASSWORD=marketpulse`

Ollama:
- `OLLAMA_BASE_URL=http://127.0.0.1:11434`
- `OLLAMA_CHAT_MODEL=gemma3:4b`
- `OLLAMA_EMBED_MODEL=nomic-embed-text`

Correlation detector tuning:
- `WINDOW_MINUTES=60`
- `NEWS_THRESHOLD=1`
- `PRICE_CHANGE_THRESHOLD=2.0`
- `EVAL_INTERVAL=15`
- `COOLDOWN_SECONDS=300`

Producer polling (optional overrides):
- `NEWS_POLL_INTERVAL=60`
- `STOCK_POLL_INTERVAL=30`
- `REDDIT_POLL_INTERVAL=10`

Dynamic watchlist options:
- `EXTRA_WATCHED_TICKERS=` (comma-separated symbols merged with defaults)
- `WATCHLIST_FILE=app/data/user_tickers.json` (persistent user ticker store)

## 6. Local Setup (Recommended)
1. Create env file:
```bash
cp .env.example .env
```

2. Start infrastructure:
```bash
make up
```

3. Install Python dependencies:
```bash
make api-install
```

4. Start Ollama in another terminal:
```bash
ollama serve
```

5. Pull required models:
```bash
make ollama-pull
```

6. Optional connectivity test:
```bash
make test-ollama
```

7. Initialize DB schema:
```bash
make db-init
```

## 7. Running Services (Typical Multi-Terminal Workflow)
Terminal A:
```bash
make news-producer
```

Terminal B:
```bash
make stock-producer
```

Terminal C:
```bash
make correlation-detector
```

Terminal D:
```bash
make research-agent
```

Terminal E (optional API):
```bash
make api-run
```

Health check:
```bash
curl http://localhost:8000/health
```

Watchlist API examples:
```bash
curl http://localhost:8000/watchlist
curl -X POST http://localhost:8000/watchlist -H 'Content-Type: application/json' -d '{"ticker":"NFLX"}'
curl -X DELETE http://localhost:8000/watchlist/NFLX
```

## 8. Data Contracts
### 8.1 `news-headlines` (`NewsEvent`)
Fields:
- `article_id`, `ticker`, `title`, `summary`, `publisher`, `url`
- `published_at`, `ingested_at`
Keyed by: ticker

### 8.2 `stock-ticks` (`StockTickEvent`)
Fields:
- `ticker`, `price`, `open`, `high`, `low`, `volume`
- `change_pct`, `previous_close`, `market_time`, `ingested_at`
Keyed by: ticker

### 8.3 `correlation-events` (`CorrelationEvent`)
Fields:
- `ticker`, `news_count`, `price`, `price_change_pct`
- `window_minutes`, `headlines`, `detected_at`
Keyed by: ticker

### 8.4 `reddit-posts` (`RedditPostEvent`)
Fields:
- `event_id`, `ticker`, `title`, `body`, `subreddit`
- `author`, `url`, `score`, `created_utc`, `ingested_at`
Keyed by: ticker

Note:
- Current correlation logic consumes only `news-headlines` and `stock-ticks`.
- `reddit-posts` is present but not integrated into detector logic in this version.

## 9. Database Schema
Table: `correlation_reports`
- `id` (PK)
- `ticker` (indexed)
- `price`
- `price_change_pct`
- `news_count`
- `headlines` (Postgres text array)
- `summary` (LLM output)
- `embedding` (`vector(768)`)
- `detected_at`
- `created_at`

DB initialization behavior:
- Ensures pgvector extension exists.
- Checks embedding dimension; drops/recreates table if embedding type dimension mismatches expected 768.

## 10. Makefile Command Reference
- `make up`: start Kafka + Postgres.
- `make down`: stop infra.
- `make logs`: follow docker compose logs.
- `make api-install`: create `.venv` + install requirements.
- `make api-run`: run FastAPI app.
- `make news-producer`: start news producer.
- `make stock-producer`: start stock producer.
- `make correlation-detector`: start detector.
- `make research-agent`: start research agent.
- `make db-init`: initialize DB schema/extensions.
- `make ollama-pull`: pull required Ollama models.
- `make test-ollama`: smoke test Ollama chat endpoint.

## 11. Known Issue and Root Cause Notes
### Symptom
Research agent logs:
- `Failed to process event: [Errno 61] Connection refused`

### Root cause
The research agent calls Ollama at `OLLAMA_BASE_URL` (default `http://127.0.0.1:11434`).
If no service is listening on that address/port, each event fails during summary/embedding generation.

### Verification
```bash
curl -sS -m 3 http://127.0.0.1:11434/api/tags
lsof -nP -iTCP:11434 -sTCP:LISTEN
```

### Fix
1. Start Ollama: `ollama serve`
2. Pull models: `make ollama-pull`
3. Retry agent: `make research-agent`

### Container caveat
If research agent runs inside Docker, `127.0.0.1` points to container loopback, not host.
Use:
- `OLLAMA_BASE_URL=http://host.docker.internal:11434`

## 12. Operational Troubleshooting Checklist
### Kafka issues
- Validate broker running:
```bash
docker compose ps
```
- Check logs:
```bash
make logs
```
- Confirm topic auto-creation is enabled (it is in compose).

### Postgres issues
- Check DB health in compose logs.
- Validate credentials match `.env`.
- Re-run `make db-init` after infra starts.

### Producer silence
- News/stock APIs can rate limit or return partial data.
- Keep polling intervals reasonable; transient failures are expected.

### Correlation detector not firing
- Verify both producers running.
- Verify thresholds are not too strict:
  - `NEWS_THRESHOLD`
  - `PRICE_CHANGE_THRESHOLD`
- Wait for `WINDOW_MINUTES` data accumulation.

### Research agent not storing reports
- Confirm Ollama reachable.
- Confirm DB reachable.
- Confirm embedding model dimension matches DB expectation (`768`).

## 13. Security and Reliability Notes
- No explicit auth, secrets vault, or topic ACLs in current local setup.
- Public data sources are used (Yahoo Finance, Reddit JSON).
- Error handling is mostly log-and-continue to keep streams alive.
- Consider introducing:
  - centralized structured logging
  - retries/backoff for Ollama calls
  - dead-letter topics for malformed events
  - metrics and alerting

## 14. Handoff Runbook (Fast Start)
For a new owner:
1. Install Docker, Python 3.11+, and Ollama.
2. Clone repo, `cp .env.example .env`.
3. `make up`
4. `make api-install`
5. In separate terminal: `ollama serve`
6. `make ollama-pull`
7. `make db-init`
8. Start workers:
   - `make news-producer`
   - `make stock-producer`
   - `make correlation-detector`
   - `make research-agent`
9. Optionally run API: `make api-run`
10. Monitor logs for correlation and report storage messages.

## 15. Suggested Next Improvements
- Add a dedicated consumer/CLI for inspecting `correlation_reports`.
- Add integration tests with mocked Kafka/Ollama.
- Add health-check endpoint for downstream dependencies.
- Add optional Docker service for research agent with explicit Ollama host config.
- Add retention and cleanup strategy for DB and Kafka topics.

## 16. Ownership Notes
Current status summary:
- Core stream pipeline is functional.
- Key operational dependency: Ollama availability.
- Project is suitable for local development and demonstration use.
- Production hardening (auth, monitoring, resilience) remains to be done.
