# Read-only SAP assistant

Python src-layout project for a local LLM agent that queries SAP OData. Demo mode is the default and uses synthetic records without network access. The registry and policy expose read-only sales, purchase, and currency calculation tools; there are no SAP write tools.

## Start

```sh
cd ~/Desktop/sap-agent
make install
make run
```

`make run` (equivalent to `sap-agent start` or `scripts/launch_sap_agent.sh`) checks Ollama and the configured model, opens SAP GUI for Java, tiles it beside the current Terminal, and starts the interactive agent. Log in to SAP manually. Use `/find sales orders` to search profiles, then `/run VA05 date_from=2020-01-01 date_to=2020-12-31` to run the read-only report. Natural-language SAP GUI requests use the same generic profile runner through the model. Type `exit` to quit. `make test`, `make lint`, and `make eval` run quality checks and the local-model golden set.

See [How to add a transaction profile](docs/architecture/transactions.md) before adding transaction coverage.

Window positioning needs Terminal access in **System Settings → Privacy & Security → Accessibility** and permission for Terminal to control **System Events** under **Automation**. The Java GUI bridge remains unavailable until its recorded scripting flow is reviewed.

## Configuration

Settings precedence is `config/base.yaml`, `config/{APP_ENV}.yaml`, `.env`, then process environment. Demo remains enabled by default. For real SAP, set `DEMO=0`, `S4_DESTINATION_URL`, `S4_CLIENT`, `S4_USERNAME`, and `S4_PASSWORD` (legacy `SAP_*` URL/user/password are also supported). The client uses HTTP Basic auth and `sap-client`. `S4_CONNECTION_TYPE` is retained as metadata for direct URL configurations.

Choose `PROVIDER=ollama` (default), `gemini`, or `groq`; configure cloud API keys via environment or `.env`. Confidential SAP data must not be sent to free cloud providers. Review `docs/security` before enabling production connections.
