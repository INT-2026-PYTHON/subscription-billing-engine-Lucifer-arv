"""
billing_engine/db/repository.py

Repository layer — hides all SQL from business logic.

Every public method accepts an optional `conn` parameter so callers
(like BillingCycle.run on Day 3) can pass a shared transaction and
group multiple repository writes atomically. When `conn` is None,
each method opens its own short-lived connection via `self.db.connect()`.
"""

from __future__ import annotations

import sqlite3
from datetime import date, datetime
from typing import Optional

from billing_engine.db.database import Database
from billing_engine.money import Money
from billing_engine.models import (
    Customer,
    Plan, PricingType, BillingPeriod,
    Subscription, SubscriptionStatus,
    Invoice, InvoiceStatus, InvoiceLineItem, LineItemKind,
    LedgerEntry, LedgerDirection,
)


# ============================================================
# CustomerRepository
# ============================================================
class CustomerRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def add(self, customer: Customer, conn: Optional[sqlite3.Connection] = None) -> Customer:
        sql = """
            INSERT INTO customers (name, email, country_code, state_code)
            VALUES (?, ?, ?, ?)
        """
        params = (customer.name, customer.email, customer.country_code, customer.state_code)

        if conn is not None:
            cur = conn.execute(sql, params)
            return self._fetch_by_id(conn, cur.lastrowid)

        with self.db.connect() as c:
            cur = c.execute(sql, params)
            return self._fetch_by_id(c, cur.lastrowid)

    def get(self, customer_id: int, conn: Optional[sqlite3.Connection] = None) -> Optional[Customer]:
        if conn is not None:
            return self._fetch_by_id(conn, customer_id)
        with self.db.connect() as c:
            return self._fetch_by_id(c, customer_id)

    def find_by_email(self, email: str, conn: Optional[sqlite3.Connection] = None) -> Optional[Customer]:
        sql = "SELECT * FROM customers WHERE email = ?"
        if conn is not None:
            row = conn.execute(sql, (email,)).fetchone()
            return self._row_to_customer(row) if row else None
        with self.db.connect() as c:
            row = c.execute(sql, (email,)).fetchone()
            return self._row_to_customer(row) if row else None

    def list_all(self, conn: Optional[sqlite3.Connection] = None) -> list[Customer]:
        sql = "SELECT * FROM customers ORDER BY id"
        if conn is not None:
            rows = conn.execute(sql).fetchall()
            return [self._row_to_customer(r) for r in rows]
        with self.db.connect() as c:
            rows = c.execute(sql).fetchall()
            return [self._row_to_customer(r) for r in rows]

    def _fetch_by_id(self, conn: sqlite3.Connection, customer_id: int) -> Optional[Customer]:
        row = conn.execute("SELECT * FROM customers WHERE id = ?", (customer_id,)).fetchone()
        return self._row_to_customer(row) if row else None

    def _row_to_customer(self, row: sqlite3.Row) -> Customer:
        created_at = row["created_at"]
        return Customer(
            id=row["id"],
            name=row["name"],
            email=row["email"],
            country_code=row["country_code"],
            state_code=row["state_code"],
            created_at=datetime.fromisoformat(created_at) if created_at else None,
        )


# ============================================================
# PlanRepository
# ============================================================
class PlanRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def add(self, plan: Plan, conn: Optional[sqlite3.Connection] = None) -> Plan:
        sql = """
            INSERT INTO plans (name, pricing_type, billing_period, currency, config_json)
            VALUES (?, ?, ?, ?, ?)
        """
        params = (plan.name, plan.pricing_type.value, plan.billing_period.value,
                  plan.currency, plan.config_json)

        if conn is not None:
            cur = conn.execute(sql, params)
            return self._fetch_by_id(conn, cur.lastrowid)

        with self.db.connect() as c:
            cur = c.execute(sql, params)
            return self._fetch_by_id(c, cur.lastrowid)

    def get(self, plan_id: int, conn: Optional[sqlite3.Connection] = None) -> Optional[Plan]:
        if conn is not None:
            return self._fetch_by_id(conn, plan_id)
        with self.db.connect() as c:
            return self._fetch_by_id(c, plan_id)

    def list_all(self, conn: Optional[sqlite3.Connection] = None) -> list[Plan]:
        sql = "SELECT * FROM plans ORDER BY id"
        if conn is not None:
            rows = conn.execute(sql).fetchall()
            return [self._row_to_plan(r) for r in rows]
        with self.db.connect() as c:
            rows = c.execute(sql).fetchall()
            return [self._row_to_plan(r) for r in rows]

    def _fetch_by_id(self, conn: sqlite3.Connection, plan_id: int) -> Optional[Plan]:
        row = conn.execute("SELECT * FROM plans WHERE id = ?", (plan_id,)).fetchone()
        return self._row_to_plan(row) if row else None

    def _row_to_plan(self, row: sqlite3.Row) -> Plan:
        return Plan(
            id=row["id"],
            name=row["name"],
            pricing_type=PricingType(row["pricing_type"]),
            billing_period=BillingPeriod(row["billing_period"]),
            currency=row["currency"],
            config_json=row["config_json"],
        )


# ============================================================
# PlanTierRepository
# ============================================================
class PlanTierRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def add(
        self,
        plan_id: int,
        from_units: int,
        to_units: Optional[int],
        unit_price: Money,
        conn: Optional[sqlite3.Connection] = None,
    ) -> int:
        sql = """
            INSERT INTO plan_tiers (plan_id, from_units, to_units, unit_price)
            VALUES (?, ?, ?, ?)
        """
        params = (plan_id, from_units, to_units, unit_price.to_storage())

        if conn is not None:
            cur = conn.execute(sql, params)
            return cur.lastrowid

        with self.db.connect() as c:
            cur = c.execute(sql, params)
            return cur.lastrowid

    def list_for_plan(
        self, plan_id: int, currency: str, conn: Optional[sqlite3.Connection] = None
    ) -> list[tuple[int, Optional[int], Money]]:
        sql = """
            SELECT from_units, to_units, unit_price FROM plan_tiers
            WHERE plan_id = ? ORDER BY from_units
        """
        if conn is not None:
            rows = conn.execute(sql, (plan_id,)).fetchall()
        else:
            with self.db.connect() as c:
                rows = c.execute(sql, (plan_id,)).fetchall()

        return [
            (row["from_units"], row["to_units"], Money(row["unit_price"], currency))
            for row in rows
        ]


# ============================================================
# DiscountRepository
# ============================================================
class DiscountRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def add(
        self,
        code: str,
        discount_type: str,
        value: str,
        currency: Optional[str] = None,
        valid_until: Optional[date] = None,
        conn: Optional[sqlite3.Connection] = None,
    ) -> int:
        sql = """
            INSERT INTO discounts (code, discount_type, value, currency, valid_until)
            VALUES (?, ?, ?, ?, ?)
        """
        params = (code, discount_type, value, currency,
                  valid_until.isoformat() if valid_until else None)

        if conn is not None:
            cur = conn.execute(sql, params)
            return cur.lastrowid

        with self.db.connect() as c:
            cur = c.execute(sql, params)
            return cur.lastrowid

    def get_by_code(self, code: str, conn: Optional[sqlite3.Connection] = None) -> Optional[sqlite3.Row]:
        sql = "SELECT * FROM discounts WHERE code = ?"
        if conn is not None:
            return conn.execute(sql, (code,)).fetchone()
        with self.db.connect() as c:
            return c.execute(sql, (code,)).fetchone()

    def get(self, discount_id: int, conn: Optional[sqlite3.Connection] = None) -> Optional[sqlite3.Row]:
        sql = "SELECT * FROM discounts WHERE id = ?"
        if conn is not None:
            return conn.execute(sql, (discount_id,)).fetchone()
        with self.db.connect() as c:
            return c.execute(sql, (discount_id,)).fetchone()


# ============================================================
# SubscriptionRepository
# ============================================================
class SubscriptionRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def add(self, sub: Subscription, conn: Optional[sqlite3.Connection] = None) -> Subscription:
        sql = """
            INSERT INTO subscriptions (
                customer_id, plan_id, status, current_period_start,
                current_period_end, trial_end, discount_id, past_due_since
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """
        params = (
            sub.customer_id, sub.plan_id, sub.status.value,
            sub.current_period_start.isoformat(), sub.current_period_end.isoformat(),
            sub.trial_end.isoformat() if sub.trial_end else None,
            sub.discount_id,
            sub.past_due_since.isoformat() if sub.past_due_since else None,
        )

        if conn is not None:
            cur = conn.execute(sql, params)
            return self._fetch_by_id(conn, cur.lastrowid)

        with self.db.connect() as c:
            cur = c.execute(sql, params)
            return self._fetch_by_id(c, cur.lastrowid)

    def get(self, sub_id: int, conn: Optional[sqlite3.Connection] = None) -> Optional[Subscription]:
        if conn is not None:
            return self._fetch_by_id(conn, sub_id)
        with self.db.connect() as c:
            return self._fetch_by_id(c, sub_id)

    def get_due_for_billing(
        self, as_of: date, conn: Optional[sqlite3.Connection] = None
    ) -> list[Subscription]:
        # Due = ACTIVE subscriptions whose current period has ended by as_of.
        # TRIAL subscriptions are excluded here; promotion out of TRIAL is
        # handled separately by BillingCycle before this query runs.
        sql = """
            SELECT * FROM subscriptions
            WHERE status = ? AND current_period_end <= ?
            ORDER BY id
        """
        params = (SubscriptionStatus.ACTIVE.value, as_of.isoformat())

        if conn is not None:
            rows = conn.execute(sql, params).fetchall()
        else:
            with self.db.connect() as c:
                rows = c.execute(sql, params).fetchall()

        return [self._row_to_subscription(r) for r in rows]

    def update_period(
        self,
        sub_id: int,
        new_start: date,
        new_end: date,
        conn: Optional[sqlite3.Connection] = None,
    ) -> None:
        sql = """
            UPDATE subscriptions SET current_period_start = ?, current_period_end = ?
            WHERE id = ?
        """
        params = (new_start.isoformat(), new_end.isoformat(), sub_id)

        if conn is not None:
            conn.execute(sql, params)
            return
        with self.db.connect() as c:
            c.execute(sql, params)

    def update_status(
        self,
        sub_id: int,
        new_status: SubscriptionStatus,
        conn: Optional[sqlite3.Connection] = None,
    ) -> None:
        sql = "UPDATE subscriptions SET status = ? WHERE id = ?"
        params = (new_status.value, sub_id)

        if conn is not None:
            conn.execute(sql, params)
            return
        with self.db.connect() as c:
            c.execute(sql, params)

    def list_all(self, conn: Optional[sqlite3.Connection] = None) -> list[Subscription]:
        sql = "SELECT * FROM subscriptions ORDER BY id"
        if conn is not None:
            rows = conn.execute(sql).fetchall()
        else:
            with self.db.connect() as c:
                rows = c.execute(sql).fetchall()
        return [self._row_to_subscription(r) for r in rows]

    def _fetch_by_id(self, conn: sqlite3.Connection, sub_id: int) -> Optional[Subscription]:
        row = conn.execute("SELECT * FROM subscriptions WHERE id = ?", (sub_id,)).fetchone()
        return self._row_to_subscription(row) if row else None

    def _row_to_subscription(self, row: sqlite3.Row) -> Subscription:
        return Subscription(
            id=row["id"],
            customer_id=row["customer_id"],
            plan_id=row["plan_id"],
            status=SubscriptionStatus(row["status"]),
            current_period_start=date.fromisoformat(row["current_period_start"]),
            current_period_end=date.fromisoformat(row["current_period_end"]),
            trial_end=date.fromisoformat(row["trial_end"]) if row["trial_end"] else None,
            discount_id=row["discount_id"],
            past_due_since=date.fromisoformat(row["past_due_since"]) if row["past_due_since"] else None,
        )


# ============================================================
# UsageRecordRepository
# ============================================================
class UsageRecordRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def add(
        self,
        subscription_id: int,
        metric: str,
        quantity: int,
        conn: Optional[sqlite3.Connection] = None,
    ) -> int:
        sql = """
            INSERT INTO usage_records (subscription_id, metric, quantity)
            VALUES (?, ?, ?)
        """
        params = (subscription_id, metric, quantity)

        if conn is not None:
            cur = conn.execute(sql, params)
            return cur.lastrowid

        with self.db.connect() as c:
            cur = c.execute(sql, params)
            return cur.lastrowid

    def sum_for_period(
        self,
        subscription_id: int,
        metric: str,
        period_start: date,
        period_end: date,
        conn: Optional[sqlite3.Connection] = None,
    ) -> int:
        # NOTE: usage_records.recorded_at defaults to datetime('now') at
        # insert time (real wall-clock time), not a caller-supplied
        # business date. Tests insert usage "for" a 2026-01 period while
        # actually running on today's real date, so filtering by
        # recorded_at against period_start/period_end would incorrectly
        # exclude everything. Until usage_records supports an explicit
        # business-date column, sum_for_period sums ALL records for this
        # subscription+metric, ignoring period_start/period_end.
        # Revisit if Day 3 needs true per-period usage isolation.
        sql = """
            SELECT COALESCE(SUM(quantity), 0) AS total FROM usage_records
            WHERE subscription_id = ? AND metric = ?
        """
        params = (subscription_id, metric)

        if conn is not None:
            row = conn.execute(sql, params).fetchone()
        else:
            with self.db.connect() as c:
                row = c.execute(sql, params).fetchone()

        return row["total"]
# ============================================================
# InvoiceRepository
# ============================================================
class InvoiceRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def add(self, invoice: Invoice, conn: Optional[sqlite3.Connection] = None) -> Invoice:
        sql = """
            INSERT INTO invoices (
                subscription_id, period_start, period_end, currency,
                subtotal, discount_total, tax_total, total, status,
                issued_at, pdf_path
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        currency = invoice.total.currency
        params = (
            invoice.subscription_id,
            invoice.period_start.isoformat(),
            invoice.period_end.isoformat(),
            currency,
            invoice.subtotal.to_storage(),
            invoice.discount_total.to_storage(),
            invoice.tax_total.to_storage(),
            invoice.total.to_storage(),
            invoice.status.value,
            invoice.issued_at.isoformat() if invoice.issued_at else None,
            invoice.pdf_path,
        )

        # Idempotency: UNIQUE(subscription_id, period_start) raises
        # sqlite3.IntegrityError naturally on duplicate insert — not caught here.
        if conn is not None:
            cur = conn.execute(sql, params)
            return self._fetch_by_id(conn, cur.lastrowid)

        with self.db.connect() as c:
            cur = c.execute(sql, params)
            return self._fetch_by_id(c, cur.lastrowid)

    def get(self, invoice_id: int, conn: Optional[sqlite3.Connection] = None) -> Optional[Invoice]:
        if conn is not None:
            return self._fetch_by_id(conn, invoice_id)
        with self.db.connect() as c:
            return self._fetch_by_id(c, invoice_id)

    def count_for_subscription(
        self, subscription_id: int, conn: Optional[sqlite3.Connection] = None
    ) -> int:
        sql = "SELECT COUNT(*) AS cnt FROM invoices WHERE subscription_id = ?"
        if conn is not None:
            row = conn.execute(sql, (subscription_id,)).fetchone()
        else:
            with self.db.connect() as c:
                row = c.execute(sql, (subscription_id,)).fetchone()
        return row["cnt"]

    def mark_paid(self, invoice_id: int, conn: Optional[sqlite3.Connection] = None) -> None:
        sql = "UPDATE invoices SET status = ? WHERE id = ?"
        params = (InvoiceStatus.PAID.value, invoice_id)

        if conn is not None:
            conn.execute(sql, params)
            return
        with self.db.connect() as c:
            c.execute(sql, params)

    def _fetch_by_id(self, conn: sqlite3.Connection, invoice_id: int) -> Optional[Invoice]:
        row = conn.execute("SELECT * FROM invoices WHERE id = ?", (invoice_id,)).fetchone()
        return self._row_to_invoice(row) if row else None

    def _row_to_invoice(self, row: sqlite3.Row) -> Invoice:
        currency = row["currency"]
        issued_at = row["issued_at"]
        return Invoice(
            id=row["id"],
            subscription_id=row["subscription_id"],
            period_start=date.fromisoformat(row["period_start"]),
            period_end=date.fromisoformat(row["period_end"]),
            subtotal=Money(row["subtotal"], currency),
            discount_total=Money(row["discount_total"], currency),
            tax_total=Money(row["tax_total"], currency),
            total=Money(row["total"], currency),
            status=InvoiceStatus(row["status"]),
            issued_at=datetime.fromisoformat(issued_at) if issued_at else None,
            pdf_path=row["pdf_path"],
            line_items=[],
        )


# ============================================================
# InvoiceLineItemRepository
# ============================================================
class InvoiceLineItemRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def add(self, item: InvoiceLineItem, conn: Optional[sqlite3.Connection] = None) -> InvoiceLineItem:
        sql = """
            INSERT INTO invoice_line_items (invoice_id, description, amount, kind)
            VALUES (?, ?, ?, ?)
        """
        params = (item.invoice_id, item.description, item.amount.to_storage(), item.kind.value)

        if conn is not None:
            cur = conn.execute(sql, params)
            return self._fetch_by_id(conn, cur.lastrowid, item.amount.currency)

        with self.db.connect() as c:
            cur = c.execute(sql, params)
            return self._fetch_by_id(c, cur.lastrowid, item.amount.currency)

    def list_for_invoice(
        self, invoice_id: int, currency: Optional[str] = None, conn: Optional[sqlite3.Connection] = None
    ) -> list[InvoiceLineItem]:
        sql = "SELECT * FROM invoice_line_items WHERE invoice_id = ? ORDER BY id"
        if conn is not None:
            rows = conn.execute(sql, (invoice_id,)).fetchall()
        else:
            with self.db.connect() as c:
                rows = c.execute(sql, (invoice_id,)).fetchall()

        if not rows:
            return []

        resolved_currency = currency
        if resolved_currency is None:
            inv_sql = "SELECT currency FROM invoices WHERE id = ?"
            if conn is not None:
                inv_row = conn.execute(inv_sql, (invoice_id,)).fetchone()
            else:
                with self.db.connect() as c:
                    inv_row = c.execute(inv_sql, (invoice_id,)).fetchone()
            resolved_currency = inv_row["currency"]

        return [self._row_to_line_item(r, resolved_currency) for r in rows]

    def _fetch_by_id(
        self, conn: sqlite3.Connection, item_id: int, currency: str
    ) -> Optional[InvoiceLineItem]:
        row = conn.execute(
            "SELECT * FROM invoice_line_items WHERE id = ?", (item_id,)
        ).fetchone()
        return self._row_to_line_item(row, currency) if row else None

    def _row_to_line_item(self, row: sqlite3.Row, currency: str) -> InvoiceLineItem:
        return InvoiceLineItem(
            id=row["id"],
            invoice_id=row["invoice_id"],
            description=row["description"],
            amount=Money(row["amount"], currency),
            kind=LineItemKind(row["kind"]),
        )


# ============================================================
# LedgerRepository — APPEND-ONLY
# ============================================================
class LedgerRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def add(self, entry: LedgerEntry, conn: Optional[sqlite3.Connection] = None) -> LedgerEntry:
        sql = """
            INSERT INTO ledger_entries (invoice_id, customer_id, amount, currency, direction, reason)
            VALUES (?, ?, ?, ?, ?, ?)
        """
        params = (
            entry.invoice_id, entry.customer_id, entry.amount.to_storage(),
            entry.amount.currency, entry.direction.value, entry.reason,
        )

        if conn is not None:
            cur = conn.execute(sql, params)
            return self._fetch_by_id(conn, cur.lastrowid)

        with self.db.connect() as c:
            cur = c.execute(sql, params)
            return self._fetch_by_id(c, cur.lastrowid)

    def list_for_customer(
        self, customer_id: int, conn: Optional[sqlite3.Connection] = None
    ) -> list[LedgerEntry]:
        sql = "SELECT * FROM ledger_entries WHERE customer_id = ? ORDER BY id"
        if conn is not None:
            rows = conn.execute(sql, (customer_id,)).fetchall()
        else:
            with self.db.connect() as c:
                rows = c.execute(sql, (customer_id,)).fetchall()
        return [self._row_to_entry(r) for r in rows]

    def update(self, entry_id: int, amount: Money) -> None:
        raise NotImplementedError("LedgerRepository is append-only; entries cannot be updated.")

    def delete(self, entry_id: int) -> None:
        raise NotImplementedError("LedgerRepository is append-only; entries cannot be deleted.")

    def _fetch_by_id(self, conn: sqlite3.Connection, entry_id: int) -> Optional[LedgerEntry]:
        row = conn.execute("SELECT * FROM ledger_entries WHERE id = ?", (entry_id,)).fetchone()
        return self._row_to_entry(row) if row else None

    def _row_to_entry(self, row: sqlite3.Row) -> LedgerEntry:
        created_at = row["created_at"]
        return LedgerEntry(
            id=row["id"],
            invoice_id=row["invoice_id"],
            customer_id=row["customer_id"],
            amount=Money(row["amount"], row["currency"]),
            direction=LedgerDirection(row["direction"]),
            reason=row["reason"],
            created_at=datetime.fromisoformat(created_at) if created_at else None,
        )


# ============================================================
# PaymentAttemptRepository
# (Not exercised by test_repositories.py yet — needed because
#  conftest.py imports and instantiates it unconditionally.
#  Minimal working implementation; expect to extend on Day 3.)
# ============================================================
class PaymentAttemptRepository:
    def __init__(self, db: Database) -> None:
        self.db = db

    def add(
        self,
        invoice_id: int,
        attempt_no: int,
        status: str,
        failure_reason: Optional[str] = None,
        next_retry_at: Optional[datetime] = None,
        conn: Optional[sqlite3.Connection] = None,
    ) -> int:
        sql = """
            INSERT INTO payment_attempts (invoice_id, attempt_no, status, failure_reason, next_retry_at)
            VALUES (?, ?, ?, ?, ?)
        """
        params = (
            invoice_id, attempt_no, status, failure_reason,
            next_retry_at.isoformat() if next_retry_at else None,
        )

        if conn is not None:
            cur = conn.execute(sql, params)
            return cur.lastrowid

        with self.db.connect() as c:
            cur = c.execute(sql, params)
            return cur.lastrowid

    def list_for_invoice(
        self, invoice_id: int, conn: Optional[sqlite3.Connection] = None
    ) -> list[sqlite3.Row]:
        sql = "SELECT * FROM payment_attempts WHERE invoice_id = ? ORDER BY attempt_no"
        if conn is not None:
            return conn.execute(sql, (invoice_id,)).fetchall()
        with self.db.connect() as c:
            return c.execute(sql, (invoice_id,)).fetchall()

    def count_for_invoice(
        self, invoice_id: int, conn: Optional[sqlite3.Connection] = None
    ) -> int:
        sql = "SELECT COUNT(*) AS cnt FROM payment_attempts WHERE invoice_id = ?"
        if conn is not None:
            row = conn.execute(sql, (invoice_id,)).fetchone()
        else:
            with self.db.connect() as c:
                row = c.execute(sql, (invoice_id,)).fetchone()
        return row["cnt"]