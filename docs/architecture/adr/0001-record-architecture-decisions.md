# ADR 0001: Record architecture decisions

- Status: Accepted
- Context: The assistant needs a reviewable structure that can evolve without coupling the model, SAP transport, policy, and terminal UX.
- Decision: Keep provider, tool, SAP, security, and observability modules separate under `src/sap_agent`; store prompts and environment policy in files.
- Consequences: Components can be tested independently with scripted LLMs and HTTPX MockTransport. Small modules require explicit interfaces and some wiring.
