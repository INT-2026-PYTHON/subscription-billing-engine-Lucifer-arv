"""
PaymentGateway — abstract + two mock implementations.
"""

from __future__ import annotations

import random
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

from billing_engine.models import Invoice


@dataclass(frozen=True)
class PaymentResult:
    success: bool
    failure_reason: Optional[str] = None


class PaymentGateway(ABC):
    @abstractmethod
    def charge(self, invoice: Invoice) -> PaymentResult:
        raise NotImplementedError


class ScriptedGateway(PaymentGateway):
    """Returns pre-set results from a queue. Used in tests."""

    def __init__(self, results: list[PaymentResult]) -> None:
        self.results = list(results)
        self.index = 0

    def charge(self, invoice: Invoice) -> PaymentResult:
        if self.index >= len(self.results):
            raise IndexError("No more scripted payment results available")

        result = self.results[self.index]
        self.index += 1
        return result


class FakeRandomGateway(PaymentGateway):
    """Succeeds at a configurable rate; seeded for reproducibility."""

    def __init__(self, success_rate: float = 0.7, seed: Optional[int] = None) -> None:
        if success_rate < 0 or success_rate > 1:
            raise ValueError("success_rate must be between 0 and 1")

        self.success_rate = success_rate
        self.random = random.Random(seed)

    def charge(self, invoice: Invoice) -> PaymentResult:
        if self.random.random() < self.success_rate:
            return PaymentResult(True)

        return PaymentResult(False, "DECLINED")