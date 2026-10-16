"""Fixed synthetic records for no-network demo operation."""

from typing import Any

SALES_ORDERS: list[dict[str, Any]] = [
    {
        "SalesOrder": "1000001",
        "CreationDate": "2020-01-10",
        "SoldToParty": "1001",
        "TotalNetAmount": "100.00",
        "TransactionCurrency": "RUB",
    },
    {
        "SalesOrder": "1000002",
        "CreationDate": "2020-02-10",
        "SoldToParty": "1002",
        "TotalNetAmount": "200.00",
        "TransactionCurrency": "RUB",
    },
    {
        "SalesOrder": "1000003",
        "CreationDate": "2020-03-10",
        "SoldToParty": "1003",
        "TotalNetAmount": "600.00",
        "TransactionCurrency": "RUB",
    },
    {
        "SalesOrder": "1000004",
        "CreationDate": "2020-04-10",
        "SoldToParty": "1004",
        "TotalNetAmount": "5000.50",
        "TransactionCurrency": "USD",
    },
    {
        "SalesOrder": "1000005",
        "CreationDate": "2020-05-10",
        "SoldToParty": "1005",
        "TotalNetAmount": "12543.00",
        "TransactionCurrency": "USD",
    },
]

PURCHASE_ORDERS: list[dict[str, Any]] = []
