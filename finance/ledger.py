"""Balances: fines from attendance, dues, payments and refunds.

Fines are worked out from the marks every time rather than stored, so a
corrected mark, a waiver or a changed rate shows up everywhere at once.
Only events dated today or earlier count. Students who are not enrolled owe
nothing, though their payments still show (as credit to refund).

    balance = fines (not waived) + dues - payments + refunds
"""

from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal

from django.db.models import Sum
from django.utils import timezone

from events.models import MARK_LABELS, Attendance, Event
from roster.models import Student

from .models import Payment, Waiver

ZERO = Decimal("0.00")


@dataclass
class EventFine:
    event: Event
    missing: int
    uniform: int
    amount: Decimal
    attendance: Attendance | None = None
    waiver: Waiver | None = None

    @property
    def missing_labels(self):
        """e.g. ["AM out", "PM in"]; all marks when the student has no attendance row."""
        return [MARK_LABELS[f] for f in self.event.mark_fields if not (self.attendance and getattr(self.attendance, f))]

    @property
    def charged(self):
        return ZERO if self.waiver else self.amount


@dataclass
class Account:
    student: Student
    lines: list = field(default_factory=list)  # EventFine for each event with a fine
    dues: Decimal = ZERO
    paid: Decimal = ZERO
    refunded: Decimal = ZERO

    @property
    def fines(self):
        return sum((line.charged for line in self.lines), ZERO)

    @property
    def waived(self):
        return sum((line.amount for line in self.lines if line.waiver), ZERO)

    @property
    def absences(self):
        return sum(line.missing for line in self.lines if not line.waiver)

    @property
    def uniform_violations(self):
        return sum(line.uniform for line in self.lines if not line.waiver)

    @property
    def total_due(self):
        return self.fines + self.dues

    @property
    def balance(self):
        return self.total_due - self.paid + self.refunded

    @property
    def credit(self):
        """Overpaid amount that can be refunded (e.g. after a waiver)."""
        return max(-self.balance, ZERO)


def counted_events(term, as_of=None):
    return list(Event.objects.filter(term=term, date__lte=as_of or timezone.localdate()).order_by("date", "id"))


def event_fine(term, event, student, attendance):
    missing = attendance.missing_marks(event) if attendance else len(event.mark_fields)
    uniform = attendance.uniform_violations(event) if attendance else 0
    amount = missing * term.absence_fine_for(student) + uniform * term.uniform_fine_for(student)
    return EventFine(event=event, missing=missing, uniform=uniform, amount=amount, attendance=attendance)


def accounts_for(term, students=None, as_of=None, include_clear=False):
    """Accounts for many students of a term at once, keyed by student id.

    Lines list only events with a fine unless include_clear is set.
    """
    if students is None:
        students = Student.objects.filter(term=term)
    students = list(students)
    ids = [s.pk for s in students]
    events = counted_events(term, as_of)
    rates = list(term.dues_rates.all())

    attendance = {(a.event_id, a.student_id): a for a in Attendance.objects.filter(student__in=ids, event__in=events)}
    waivers = {
        (w.event_id, w.student_id): w
        for w in Waiver.objects.filter(student__in=ids, event__in=events, revoked_at__isnull=True)
    }
    money = defaultdict(lambda: {Payment.PAYMENT: ZERO, Payment.REFUND: ZERO})
    for row in (
        Payment.objects.filter(student__in=ids, reversed_at__isnull=True)
        .values("student_id", "kind")
        .annotate(total=Sum("amount"))
    ):
        money[row["student_id"]][row["kind"]] = row["total"]

    accounts = {}
    for student in students:
        account = Account(
            student=student, paid=money[student.pk][Payment.PAYMENT], refunded=money[student.pk][Payment.REFUND]
        )
        if student.is_enrolled:
            account.dues = term.total_dues_for(student, rates)
            for event in events:
                if not event.applies_to(student):
                    continue
                line = event_fine(term, event, student, attendance.get((event.pk, student.pk)))
                if line.amount or include_clear:
                    line.waiver = waivers.get((event.pk, student.pk))
                    account.lines.append(line)
        accounts[student.pk] = account
    return accounts


def account_for(student, as_of=None, include_clear=False):
    return accounts_for(student.term, [student], as_of, include_clear)[student.pk]
