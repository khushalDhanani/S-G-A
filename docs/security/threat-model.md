# Threat model

| Threat | Mitigation in this skeleton |
| --- | --- |
| Prompt injection in SAP text fields | System prompt treats records as untrusted; model can call only registered read tools; policy checks every call. |
| Credential leakage | Passwords use `SecretStr`; audit redacts secret keys; logs omit full row payloads; `.env` is ignored. |
| Over-privileged SAP user | Onboard a dedicated SAP account with read-only authorizations; client uses GET requests only. |
| Data exfiltration to cloud LLM | Default provider is local Ollama; classification guidance says confidential data must not go to free cloud providers. |
| Runaway tool loop | `max_tool_rounds` is bounded; result payloads are truncated. |

Residual risk: cloud providers can receive prompts when configured. Operators must classify data and choose an approved provider before real SAP access.
