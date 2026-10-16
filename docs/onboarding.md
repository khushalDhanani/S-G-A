# Onboarding

1. Install Python 3.10+ and Ollama; pull `qwen3:14b`.
2. `cd ~/Desktop/sap-agent`
3. `python3 -m venv .venv && source .venv/bin/activate`
4. `python -m pip install -e '.[dev]'`
5. `cp .env.example .env` (if needed), keep `DEMO=1`, then run `sap-agent`.

Type `exit` to quit. Run `make test` and `make lint` before proposing changes.
