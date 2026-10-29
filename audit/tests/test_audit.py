import datetime
import tempfile
from decimal import Decimal
from pathlib import Path

from cryptography.fernet import Fernet
from django.contrib.auth.models import Group, User
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings
from django.urls import URLPattern, URLResolver, get_resolver, reverse

from accounts import roles
from audit import backup
from audit.models import AuditLog
from events.models import Event
from finance import services
from finance.models import Payment
from roster.models import Student
from terms.models import DuesRate, Term


def make_user(username, role):
    user = User.objects.create_user(username, password="pw-123456!")
    user.groups.add(Group.objects.get(name=role))
    return user


class AuditTests(TestCase):
    def setUp(self):
        self.term = Term.objects.create(name="1st Sem", is_active=True)
        self.ana = Student.objects.create(
            term=self.term, student_no="1-001", last_name="Cruz", first_name="Ana", year_level=1
        )
        self.treasurer = make_user("t", roles.TREASURER)

    def test_money_changes_are_logged(self):
        payment = services.record_payment(self.ana, "50", self.treasurer, method=Payment.GCASH, gcash_ref="R1")
        services.reverse_payment(payment, self.treasurer, "Wrong amount")
        actions = list(AuditLog.objects.order_by("id").values_list("action", "actor_name"))
        self.assertEqual(actions, [("payment", "t"), ("reversal", "t")])
        entry = AuditLog.objects.get(action="reversal")
        self.assertEqual(entry.details, {"reason": "Wrong amount"})
        self.assertEqual(entry.target_id, str(payment.pk))

    def test_entries_cannot_be_changed_or_deleted(self):
        services.record_payment(self.ana, "50", self.treasurer)
        entry = AuditLog.objects.get()
        entry.summary = "nothing happened"
        with self.assertRaises(ValueError):
            entry.save()
        with self.assertRaises(ValueError):
            entry.delete()

    def test_attendance_edit_and_login_are_logged(self):
        officer = make_user("o", roles.OFFICER)
        self.client.post(reverse("login"), {"username": "o", "password": "pw-123456!"}, REMOTE_ADDR="10.0.0.5")
        login = AuditLog.objects.get(action="login")
        self.assertEqual((login.actor, login.ip), (officer, "10.0.0.5"))
        event = Event.objects.create(term=self.term, name="Assembly", date=datetime.date(2026, 9, 1))
        self.client.post(
            reverse("events:attendance", args=[event.pk]), {"shown": [self.ana.pk], f"am_in-{self.ana.pk}": "on"}
        )
        entry = AuditLog.objects.get(action="attendance_changed")
        self.assertEqual(entry.details["rows"], [{"student": "1-001", "changes": {"am_in": [False, True]}}])
        self.client.post(reverse("login"), {"username": "o", "password": "wrong"})
        self.assertTrue(AuditLog.objects.filter(action="login_failed").exists())

    def test_audit_page_access(self):
        services.record_payment(self.ana, "50", self.treasurer)
        self.client.force_login(self.treasurer)
        self.assertContains(self.client.get(reverse("audit:log")), "OR-00001")
        self.client.force_login(make_user("o", roles.OFFICER))
        self.assertEqual(self.client.get(reverse("audit:log")).status_code, 403)


class SettingsScreenTests(TestCase):
    def setUp(self):
        self.term = Term.objects.create(name="1st Sem", is_active=True)
        self.client.force_login(make_user("t", roles.TREASURER))
        self.url = reverse("terms:term_edit", args=[self.term.pk])

    def data(self, **overrides):
        data = {
            "name": "1st Sem",
            "start_date": "",
            "end_date": "",
            "is_active": "on",
            "absence_fine_regular": "25.00",
            "absence_fine_officer": "50.00",
            "uniform_extra_regular": "75.00",
            "uniform_extra_officer": "50.00",
            "weekly_dues": "15.00",
            "dues_weeks": "18",
            "am_pm_cutoff": "12:30",
            "rates-TOTAL_FORMS": "2",
            "rates-INITIAL_FORMS": "0",
            "rates-MIN_NUM_FORMS": "0",
            "rates-MAX_NUM_FORMS": "1000",
        }
        data.update(overrides)
        return data

    def test_edit_rates_and_add_group_dues(self):
        response = self.client.post(
            self.url,
            self.data(
                absence_fine_regular="30.00",
                **{
                    "rates-0-label": "Officers",
                    "rates-0-officer": "yes",
                    "rates-0-year_level": "",
                    "rates-0-group": "",
                    "rates-0-weekly_amount": "10.00",
                },
            ),
        )
        self.assertRedirects(response, reverse("terms:term_list"))
        self.term.refresh_from_db()
        self.assertEqual(self.term.absence_fine_regular, Decimal("30.00"))
        self.assertEqual(DuesRate.objects.get().weekly_amount, Decimal("10.00"))
        entry = AuditLog.objects.get(action="settings_changed")
        self.assertEqual(entry.details["changes"], {"absence_fine_regular": ["25.00", "30.00"]})
        self.assertEqual(entry.details["rates"]["added"][0]["label"], "Officers")
        self.assertContains(self.client.get(reverse("terms:term_list")), "Officers: 10.00/wk")

    def test_duplicate_dues_criteria_rejected(self):
        rate = {"officer": "yes", "year_level": "", "group": "", "weekly_amount": "10"}
        data = self.data(**{f"rates-{i}-{k}": v for i in (0, 1) for k, v in rate.items()})
        data.update({"rates-0-label": "A", "rates-1-label": "B"})
        self.assertContains(self.client.post(self.url, data), "same officer, year and group")

    def test_create_term(self):
        response = self.client.post(reverse("terms:term_add"), self.data(name="2nd Sem", is_active=""))
        self.assertRedirects(response, reverse("terms:term_list"))
        self.assertTrue(Term.objects.filter(name="2nd Sem", dues_weeks=18).exists())

    def test_officers_cannot_change_settings(self):
        self.client.force_login(make_user("o", roles.OFFICER))
        self.assertEqual(self.client.get(self.url).status_code, 403)


class BackupTests(TestCase):
    def setUp(self):
        self.key = Fernet.generate_key().decode()
        self.term = Term.objects.create(name="1st Sem", is_active=True)
        Student.objects.create(term=self.term, student_no="1-001", last_name="Cruz", first_name="Ana", year_level=1)

    def test_backup_is_encrypted_and_restorable(self):
        with tempfile.TemporaryDirectory() as tmp, override_settings(DUESTRACK_BACKUP_KEY=self.key):
            call_command("backup", dir=tmp, stdout=open("/dev/null", "w"))
            (path,) = Path(tmp).glob("duestrack-*.json.gz.enc")
            raw = path.read_bytes()
            self.assertNotIn(b"Cruz", raw)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            fixture = backup.read_backup(path)
            self.assertIn(b'"student_no": "1-001"', fixture)
            with self.assertRaises(CommandError):
                backup.read_backup(path, key=Fernet.generate_key())
            # Restore into an empty database.
            Student.objects.all().delete()
            call_command("restore_backup", str(path), load=True, stdout=open("/dev/null", "w"))
            self.assertTrue(Student.objects.filter(student_no="1-001").exists())

    def test_backup_needs_a_key(self):
        with override_settings(DUESTRACK_BACKUP_KEY=""), self.assertRaisesMessage(CommandError, "DUESTRACK_BACKUP_KEY"):
            call_command("backup")


class NoPublicPagesTests(TestCase):
    PUBLIC = {"login", "privacy", "logout"}

    def test_every_page_needs_login(self):
        def walk(patterns, prefix=""):
            for p in patterns:
                if isinstance(p, URLResolver):
                    yield from walk(p.url_patterns, prefix + str(p.pattern))
                elif isinstance(p, URLPattern):
                    yield p.name, prefix + str(p.pattern)

        checked = 0
        for name, route in walk(get_resolver().url_patterns):
            if route.startswith("admin/") or name in self.PUBLIC:
                continue
            path = "/" + route.replace("<int:pk>", "1").replace("<int:event_pk>", "1")
            response = self.client.get(path)
            if response.status_code == 405:  # POST-only actions
                response = self.client.post(path)
            self.assertEqual(response.status_code, 302, path)
            self.assertTrue(response["Location"].startswith(reverse("login")), path)
            checked += 1
        self.assertGreater(checked, 25)
