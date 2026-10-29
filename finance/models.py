from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q

from events.models import Event
from roster.models import Student
from terms.models import Term


class Waiver(models.Model):
    """Excuses one student from all fines of one event. Revoking keeps the record."""

    event = models.ForeignKey(Event, on_delete=models.PROTECT, related_name="waivers")
    student = models.ForeignKey(Student, on_delete=models.PROTECT, related_name="waivers")
    reason = models.CharField(max_length=255)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["event", "student"], condition=Q(revoked_at__isnull=True), name="one_active_waiver"
            )
        ]

    def __str__(self):
        return f"Waiver: {self.student} at {self.event}"


class Counter(models.Model):
    """Named sequences for receipt numbers."""

    name = models.CharField(max_length=20, unique=True)
    value = models.PositiveIntegerField(default=0)

    @classmethod
    def next(cls, name):
        """Next value of a sequence; call inside a transaction."""
        counter, _ = cls.objects.select_for_update().get_or_create(name=name)
        counter.value += 1
        counter.save(update_fields=["value"])
        return counter.value


class Payment(models.Model):
    """Money in (a payment) or out (a refund). Never deleted; a mistake is reversed instead."""

    PAYMENT = "payment"
    REFUND = "refund"
    KIND_CHOICES = [(PAYMENT, "Payment"), (REFUND, "Refund")]

    CASH = "cash"
    GCASH = "gcash"
    METHOD_CHOICES = [(CASH, "Cash"), (GCASH, "GCash")]

    PREFIX = {PAYMENT: "OR", REFUND: "RF"}

    term = models.ForeignKey(Term, on_delete=models.PROTECT, related_name="payments")
    student = models.ForeignKey(Student, on_delete=models.PROTECT, related_name="payments")
    kind = models.CharField(max_length=10, choices=KIND_CHOICES, default=PAYMENT)
    amount = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))])
    method = models.CharField(max_length=10, choices=METHOD_CHOICES, default=CASH)
    gcash_ref = models.CharField("GCash reference no.", max_length=40, blank=True)
    receipt_no = models.CharField(max_length=20, unique=True)
    note = models.CharField(max_length=255, blank=True)
    balance_after = models.DecimalField(max_digits=10, decimal_places=2)
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    recorded_at = models.DateTimeField(auto_now_add=True)

    reversed_at = models.DateTimeField(null=True, blank=True)
    reversed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    reversal_reason = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["-recorded_at", "-id"]
        constraints = [
            # A GCash transfer can pay only once per term; a reversed entry frees its reference.
            models.UniqueConstraint(
                fields=["term", "gcash_ref"],
                condition=~Q(gcash_ref="") & Q(reversed_at__isnull=True),
                name="unique_active_gcash_ref_per_term",
            ),
        ]
        indexes = [models.Index(fields=["term", "recorded_at"])]

    def __str__(self):
        return f"{self.receipt_no} {self.student} {self.amount}"

    @property
    def is_reversed(self):
        return self.reversed_at is not None

    @property
    def signed_amount(self):
        """What this entry takes off the balance."""
        return self.amount if self.kind == self.PAYMENT else -self.amount
