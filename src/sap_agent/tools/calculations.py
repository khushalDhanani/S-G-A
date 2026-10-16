"""Currency-safe exact calculations."""

from decimal import ROUND_HALF_UP, Decimal
from typing import Any


def _parse_amount(value: Any) -> Decimal:
    raw = str(value).strip().replace(" ", "")
    if not raw:
        return Decimal("0")
    if "," in raw and "." in raw:
        if raw.rfind(",") > raw.rfind("."):
            raw = raw.replace(".", "").replace(",", ".")
        else:
            raw = raw.replace(",", "")
    elif "," in raw:
        # Check if comma is used as decimal separator (e.g. 1250,50)
        parts = raw.split(",")
        if len(parts) == 2 and len(parts[1]) <= 2:
            raw = raw.replace(",", ".")
        else:
            raw = raw.replace(",", "")
    return Decimal(raw)


def calc_totals(
    rows: list[dict[str, Any]], amount_field: str, currency_field: str
) -> dict[str, float]:
    totals: dict[str, Decimal] = {}
    for row in rows:
        if currency_field not in row or amount_field not in row:
            continue
        currency = str(row[currency_field]).strip()
        if not currency:
            continue
        totals[currency] = totals.get(currency, Decimal("0")) + _parse_amount(row[amount_field])
    return {
        currency: float(amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
        for currency, amount in sorted(totals.items())
    }
