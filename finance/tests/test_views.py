import datetime

from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse

from accounts import roles
from events.models import Event
from finance import services
from finance.models import Payment, Waiver
from roster.models import Student
from terms.models import Term


def make_user(username, role):
    user = User.objects.create_user(username)
    user.groups.add(Group.objects.get(name=role))
    return user


class FinanceViewTests(TestCase):
    def setUp(self):
        self.term = Term.objects.create(name="1st Sem", is_active=True)
        self.ana = Student.objects.create(
            term=self.term, student_no="1-001", last_name="Cruz", first_name="Ana", year_level=1
        )
        self.treasurer = make_user("t", roles.TREASURER)
        self.client.force_login(self.treasurer)

    def test_officer_has_no_access_to_payments(self):
        self.client.force_login(make_user("o", roles.OFFICER))
        for url in [
            reverse("finance:payment_list"),
            reverse("finance:account", args=[self.ana.pk]),
            reverse("finance:pay", args=[self.ana.pk]),
        ]:
            self.assertEqual(self.client.get(url).status_code, 403, url)

    def test_admin_can_view_but_not_take_payments(self):
        self.client.force_login(make_user("a", roles.ADMIN))
        self.assertEqual(self.client.get(reverse("finance:account", args=[self.ana.pk])).status_code, 200)
        self.assertEqual(self.client.get(reverse("finance:pay", args=[self.ana.pk])).status_code, 403)

    def test_find_student_and_pay(self):
        response = self.client.get(reverse("finance:payment_list"), {"find": "cruz"})
        self.assertRedirects(response, reverse("finance:account", args=[self.ana.pk]))
        response = self.client.post(reverse("finance:pay", args=[self.ana.pk]), {"amount": "100", "method": "cash"})
        payment = Payment.objects.get()
        self.assertRedirects(response, reverse("finance:receipt", args=[payment.pk]))
        receipt = self.client.get(reverse("finance:receipt", args=[payment.pk]))
        self.assertContains(receipt, "OR-00001")
        self.assertContains(receipt, "170.00")  # balance after

    def test_overpayment_shows_error(self):
        response = self.client.post(reverse("finance:pay", args=[self.ana.pk]), {"amount": "500", "method": "cash"})
        self.assertContains(response, "Overpayment rejected")
        self.assertFalse(Payment.objects.exists())

    def test_reverse_and_refund_pages(self):
        payment = services.record_payment(self.ana, "270", self.treasurer)
        event = Event.objects.create(term=self.term, name="Assembly", date=datetime.date(2026, 9, 1))
        self.client.post(reverse("finance:waive", args=[self.ana.pk, event.pk]), {"reason": "Excused"})
        self.assertTrue(Waiver.objects.filter(student=self.ana).exists())
        self.client.post(reverse("finance:reverse", args=[payment.pk]), {"reason": "Duplicate entry"})
        payment.refresh_from_db()
        self.assertEqual(payment.reversal_reason, "Duplicate entry")
        response = self.client.get(reverse("finance:account", args=[self.ana.pk]))
        self.assertContains(response, "Reversed")
        self.assertContains(response, "waived")

    def test_student_sees_own_receipt_only(self):
        payment = services.record_payment(self.ana, "10", self.treasurer)
        user = make_user("1-001", roles.STUDENT)
        other = make_user("1-002", roles.STUDENT)
        Student.objects.filter(pk=self.ana.pk).update(user=user)
        self.client.force_login(other)
        self.assertEqual(self.client.get(reverse("finance:receipt", args=[payment.pk])).status_code, 403)
        self.client.force_login(user)
        self.assertContains(self.client.get(reverse("finance:receipt", args=[payment.pk])), "OR-00001")
