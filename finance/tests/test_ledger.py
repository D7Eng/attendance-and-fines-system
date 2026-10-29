import datetime
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.test import TestCase

from events.models import Attendance, Event
from finance import services
from finance.ledger import account_for, accounts_for
from finance.models import Payment
from roster.models import Student
from terms.models import DuesRate, Term

D = Decimal
PAST = datetime.date(2026, 9, 1)


class Base(TestCase):
    def setUp(self):
        self.term = Term.objects.create(name="1st Sem", is_active=True)
        self.user = User.objects.create_user("treasurer")
        self.ana = self.student("1-001", "Cruz")
        self.olga = self.student("1-002", "Ong", is_officer=True)

    def student(self, no, last, **kw):
        kw.setdefault("year_level", 1)
        return Student.objects.create(term=self.term, student_no=no, last_name=last, first_name="X", **kw)

    def event(self, **kw):
        kw.setdefault("date", PAST)
        return Event.objects.create(term=self.term, name=kw.pop("name", "Assembly"), **kw)


class FineTests(Base):
    def test_missing_marks_and_uniform(self):
        whole_day = self.event(has_am=True, has_pm=True)
        # Ana: AM complete with a uniform violation, PM IN only -> 1 missing mark.
        Attendance.objects.create(
            event=whole_day, student=self.ana, am_in=True, am_out=True, pm_in=True, am_uniform=True
        )
        # Olga (officer) never came: 4 missing marks at 50.
        acct = account_for(self.ana)
        self.assertEqual(acct.fines, D("25") + D("100"))
        self.assertEqual(acct.dues, D("270"))
        self.assertEqual(acct.balance, D("395"))
        self.assertEqual(account_for(self.olga).fines, D("200"))

    def test_officer_uniform_is_also_100(self):
        event = self.event()
        Attendance.objects.create(event=event, student=self.olga, am_in=True, am_out=True, am_uniform=True)
        self.assertEqual(account_for(self.olga).fines, D("100"))

    def test_configured_rates_apply(self):
        self.term.absence_fine_regular = D("30")
        self.term.save()
        self.event()
        self.assertEqual(account_for(self.ana).fines, D("60"))

    def test_future_events_other_years_and_not_enrolled(self):
        self.event(date=datetime.date.today() + datetime.timedelta(days=3))
        self.event(year_levels=[2])
        dropped = self.student("1-003", "Gone", status=Student.NOT_ENROLLED)
        self.assertEqual(account_for(self.ana).fines, D("0"))
        acct = account_for(dropped)
        self.assertEqual((acct.fines, acct.dues, acct.balance), (D("0"), D("0"), D("0")))

    def test_waiver_removes_the_event_fine(self):
        event = self.event()
        waiver = services.waive(event, self.ana, self.user, "Excused: medical")
        acct = account_for(self.ana)
        self.assertEqual((acct.fines, acct.waived), (D("0"), D("50")))
        with self.assertRaises(ValidationError):
            services.waive(event, self.ana, self.user, "again")
        services.revoke_waiver(waiver, self.user)
        self.assertEqual(account_for(self.ana).fines, D("50"))

    def test_group_dues_rate(self):
        DuesRate.objects.create(term=self.term, label="Officers", officer="yes", weekly_amount=D("10"))
        accounts = accounts_for(self.term)
        self.assertEqual(accounts[self.olga.pk].dues, D("180"))
        self.assertEqual(accounts[self.ana.pk].dues, D("270"))


class PaymentTests(Base):
    def test_payment_receipt_numbers_and_balance(self):
        p1 = services.record_payment(self.ana, "100", self.user)
        p2 = services.record_payment(self.ana, "70.50", self.user, method=Payment.GCASH, gcash_ref="1234 567 890123")
        self.assertEqual((p1.receipt_no, p2.receipt_no), ("OR-00001", "OR-00002"))
        self.assertEqual(p2.gcash_ref, "1234567890123")
        self.assertEqual(p2.balance_after, D("99.50"))
        self.assertEqual(account_for(self.ana).balance, D("99.50"))

    def test_overpayment_rejected(self):
        with self.assertRaisesMessage(ValidationError, "Overpayment rejected"):
            services.record_payment(self.ana, "270.01", self.user)
        services.record_payment(self.ana, "270", self.user)
        with self.assertRaises(ValidationError):
            services.record_payment(self.ana, "1", self.user)

    def test_gcash_needs_unique_reference_per_term(self):
        with self.assertRaisesMessage(ValidationError, "reference number"):
            services.record_payment(self.ana, "10", self.user, method=Payment.GCASH)
        services.record_payment(self.ana, "10", self.user, method=Payment.GCASH, gcash_ref="ABC123")
        with self.assertRaisesMessage(ValidationError, "already used"):
            services.record_payment(self.olga, "10", self.user, method=Payment.GCASH, gcash_ref="abc-123")
        # Another term may reuse it.
        other = Term.objects.create(name="2nd Sem")
        bob = Student.objects.create(term=other, student_no="9", last_name="B", first_name="B", year_level=1)
        services.record_payment(bob, "10", self.user, method=Payment.GCASH, gcash_ref="ABC123")

    def test_reversal_keeps_record_and_frees_reference(self):
        wrong = services.record_payment(self.ana, "50", self.user, method=Payment.GCASH, gcash_ref="REF1")
        services.reverse_payment(wrong, self.user, "Wrong student")
        wrong.refresh_from_db()
        self.assertTrue(wrong.is_reversed)
        self.assertEqual(account_for(self.ana).paid, D("0"))
        right = services.record_payment(self.olga, "50", self.user, method=Payment.GCASH, gcash_ref="REF1")
        self.assertEqual(right.receipt_no, "OR-00002")
        with self.assertRaises(ValidationError):
            services.reverse_payment(wrong, self.user, "again")
        with self.assertRaisesMessage(ValidationError, "reason"):
            services.reverse_payment(right, self.user, " ")

    def test_refund_only_up_to_credit(self):
        event = self.event()
        services.record_payment(self.ana, "320", self.user)  # 270 dues + 50 fine
        with self.assertRaisesMessage(ValidationError, "at most"):
            services.record_refund(self.ana, "1", self.user, "nothing to refund")
        services.waive(event, self.ana, self.user, "Excused")
        self.assertEqual(account_for(self.ana).credit, D("50"))
        refund = services.record_refund(self.ana, "50", self.user, "Waived after paying")
        self.assertEqual(refund.receipt_no, "RF-00001")
        acct = account_for(self.ana)
        self.assertEqual((acct.balance, acct.refunded), (D("0"), D("50")))

    def test_dropped_student_payments_become_credit(self):
        services.record_payment(self.ana, "100", self.user)
        Student.objects.filter(pk=self.ana.pk).update(status=Student.NOT_ENROLLED)
        self.ana.refresh_from_db()
        self.assertEqual(account_for(self.ana).credit, D("100"))
