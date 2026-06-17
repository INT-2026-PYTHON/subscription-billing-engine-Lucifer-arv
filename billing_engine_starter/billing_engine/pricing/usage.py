from billing_engine.money import Money
from billing_engine.pricing.base import PricingStrategy


class UsageBased(PricingStrategy):
    """Charges `unit_price * quantity`."""

    def __init__(self, unit_price: Money) -> None:
        if not isinstance(unit_price, Money):
            raise TypeError(
                f"Expected Money, got {type(unit_price).__name__}"
            )

        self.unit_price = unit_price

    def calculate(self, quantity: int) -> Money:
        if not isinstance(quantity, int):
            raise TypeError(
                f"Expected int, got {type(quantity).__name__}"
            )

        if quantity < 0:
            raise ValueError("quantity cannot be negative")

        return self.unit_price * quantity