"""
VATCalculator — single-rate VAT (e.g. 19% in Germany).
"""

from decimal import Decimal

from billing_engine.money import Money
from billing_engine.taxes.base import TaxCalculator, TaxContext, TaxBreakdown


class VATCalculator(TaxCalculator):
    def __init__(self, rate: Decimal) -> None:
        if not isinstance(rate, Decimal):
            raise TypeError(
                f"Expected Decimal, got {type(rate).__name__}"
            )

        if rate < Decimal("0") or rate > Decimal("1"):
            raise ValueError(
                "rate must be between 0 and 1 inclusive"
            )

        self.rate = rate

    def apply(self, taxable: Money, context: TaxContext) -> TaxBreakdown:
        vat = taxable * self.rate
        percent = self.rate * Decimal("100")

        return TaxBreakdown(
            components=[
                (f"VAT {percent}%", vat)
            ],
            total_tax=vat,
        )