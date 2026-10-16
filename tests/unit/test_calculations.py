from sap_agent.sap.demo_data import SALES_ORDERS
from sap_agent.tools.calculations import calc_totals


def test_currency_totals() -> None:
    assert calc_totals(SALES_ORDERS, "TotalNetAmount", "TransactionCurrency") == {
        "RUB": 900.0,
        "USD": 17543.5,
    }
