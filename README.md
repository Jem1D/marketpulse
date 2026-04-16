# MarketPulse

Real-Time Reddit x Stock Correlation Engine.

## Step 0 Setup

### 1) Start infrastructure

```bash
make up
```

This starts:
- Kafka on `localhost:9092`
- PostgreSQL (`pgvector`) on `localhost:5432`

### 2) Run API locally

```bash
make api-install
make api-run
```

Health check:

```bash
curl http://localhost:8000/health
```

### 3) Environment variables

```bash
cp .env.example .env
```

## What comes next

Step 1 will add a Reddit producer that pushes normalized events to Kafka topic `reddit-posts`.
