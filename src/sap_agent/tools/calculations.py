"""Currency-safe exact calculations."""

from decimal import ROUND_HALF_UP, Decimal
from typing import Any


def calc_totals(
    rows: list[dict[str, Any]], amount_field: str, currency_field: str
) -> dict[str, float]:
    totals: dict[str, Decimal] = {}
    for row in rows:
        currency = str(row[currency_field])
        totals[currency] = totals.get(currency, Decimal("0")) + Decimal(str(row[amount_field]))
    return {
        currency: float(amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
        for currency, amount in sorted(totals.items())
    }
