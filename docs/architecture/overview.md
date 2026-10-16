# Architecture overview

The `src/sap_agent` package separates terminal orchestration, provider adapters, tools, SAP HTTP access, security, and audit output. The CLI loads the file based system prompt and settings, creates an allow-listed registry, then sends the question and read-only tool schemas to the selected LLM. Every requested tool passes policy checks before execution. In demo mode, the OData client returns fixed synthetic records without sending a request. In real mode, it issues OData v2 GET requests only. Tool results return to the LLM; each tool call is recorded in append-only JSONL with redacted arguments. Currency calculations use Decimal and keep currencies separate.

## SAP GUI bridge

GUI access is isolated behind `GuiBridge`. Validated YAML profiles under `config/transactions/` describe transaction fields, tiers, execute keys, result grids, and row caps. A generic runner resolves fields through the bridge and executes only policy-allowed profiles. Display and report tiers run read-only under row and session-step caps; write tier requests require approval and default to deny. The default `fake` bridge simulates VA05 in memory; the Java bridge remains a stub pending a sanitized SAP GUI for Java recorded script. Each runner action is audited without field values. No real GUI automation is implemented.
