from billing_engine.money import Money
from billing_engine.pricing.base import PricingStrategy


class Freemium(PricingStrategy):
    """Returns 0 for quantity <= free_quota, else delegates overage to inner strategy."""

    def __init__(self, free_quota: int, overage_strategy: PricingStrategy) -> None:
        if not isinstance(free_quota, int):
            raise TypeError(
                f"Expected int, got {type(free_quota).__name__}"
            )

        if free_quota < 0:
            raise ValueError("free_quota cannot be negative")

        if not isinstance(overage_strategy, PricingStrategy):
            raise TypeError(
                f"Expected PricingStrategy, got {type(overage_strategy).__name__}"
            )

        self.free_quota = free_quota
        self.overage_strategy = overage_strategy

    def calculate(self, quantity: int) -> Money:
        if quantity <= self.free_quota:
            return Money("0", self.overage_strategy.calculate(0).currency)

        overage = quantity - self.free_quota
        return self.overage_strategy.calculate(overage)