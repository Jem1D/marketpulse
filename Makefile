.PHONY: up down logs api-install api-run news-producer stock-producer correlation-detector research-agent db-init ollama-pull test-ollama

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

ollama-pull:
	ollama pull gemma3:4b
	ollama pull nomic-embed-text

test-ollama:
	curl -s http://127.0.0.1:11434/api/chat -d '{"model":"gemma3:4b","messages":[{"role":"user","content":"Say OK in one word"}],"stream":false}' | python3 -c "import sys,json; print(json.load(sys.stdin)['message']['content'])"
