#!/usr/bin/env bash
# Einmalig beim Anlegen des Codespace: Ollama installieren, Modell ziehen, Projekt einrichten.
set -euo pipefail

MODEL="${OLLAMA_MODEL:-qwen2.5:3b}"

curl -fsSL https://ollama.com/install.sh | sh
nohup ollama serve > /tmp/ollama.log 2>&1 &
for _ in $(seq 1 30); do
  curl -sf http://localhost:11434/api/tags > /dev/null && break
  sleep 1
done
ollama pull "$MODEL"

make setup
