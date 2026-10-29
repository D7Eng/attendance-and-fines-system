"""Term-wide totals built from the per-student accounts."""

from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal

from finance.ledger import ZERO, accounts_for, counted_events


@dataclass
class Totals:
    students: int = 0
    fines: Decimal = ZERO
    waived: Decimal = ZERO
    dues: Decimal = ZERO
    paid: Decimal = ZERO
    refunded: Decimal = ZERO
    outstanding: Decimal = ZERO  # sum of positive balances
    credit: Decimal = ZERO  # sum of overpayments
    absences: int = 0
    uniform_violations: int = 0

    def add(self, acct):
        self.students += 1
        self.fines += acct.fines
        self.waived += acct.waived
        self.dues += acct.dues
        self.paid += acct.paid
        self.refunded += acct.refunded
        self.outstanding += max(acct.balance, ZERO)
        self.credit += acct.credit
        self.absences += acct.absences
        self.uniform_violations += acct.uniform_violations

    @property
    def billed(self):
        return self.fines + self.dues

    @property
    def collected_net(self):
        return self.paid - self.refunded

    @property
    def collection_rate(self):
        return (self.collected_net / self.billed * 100) if self.billed else Decimal(0)


@dataclass
class EventTotals:
    event: object
    expected: int = 0
    complete: int = 0
    missing: int = 0
    uniform: int = 0
    fines: Decimal = ZERO
    waived: Decimal = ZERO
    absentees: list = field(default_factory=list)  # (student, EventFine) with any fine

    @property
    def attendance_rate(self):
        return (Decimal(self.complete) / self.expected * 100) if self.expected else Decimal(0)


def term_summary(term, students=None, as_of=None):
    """Return (accounts, overall Totals, Totals by year level, EventTotals by event) for a term."""
    accounts = accounts_for(term, students, as_of, include_clear=True)
    overall = Totals()
    by_year = defaultdict(Totals)
    events = {e.pk: EventTotals(event=e) for e in counted_events(term, as_of)}
    for acct in accounts.values():
        if not acct.student.is_enrolled and not acct.paid:
            continue
        overall.add(acct)
        by_year[acct.student.year_level].add(acct)
        for line in acct.lines:
            totals = events[line.event.pk]
            totals.expected += 1
            if not line.amount:
                totals.complete += 1
                continue
            totals.absentees.append((acct.student, line))
            if line.waiver:
                totals.waived += line.amount
            else:
                totals.fines += line.amount
                totals.missing += line.missing
                totals.uniform += line.uniform
    return accounts, overall, dict(sorted(by_year.items())), list(events.values())
