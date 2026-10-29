from decimal import Decimal

from django.test import TestCase

from roster.models import Student
from terms.models import DuesRate, Term


class TermRatesTests(TestCase):
    def setUp(self):
        self.term = Term.objects.create(name="1st Sem 2026-2027", is_active=True)
        self.member = Student(term=self.term, student_no="A1", year_level=1, group="A", is_officer=False)
        self.officer = Student(term=self.term, student_no="A2", year_level=1, group="A", is_officer=True)

    def test_default_fine_rules(self):
        self.assertEqual(self.term.absence_fine_for(self.member), Decimal("25"))
        self.assertEqual(self.term.absence_fine_for(self.officer), Decimal("50"))
        # Uniform violation = one absence charge + extra, 100 total for both.
        self.assertEqual(self.term.uniform_fine_for(self.member), Decimal("100"))
        self.assertEqual(self.term.uniform_fine_for(self.officer), Decimal("100"))

    def test_fine_rates_are_configurable(self):
        self.term.absence_fine_officer = Decimal("40")
        self.term.uniform_extra_officer = Decimal("60")
        self.assertEqual(self.term.absence_fine_for(self.officer), Decimal("40"))
        self.assertEqual(self.term.uniform_fine_for(self.officer), Decimal("100"))

    def test_default_dues(self):
        self.assertEqual(self.term.weekly_dues_for(self.member), Decimal("15"))
        self.assertEqual(self.term.total_dues_for(self.member), Decimal("270"))

    def test_dues_rate_for_officers(self):
        DuesRate.objects.create(
            term=self.term, label="Officers", officer=DuesRate.OFFICER_YES, weekly_amount=Decimal("20")
        )
        self.assertEqual(self.term.weekly_dues_for(self.officer), Decimal("20"))
        self.assertEqual(self.term.weekly_dues_for(self.member), Decimal("15"))
        self.assertEqual(self.term.total_dues_for(self.officer), Decimal("360"))

    def test_most_specific_dues_rate_wins(self):
        DuesRate.objects.create(term=self.term, label="1st year", year_level=1, weekly_amount=Decimal("10"))
        DuesRate.objects.create(
            term=self.term,
            label="1st year officers",
            year_level=1,
            officer=DuesRate.OFFICER_YES,
            weekly_amount=Decimal("12"),
        )
        DuesRate.objects.create(term=self.term, label="Block B", group="b", weekly_amount=Decimal("5"))
        self.assertEqual(self.term.weekly_dues_for(self.member), Decimal("10"))
        self.assertEqual(self.term.weekly_dues_for(self.officer), Decimal("12"))
        block_b = Student(term=self.term, student_no="B1", year_level=2, group="B")
        self.assertEqual(self.term.weekly_dues_for(block_b), Decimal("5"))

    def test_only_one_active_term(self):
        other = Term.objects.create(name="2nd Sem 2026-2027", is_active=True)
        self.term.refresh_from_db()
        self.assertFalse(self.term.is_active)
        self.assertEqual(Term.objects.active(), other)
