"""
FixedAmountDiscount — e.g., flat ₹500 off.

CAPPING RULE: if the fixed amount exceeds the subtotal, return subtotal
(so the discounted total never goes below zero).
"""

from billing_engine.money import Money
from billing_engine.discounts.base import Discount, DiscountContext


class FixedAmountDiscount(Discount):
    def __init__(self, amount: Money) -> None:
        if not isinstance(amount, Money):
            raise TypeError(
                f"Expected Money, got {type(amount).__name__}"
            )

        self.amount = amount

    def apply(self, subtotal: Money, context: DiscountContext) -> Money:
        # Cap the discount at the subtotal amount
        if self.amount > subtotal:
            return subtotal

        return self.amount