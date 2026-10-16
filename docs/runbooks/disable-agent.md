# Disable the agent

1. Stop the foreground `sap-agent` process with Ctrl-C.
2. For immediate access revocation, remove/disable the dedicated SAP user's authorizations in SAP and rotate its credentials.
3. Set `DEMO=1` or unset provider credentials to prevent real SAP use.
4. Preserve the audit JSONL file according to your retention policy; do not edit it in place.
5. To prevent local Ollama from starting automatically, use the normal Homebrew service controls approved for the workstation.
