#!/usr/bin/env bash
set -eu
python3 --version
if ! curl -fsS --max-time 4 http://localhost:11434/v1/models >/dev/null; then
  echo "Ollama endpoint is not available" >&2
  exit 1
fi
ollama show "${MODEL:-qwen3:14b}" | sed -n '/Capabilities/,+4p'
echo "Environment check passed"
