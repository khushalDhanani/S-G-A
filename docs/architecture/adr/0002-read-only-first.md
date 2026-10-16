# ADR 0002: Read-only first

- Status: Accepted
- Context: An LLM can misunderstand requests or be influenced by untrusted SAP text. Mutating an ERP system creates material business risk.
- Decision: SAP OData transport exposes GET only; policy allow-lists two query services and caps rows at 50. The registry permits the named `gui_act` tool as the sole write-risk exception; it is constrained by GUI transaction/action policy and uses default-deny approval for destructive actions. Its configured default bridge is an in-memory fake, while the Java bridge remains unimplemented.
- Consequences: OData tools cannot change SAP state. GUI actions currently affect only the fake bridge. Real GUI support requires the pending recorded script, a reviewed bridge implementation, and follow-up tests.
