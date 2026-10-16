"""Purchase order read tool."""

from typing import Any

from sap_agent.sap.odata_client import ODataClient
from sap_agent.tools.base import Tool

PARAMETERS = {
    "type": "object",
    "properties": {
        "filter": {"type": "string"},
        "select": {"type": "string"},
        "top": {"type": "integer", "maximum": 50},
    },
    "additionalProperties": False,
}


def make_tool(client: ODataClient) -> Tool:
    def list_purchase_orders(filter: str = "", select: str = "", top: int = 10) -> dict[str, Any]:
        return client.query("API_PURCHASEORDER_PROCESS_SRV", "A_PurchaseOrder", filter, select, top)

    return Tool(
        "list_purchase_orders",
        "List SAP purchase orders (read only).",
        PARAMETERS,
        "read",
        list_purchase_orders,
    )
