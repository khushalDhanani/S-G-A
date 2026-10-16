# SAP GUI for Java Native Scripting & Agent Bridge

## Architecture Overview

The SAP GUI Agent controls **LIVE SAP GUI for Java** (8.10rev13) on macOS natively without fake workflows, macros, or AppleScript. It operates through an in-process Java agent attached directly to the running SAP GUI JVM process.

```
+-------------------------------------------------------------+
|                     Python Agent CLI / Core                |
|           (OBSERVE -> UNDERSTAND -> PLAN -> ACT -> VERIFY)   |
+-------------------------------------------------------------+
                              |
                     HTTP JSON API (Localhost)
                              |
+-------------------------------------------------------------+
|   SAP GUI for Java JVM Process (com.sap.platin.Gui)         |
|                                                             |
|   +-----------------------------------------------------+   |
|   |  SapBridgeAgent (Attached via HotSpot JVMTI/Agent)  |   |
|   |  - HTTP Daemon (127.0.0.1:49221)                    |   |
|   |  - GuiSessionFinder (Locates active SAP GUI session)|   |
|   |  - Hierarchy Walker & Component Resolution          |   |
|   |  - ALV Grid Extractor (SapGrid / Shell Bean)        |   |
|   |  - Native JavaScriptInterpreter (GuiSession)        |   |
|   +-----------------------------------------------------+   |
|                              |                              |
|            SAP GUI Component Model & S/4HANA Server          |
+-------------------------------------------------------------+
```

## How It Works

1. **Process Discovery & Auto-Attach**:
   - `JavaScriptBridge` discovers the running SAP GUI process using the bundled SAP JRE `jps -l` tool (locating `com.sap.platin.Gui`).
   - If the HTTP daemon is not yet listening, `AttachLoader` uses the bundled `VirtualMachine.attach(pid)` to dynamically load `sap-bridge-agent.jar` into the live JVM.

2. **In-Process HTTP API**:
   - `GET /health`: Returns connection health, system ID (`DS4`), client (`220`), user (`KHUSHAL`), transaction, and current window title.
   - `POST /observe`: Traverses the live GUI hierarchy (`GuiComponentHierarchyWalker`), extracting screen title, transaction, program name, status bar message, input fields (with labels and positional relationships like `from`/`to`), buttons, radio buttons, and ALV Grids. Generates a fresh `snapshot_id`.
   - `POST /act`: Validates that the provided `snapshot_id` matches the current screen. If stale, the action is rejected immediately (`Stale snapshot_id; observe the screen again before acting.`). Applies requested operations (`open_tx`, `set_field`, `press`, `vkey`, `select_rows`), allows GUI settling, and returns the updated screen state.
   - `POST /eval`: Evaluates arbitrary SAP GUI native JavaScript in the context of the active `GuiSession` via `com.sap.platin.base.scripting.javaScript.JavaScriptInterpreter`.
   - `POST /stop`: Gracefully shuts down the HTTP daemon server.

3. **Dynamic ALV Grid Extraction**:
   - ALV Grids embedded in `GuiShell` containers (`com.sap.components.controls.advancedGrid.SapGrid`) are dynamically accessed via `getBean()`.
   - Columns are extracted using `getColumnOrder()` and translated to human-readable titles via `getDisplayedColumnTitle(colId)`.
   - Cell contents are read with `getCellValue(row, colId)`.
   - Row selections are applied with `setPersonasSelectedRows()` and `setSelectedRowsS()`.

## Agentic Loop & Safety Guarantees

- **OBSERVE**: Discovers all active controls, labels, and ALV Grid data without hardcoding.
- **UNDERSTAND**: Resolves fields based on visible labels, tooltips, and relative positions (`from`, `to`, `value`).
- **PLAN**: Determines the required atomic operations (`set_field`, `press`, `vkey`, `select_rows`).
- **ACT**: Executes operations through the bridge with exact snapshot validation.
- **VERIFY**: Performs read-back verification of entered values and checks status bar feedback.
- **REPORT**: Calculates summaries and reports structured findings.
- **SAFETY GATE**: Execute, save, post, and delete operations strictly require explicit user approval. Non-interactive sessions fail closed.

## Verification

The complete live control flow is verified on the active SAP GUI session with:
```bash
./.venv/bin/python scripts/verify_live_sap.py
```
This tests navigation, date entry, read-back verification, report execution, 682-entry ALV Grid inspection, row selection, currency totals calculation, and stale snapshot rejection.
