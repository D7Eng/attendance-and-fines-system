import datetime
from decimal import Decimal
from io import StringIO

from django.contrib.auth.models import Group, User
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from accounts import roles
from events.models import Attendance, Event
from finance import services
from reports.summary import term_summary
from roster.models import Student
from terms.models import Term

PAST = datetime.date(2026, 9, 1)


def make_user(username, role):
    user = User.objects.create_user(username)
    user.groups.add(Group.objects.get(name=role))
    return user


class ReportTests(TestCase):
    def setUp(self):
        self.term = Term.objects.create(name="1st Sem", is_active=True)
        self.treasurer = make_user("t", roles.TREASURER)
        self.ana = Student.objects.create(
            term=self.term, student_no="1-001", last_name="Cruz", first_name="Ana", year_level=1, group="A"
        )
        self.ben = Student.objects.create(
            term=self.term, student_no="1-002", last_name="Reyes", first_name="Ben", year_level=1, group="B"
        )
        self.dan = Student.objects.create(
            term=self.term, student_no="2-001", last_name="Lim", first_name="Dan", year_level=2, is_officer=True
        )
        self.event = Event.objects.create(term=self.term, name="Assembly", date=PAST, has_am=True, has_pm=True)
        Attendance.objects.create(event=self.event, student=self.ana, am_in=True, am_out=True, pm_in=True, pm_out=True)
        Attendance.objects.create(event=self.event, student=self.ben, am_in=True, am_out=True, pm_uniform=True)
        services.record_payment(self.ana, "100", self.treasurer)

    def test_term_summary(self):
        _, overall, by_year, events = term_summary(self.term)
        # Ben: 2 missing x 25 + 1 uniform x 100 = 150. Dan (officer): 4 missing x 50 = 200.
        self.assertEqual(overall.fines, Decimal("350"))
        self.assertEqual(by_year[1].fines, Decimal("150"))
        self.assertEqual(overall.dues, Decimal("810"))
        self.assertEqual(overall.paid, Decimal("100"))
        self.assertEqual(overall.outstanding, Decimal("170") + Decimal("420") + Decimal("470"))
        (assembly,) = events
        self.assertEqual((assembly.expected, assembly.complete, assembly.missing, assembly.uniform), (3, 1, 6, 1))

    def test_dashboard_hides_money_from_officers(self):
        self.client.force_login(make_user("o", roles.OFFICER))
        response = self.client.get(reverse("reports:dashboard"))
        self.assertContains(response, "Assembly")
        self.assertNotContains(response, "Outstanding")
        self.client.force_login(self.treasurer)
        self.assertContains(self.client.get(reverse("reports:dashboard")), "Outstanding")

    def test_balances_report_and_csv(self):
        self.client.force_login(self.treasurer)
        response = self.client.get(reverse("reports:balances"), {"year": 1, "show": "owing"})
        self.assertContains(response, "Reyes, Ben")
        self.assertNotContains(response, "Lim, Dan")
        csv = self.client.get(reverse("reports:balances"), {"format": "csv"}).content.decode("utf-8-sig")
        self.assertIn('1-002,"Reyes, Ben",1,B,,2,1,150.00,0.00,270.00,0.00,0.00,420.00', csv)

    def test_collections_report(self):
        self.client.force_login(self.treasurer)
        response = self.client.get(reverse("reports:collections"))
        self.assertContains(response, "OR-00001")
        self.assertEqual(response.context["net"], Decimal("100"))
        csv = self.client.get(reverse("reports:collections"), {"format": "csv"}).content.decode("utf-8-sig")
        self.assertIn("OR-00001", csv)

    def test_event_report_for_officer_has_no_money(self):
        self.client.force_login(make_user("o", roles.OFFICER))
        response = self.client.get(reverse("reports:event_report", args=[self.event.pk]))
        self.assertContains(response, "PM in, PM out")
        self.assertNotContains(response, "150.00")
        self.assertNotContains(response, "Cruz, Ana")  # complete

    def test_statement(self):
        self.client.force_login(self.treasurer)
        response = self.client.get(reverse("reports:statement", args=[self.ben.pk]))
        self.assertContains(response, "Statement of account")
        self.assertContains(response, "420.00")

    def test_finance_reports_are_closed_to_officers_and_students(self):
        for role in (roles.OFFICER, roles.STUDENT):
            self.client.force_login(make_user(f"u-{role}", role))
            for url in (
                reverse("reports:balances"),
                reverse("reports:collections"),
                reverse("reports:statement", args=[self.ana.pk]),
            ):
                self.assertEqual(self.client.get(url).status_code, 403, (role, url))

    def test_student_self_service_shows_own_terms_only(self):
        user = make_user("1-001", roles.STUDENT)
        Student.objects.filter(pk=self.ana.pk).update(user=user)
        old = Term.objects.create(name="Old term", start_date=datetime.date(2025, 6, 1))
        Student.objects.create(
            term=old, student_no="1-001", last_name="Cruz", first_name="Ana", year_level=1, user=user
        )
        self.client.force_login(user)
        response = self.client.get(reverse("me"))
        self.assertEqual(response.context["student"], self.ana)
        self.assertContains(response, "OR-00001")
        self.assertContains(response, "Old term")
        self.assertNotContains(response, "Reyes")
        response = self.client.get(reverse("me"), {"term": old.pk})
        self.assertEqual(response.context["student"].term, old)
        self.assertEqual(self.client.get(reverse("reports:dashboard")).status_code, 403)

    def test_fine_totals_command(self):
        out = StringIO()
        call_command("fine_totals", stdout=out)
        self.assertIn("150.00", out.getvalue())
        self.assertIn("350.00", out.getvalue())
