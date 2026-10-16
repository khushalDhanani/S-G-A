# How to add a transaction profile

1. Add one YAML file under `config/transactions/`; do not add transaction-specific Python code.
2. Follow `config/transactions/schema.json`. Set the SAP code, module, tier (`display`, `report`, or `write`), description, search keywords, fields with visible labels and positions, execute operation, result grid, and row cap.
3. Keep values as supplied by the runner. Date and number format conversion belongs in the GUI bridge.
4. Add the transaction code to `allowed_transactions` in `config/tool_policy.yaml`. Unknown or unlisted codes are denied. Write-tier profiles require approval, which denies by default.
5. Extend the fake bridge only when needed to simulate a visible field or result shape; never connect it to SAP.
6. Add schema-validation and generic runner tests for required fields, popup/status errors, stale snapshots, row caps, tier policy, session-step caps, and audit redaction.
7. Run `make test` and `make lint`. Verify that action audits include operation, redacted target, and status without entered values.
