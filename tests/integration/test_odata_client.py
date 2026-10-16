import httpx
import pytest

from sap_agent.sap.odata_client import ODataClient
from sap_agent.settings import Settings


@pytest.mark.parametrize("status", [401, 403, 404])
def test_http_errors_are_returned_without_sensitive_body(status: int) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, text="sensitive backend detail", request=request)

    client = ODataClient(
        Settings(demo=False, sap_base_url="https://sap.invalid"),
        transport=httpx.MockTransport(handler),
    )
    result = client.query("API_SALES_ORDER_SRV", "A_SalesOrder", top=1)
    client.close()
    assert result == {"error": f"SAP HTTP {status}"}


def test_odata_v2_response_and_client_parameter() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.params["sap-client"] == "100"
        return httpx.Response(200, json={"d": {"results": [{"SalesOrder": "1"}]}}, request=request)

    settings = Settings(demo=False, s4_destination_url="https://sap.invalid", s4_client="100")
    client = ODataClient(settings, transport=httpx.MockTransport(handler))
    assert client.query("API_SALES_ORDER_SRV", "A_SalesOrder")["results"] == [{"SalesOrder": "1"}]
    client.close()


def test_demo_does_not_use_transport() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("demo mode must not make network calls")

    client = ODataClient(Settings(demo=True), transport=httpx.MockTransport(handler))
    assert len(client.query("API_SALES_ORDER_SRV", "A_SalesOrder", top=5)["results"]) == 5
    client.close()
