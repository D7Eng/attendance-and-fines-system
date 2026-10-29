"""Writing money: payments, refunds, reversals and waivers.

Each change locks the student's roster row so two treasurers cannot both
take the last peso of a balance.
"""

import re
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from audit.log import record
from roster.models import Student

from .ledger import account_for
from .models import Counter, Payment, Waiver


def normalize_gcash_ref(value):
    ref = re.sub(r"[\s-]+", "", value or "")
    if ref and not ref.isalnum():
        raise ValidationError("The GCash reference number can only have letters and digits.")
    return ref.upper()


def _locked(student):
    return Student.objects.select_for_update(of=("self",)).select_related("term").get(pk=student.pk)


def _receipt_no(kind):
    prefix = Payment.PREFIX[kind]
    return f"{prefix}-{Counter.next(prefix):05d}"


@transaction.atomic
def record_payment(student, amount, user, method=Payment.CASH, gcash_ref="", note=""):
    student = _locked(student)
    amount = Decimal(amount)
    if amount <= 0:
        raise ValidationError("Enter an amount above zero.")
    gcash_ref = normalize_gcash_ref(gcash_ref)
    if method == Payment.GCASH and not gcash_ref:
        raise ValidationError("Enter the GCash reference number.")
    if method != Payment.GCASH:
        gcash_ref = ""
    if gcash_ref:
        used = Payment.objects.filter(term=student.term, gcash_ref=gcash_ref, reversed_at__isnull=True).first()
        if used:
            raise ValidationError(
                f"GCash reference {gcash_ref} was already used this term on {used.receipt_no} ({used.student})."
            )
    balance = account_for(student).balance
    if amount > balance:
        raise ValidationError(f"Overpayment rejected: the balance is {max(balance, Decimal(0)):,.2f}.")
    try:
        with transaction.atomic():
            payment = Payment.objects.create(
                term=student.term,
                student=student,
                kind=Payment.PAYMENT,
                amount=amount,
                method=method,
                gcash_ref=gcash_ref,
                receipt_no=_receipt_no(Payment.PAYMENT),
                note=note,
                balance_after=balance - amount,
                recorded_by=user,
            )
    except IntegrityError as exc:
        raise ValidationError(f"GCash reference {gcash_ref} was already used this term.") from exc
    record(
        "payment",
        f"{payment.receipt_no}: {amount:,.2f} {payment.get_method_display()} from {student}",
        target=payment,
        actor=user,
        gcash_ref=gcash_ref,
        balance_after=payment.balance_after,
    )
    return payment


@transaction.atomic
def record_refund(student, amount, user, reason, method=Payment.CASH, gcash_ref=""):
    student = _locked(student)
    amount = Decimal(amount)
    if amount <= 0:
        raise ValidationError("Enter an amount above zero.")
    if not reason.strip():
        raise ValidationError("Give a reason for the refund.")
    account = account_for(student)
    if amount > account.credit:
        raise ValidationError(f"A refund can be at most the student's credit ({account.credit:,.2f}).")
    refund = Payment.objects.create(
        term=student.term,
        student=student,
        kind=Payment.REFUND,
        amount=amount,
        method=method,
        gcash_ref=normalize_gcash_ref(gcash_ref) if method == Payment.GCASH else "",
        receipt_no=_receipt_no(Payment.REFUND),
        note=reason,
        balance_after=account.balance + amount,
        recorded_by=user,
    )
    record(
        "refund", f"{refund.receipt_no}: refunded {amount:,.2f} to {student}", target=refund, actor=user, reason=reason
    )
    return refund


@transaction.atomic
def reverse_payment(payment, user, reason):
    """Void a payment or refund entered by mistake. It stays on record, marked reversed."""
    _locked(payment.student)
    payment = Payment.objects.select_for_update().get(pk=payment.pk)
    if payment.is_reversed:
        raise ValidationError(f"{payment.receipt_no} is already reversed.")
    if not reason.strip():
        raise ValidationError("Give a reason for the reversal.")
    payment.reversed_at = timezone.now()
    payment.reversed_by = user
    payment.reversal_reason = reason
    payment.save(update_fields=["reversed_at", "reversed_by", "reversal_reason"])
    record(
        "reversal",
        f"{payment.receipt_no} reversed ({payment.get_kind_display()} {payment.amount:,.2f}, {payment.student})",
        target=payment,
        actor=user,
        reason=reason,
    )
    return payment


@transaction.atomic
def waive(event, student, user, reason):
    _locked(student)
    if not reason.strip():
        raise ValidationError("Give a reason for the waiver.")
    if event.term_id != student.term_id:
        raise ValidationError("The event is in another term.")
    if Waiver.objects.filter(event=event, student=student, revoked_at__isnull=True).exists():
        raise ValidationError("This student's fines for the event are already waived.")
    waiver = Waiver.objects.create(event=event, student=student, reason=reason, created_by=user)
    record("waiver", f"Fines waived for {student} at {event}", target=waiver, actor=user, reason=reason)
    return waiver


@transaction.atomic
def revoke_waiver(waiver, user):
    _locked(waiver.student)
    waiver = Waiver.objects.select_for_update().get(pk=waiver.pk)
    if waiver.revoked_at:
        raise ValidationError("This waiver was already revoked.")
    waiver.revoked_at = timezone.now()
    waiver.revoked_by = user
    waiver.save(update_fields=["revoked_at", "revoked_by"])
    record("waiver_revoked", f"Waiver revoked for {waiver.student} at {waiver.event}", target=waiver, actor=user)
    return waiver
