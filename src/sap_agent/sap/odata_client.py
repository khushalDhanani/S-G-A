"""Read-only SAP OData v2 GET client."""

from typing import Any
from urllib.parse import quote

import httpx

from sap_agent.sap import demo_data
from sap_agent.sap.auth import basic_auth
from sap_agent.settings import Settings


class ODataClient:
    def __init__(self, settings: Settings, transport: httpx.BaseTransport | None = None) -> None:
        self.settings = settings
        self.client = httpx.Client(timeout=30, transport=transport)

    def query(
        self, service: str, entity_set: str, filter_: str = "", select: str = "", top: int = 10
    ) -> dict[str, Any]:
        top = min(max(int(top), 1), 50)
        if self.settings.demo:
            rows = (
                demo_data.SALES_ORDERS
                if service == "API_SALES_ORDER_SRV"
                else demo_data.PURCHASE_ORDERS
            )
            return {"demo": True, "results": rows[:top]}
        base = (self.settings.s4_destination_url or self.settings.sap_base_url).rstrip("/")
        if not base:
            return {"error": "S4_DESTINATION_URL or SAP_BASE_URL is required when DEMO=0"}
        params: dict[str, Any] = {"$format": "json", "$top": top}
        if filter_:
            params["$filter"] = filter_
        if select:
            params["$select"] = select
        if self.settings.s4_client:
            params["sap-client"] = self.settings.s4_client
        url = f"{base}/sap/opu/odata/sap/{quote(service)}/{quote(entity_set)}"
        try:
            response = self.client.get(url, params=params, auth=basic_auth(self.settings))
            response.raise_for_status()
            payload = response.json()
            return {"demo": False, "results": payload.get("d", {}).get("results", [])}
        except httpx.HTTPStatusError as exc:
            return {"error": f"SAP HTTP {exc.response.status_code}"}
        except Exception as exc:
            return {"error": f"SAP request failed: {type(exc).__name__}"}

    def close(self) -> None:
        self.client.close()
