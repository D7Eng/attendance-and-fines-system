import datetime
from decimal import Decimal

from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q

MONEY = {"max_digits": 10, "decimal_places": 2, "validators": [MinValueValidator(Decimal("0"))]}


class TermQuerySet(models.QuerySet):
    def active(self):
        return self.filter(is_active=True).first()


class Term(models.Model):
    """One school term. All rates live here so each term keeps its own rules.

    Fine amounts are per missing IN or OUT mark; a uniform violation is
    charged one absence plus the uniform extra.
    """

    name = models.CharField(max_length=100, unique=True, help_text="e.g. 1st Semester 2026-2027")
    start_date = models.DateField(null=True, blank=True)
    end_date = models.DateField(null=True, blank=True)
    is_active = models.BooleanField(default=False)

    absence_fine_regular = models.DecimalField(default=Decimal("25.00"), **MONEY)
    absence_fine_officer = models.DecimalField(default=Decimal("50.00"), **MONEY)
    uniform_extra_regular = models.DecimalField(default=Decimal("75.00"), **MONEY)
    uniform_extra_officer = models.DecimalField(default=Decimal("50.00"), **MONEY)

    weekly_dues = models.DecimalField(
        default=Decimal("15.00"), help_text="Default weekly dues when no dues rate matches.", **MONEY
    )
    dues_weeks = models.PositiveSmallIntegerField(default=18)
    am_pm_cutoff = models.TimeField(default=datetime.time(12, 30))

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = TermQuerySet.as_manager()

    class Meta:
        ordering = ["-start_date", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["is_active"], condition=Q(is_active=True), name="one_active_term"),
        ]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if self.is_active:
            Term.objects.filter(is_active=True).exclude(pk=self.pk).update(is_active=False)
        super().save(*args, **kwargs)

    def absence_fine_for(self, student):
        return self.absence_fine_officer if student.is_officer else self.absence_fine_regular

    def uniform_fine_for(self, student):
        """Total charge for a uniform violation: one absence plus the extra."""
        extra = self.uniform_extra_officer if student.is_officer else self.uniform_extra_regular
        return self.absence_fine_for(student) + extra

    def weekly_dues_for(self, student, rates=None):
        """Weekly dues for a student: the most specific matching rate wins.

        Pass the term's rates as a list to avoid a query per student.
        """
        best = None
        for rate in self.dues_rates.all() if rates is None else rates:
            if rate.matches(student) and (best is None or rate.specificity > best.specificity):
                best = rate
        return best.weekly_amount if best else self.weekly_dues

    def total_dues_for(self, student, rates=None):
        return self.weekly_dues_for(student, rates) * self.dues_weeks


class DuesRate(models.Model):
    """Weekly dues override for part of the roster, e.g. officers or one section.

    Blank criteria match everyone. When several rates match a student, the
    one with the most criteria set wins.
    """

    OFFICER_ANY = ""
    OFFICER_YES = "yes"
    OFFICER_NO = "no"
    OFFICER_CHOICES = [(OFFICER_ANY, "Any"), (OFFICER_YES, "Officers only"), (OFFICER_NO, "Non-officers only")]

    term = models.ForeignKey(Term, on_delete=models.CASCADE, related_name="dues_rates")
    label = models.CharField(max_length=100, help_text="e.g. Officers")
    officer = models.CharField(max_length=3, choices=OFFICER_CHOICES, blank=True, default=OFFICER_ANY)
    year_level = models.PositiveSmallIntegerField(null=True, blank=True)
    group = models.CharField(max_length=50, blank=True, help_text="Section or block name; blank for any.")
    weekly_amount = models.DecimalField(**MONEY)

    class Meta:
        ordering = ["term", "label"]
        constraints = [
            models.UniqueConstraint(
                fields=["term", "officer", "year_level", "group"], name="unique_dues_rate_criteria"
            ),
        ]

    def __str__(self):
        return f"{self.label}: {self.weekly_amount}/week"

    @property
    def specificity(self):
        return sum([bool(self.officer), self.year_level is not None, bool(self.group)])

    def matches(self, student):
        if self.officer == self.OFFICER_YES and not student.is_officer:
            return False
        if self.officer == self.OFFICER_NO and student.is_officer:
            return False
        if self.year_level is not None and student.year_level != self.year_level:
            return False
        if self.group and student.group.casefold() != self.group.casefold():
            return False
        return True
