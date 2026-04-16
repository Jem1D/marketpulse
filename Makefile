.PHONY: up down logs api-install api-run news-producer stock-producer correlation-detector research-agent db-init

up:
	docker compose up -d

down:
	docker compose down

logs:
	docker compose logs -f --tail=100

api-install:
	python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt

api-run:
	. .venv/bin/activate && uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

news-producer:
	. .venv/bin/activate && python -m app.producers.news_producer

stock-producer:
	. .venv/bin/activate && python -m app.producers.stock_producer

correlation-detector:
	. .venv/bin/activate && python -m app.processors.correlation_detector

research-agent:
	. .venv/bin/activate && python -m app.agents.research_agent

db-init:
	. .venv/bin/activate && python -m app.db.init_db
