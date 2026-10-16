# Read-only SAP assistant

Python src-layout project for a local LLM agent that queries SAP OData. Demo mode is the default and uses synthetic records without network access. The registry and policy expose read-only sales, purchase, and currency calculation tools; there are no SAP write tools.

## Start

```sh
cd ~/Desktop/sap-agent
make install
make run
```

`make run` (equivalent to `sap-agent start` or `scripts/launch_sap_agent.sh`) checks Ollama and the configured model, opens SAP GUI for Java, tiles it beside the current Terminal, and starts the interactive agent. Log in to SAP manually. The default GUI backend is `fake`: it uses in-memory synthetic data and never connects to SAP. The `java` backend is intentionally unavailable until a sanitized SAP GUI scripting recording and working macOS access to the live process have been reviewed. Do not configure `gui.bridge=java` expecting live control today.

Use `/find sales orders` to search profiles. `/run VA05 date_from=2020-01-01 date_to=2020-12-31` fills the selection and verifies the values without executing the report. Append `--execute` to prepare an allowed read-only report for confirmation: `/run VA05 date_from=2020-01-01 date_to=2020-12-31 --execute`. The agent verifies the fields and asks `VA05 is prepared. Execute?`; reply `yes` to execute or `no` to cancel. Natural-language requests use the same two-step confirmation. Runner progress reports each observed, filled, verified, and executed phase without printing field values. Type `exit` to quit. `make test`, `make lint`, and `make eval` run checks and the local-model golden set.

See [How to add a transaction profile](docs/architecture/transactions.md) before adding transaction coverage.

Window positioning and any future live GUI bridge need Terminal access in **System Settings → Privacy & Security → Accessibility** and permission for Terminal to control **System Events** under **Automation**. The live bridge must also use the SAP GUI for Java scripting interface enabled in **Preferences → Web AS ABAP → Scripting**. No live session is inspected or controlled by the fake backend.

## Configuration

Settings precedence is `config/base.yaml`, `config/{APP_ENV}.yaml`, `.env`, then process environment. Demo remains enabled by default. For real SAP, set `DEMO=0`, `S4_DESTINATION_URL`, `S4_CLIENT`, `S4_USERNAME`, and `S4_PASSWORD` (legacy `SAP_*` URL/user/password are also supported). The client uses HTTP Basic auth and `sap-client`. `S4_CONNECTION_TYPE` is retained as metadata for direct URL configurations.

Choose `PROVIDER=ollama` (default), `gemini`, or `groq`; configure cloud API keys via environment or `.env`. Confidential SAP data must not be sent to free cloud providers. Review `docs/security` before enabling production connections.
