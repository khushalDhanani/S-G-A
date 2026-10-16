#!/usr/bin/env bash
set -eu
python3 - <<'PY'
import os
import sys
import httpx

base = os.getenv("S4_DESTINATION_URL") or os.getenv("SAP_BASE_URL", "")
username = os.getenv("S4_USERNAME") or os.getenv("SAP_USER", "")
password = os.getenv("S4_PASSWORD") or os.getenv("SAP_PASSWORD", "")
if not base:
    print("Set S4_DESTINATION_URL (or SAP_BASE_URL) first", file=sys.stderr)
    raise SystemExit(2)
params = {"$format": "json", "$top": "1"}
client = os.getenv("S4_CLIENT", "")
if client:
    params["sap-client"] = client
try:
    response = httpx.get(f"{base.rstrip('/')}/sap/opu/odata/sap/API_SALES_ORDER_SRV/A_SalesOrder",
                         params=params, auth=(username, password), timeout=30)
    print(f"SAP connection status: HTTP {response.status_code}")
    raise SystemExit(0 if response.is_success else 1)
except httpx.RequestError as exc:
    print(f"SAP connection failed: {type(exc).__name__}", file=sys.stderr)
    raise SystemExit(1)
PY
