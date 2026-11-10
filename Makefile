PY := .venv/bin/python
export OLLAMA_MODEL ?= qwen2.5:3b
.PHONY: setup run test check-all up down real pull

setup:
	python3.12 -m venv .venv
	.venv/bin/pip install -q -e ".[dev]"

# Dashboard ohne Docker: Fake Ergebnisse erzeugen und Seite auf Port 8080 ausliefern
run:
	LLM_MODE=fake $(PY) -m labellab.cli
	@echo "Dashboard: http://localhost:8080"
	cd web && ../$(PY) -m http.server 8080

test:
	$(PY) -m pytest -q

# Tests, danach alle Produkte im Fake Modus pruefen und results.json schreiben
check-all: test
	LLM_MODE=fake $(PY) -m labellab.cli

# Alles mit Docker: Postgres (5442), API und Dashboard (8000), n8n (5678)
up:
	docker compose up --build

down:
	docker compose down

# Echter Lauf mit lokalem Modell (Ollama muss laufen)
real:
	LLM_MODE=ollama $(PY) -m labellab.cli

# Modell fuer den echten Lauf laden (Ollama muss laufen)
pull:
	ollama pull $(OLLAMA_MODEL)
