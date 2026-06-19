"""
DunningProcess — finite state machine for failed-payment retries.

States:
    PENDING       (initial)  →  RETRYING  on first failure
    RETRYING      ──→ SUCCEEDED    when a retry succeeds
                  ──→ FAILED_FINAL after 3 total failures
    SUCCEEDED     (terminal)
    FAILED_FINAL  (terminal — also flips subscription to PAST_DUE)

Retry schedule:
    attempt 2 scheduled at  now + 1 day
    attempt 3 scheduled at  now + 3 days
    (no attempt 4 — after the 3rd failure we mark FAILED_FINAL)

After the subscription has been PAST_DUE for 7 days with no recovery,
the BillingCycle.run (Day 2 work) may flip it to CANCELLED — that
transition does NOT live in this file.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import Enum
from typing import Optional

from billing_engine.db import (
    InvoiceRepository, LedgerRepository, SubscriptionRepository,
    PaymentAttemptRepository,
)
from billing_engine.models import Invoice, LedgerEntry, LedgerDirection, SubscriptionStatus, InvoiceStatus
from billing_engine.payments.gateway import PaymentGateway, PaymentResult


class DunningState(str, Enum):
    PENDING = "PENDING"
    RETRYING = "RETRYING"
    SUCCEEDED = "SUCCEEDED"
    FAILED_FINAL = "FAILED_FINAL"


@dataclass(frozen=True)
class DunningOutcome:
    state: DunningState
    attempt_no: int
    next_retry_at: Optional[datetime]


# Retry intervals (in days) after each failure, indexed by attempt_no JUST COMPLETED.
# After failure of attempt 1, schedule attempt 2 at +1 day.
# After failure of attempt 2, schedule attempt 3 at +3 days.
# After failure of attempt 3, no more retries → FAILED_FINAL.
RETRY_DELAYS_DAYS = {1: 1, 2: 3}
MAX_ATTEMPTS = 3


class DunningProcess:
    def __init__(
        self,
        gateway: PaymentGateway,
        invoice_repo: InvoiceRepository,
        ledger_repo: LedgerRepository,
        subscription_repo: SubscriptionRepository,
        attempt_repo: PaymentAttemptRepository,
    ) -> None:
        self.gateway = gateway
        self.invoice_repo = invoice_repo
        self.ledger_repo = ledger_repo
        self.subscription_repo = subscription_repo
        self.attempt_repo = attempt_repo

    def attempt(self, invoice: Invoice, customer_id: int, now: datetime) -> DunningOutcome:
        """Try once. Record the attempt. Return the resulting outcome."""
        attempt_no = self.attempt_repo.count_for_invoice(invoice.id) + 1

        result = self.gateway.charge(invoice)

        if result.success:
            self.attempt_repo.add(
                invoice_id=invoice.id,
                attempt_no=attempt_no,
                status="SUCCESS",
                failure_reason=None,
                next_retry_at=None,
            )
            self.invoice_repo.mark_paid(invoice.id)

            return DunningOutcome(
                state=DunningState.SUCCEEDED,
                attempt_no=attempt_no,
                next_retry_at=None,
            )

        if attempt_no >= MAX_ATTEMPTS:
            self.attempt_repo.add(
                invoice_id=invoice.id,
                attempt_no=attempt_no,
                status="FAILED",
                failure_reason=result.failure_reason,
                next_retry_at=None,
            )
            with self.invoice_repo.db.connect() as conn:
                conn.execute(
                    "UPDATE invoices SET status=? WHERE id=?",
                    (InvoiceStatus.FAILED.value, invoice.id),
                )
            self.subscription_repo.update_status(
                invoice.subscription_id,
                 SubscriptionStatus.PAST_DUE,
            )

            return DunningOutcome(
                state=DunningState.FAILED_FINAL,
                attempt_no=attempt_no,
                next_retry_at=None,
            )

        delay_days = RETRY_DELAYS_DAYS[attempt_no]
        next_retry_at = now + timedelta(days=delay_days)

        self.attempt_repo.add(
            invoice_id=invoice.id,
            attempt_no=attempt_no,
            status="FAILED",
            failure_reason=result.failure_reason,
            next_retry_at=next_retry_at,
        )

        return DunningOutcome(
            state=DunningState.RETRYING,
            attempt_no=attempt_no,
            next_retry_at=next_retry_at,
        )

    # --------------------------------------------------------
    @staticmethod
    def should_cancel(past_due_since: date, today: date, grace_days: int = 7) -> bool:
        """Helper used by BillingCycle to decide PAST_DUE → CANCELLED."""
        return (today - past_due_since).days >= grace_days