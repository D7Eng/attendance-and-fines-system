import datetime

from django.contrib.auth.models import Group, User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from accounts import roles
from events.models import Attendance, Event, ScanImport
from roster.models import Student
from terms.models import Term


def make_user(username, role):
    user = User.objects.create_user(username)
    user.groups.add(Group.objects.get(name=role))
    return user


class EventViewTests(TestCase):
    def setUp(self):
        self.term = Term.objects.create(name="1st Sem", is_active=True)
        self.ana = Student.objects.create(
            term=self.term, student_no="1-001", last_name="Cruz", first_name="Ana", year_level=1
        )
        self.dan = Student.objects.create(
            term=self.term, student_no="2-001", last_name="Lim", first_name="Dan", year_level=2
        )
        self.gone = Student.objects.create(
            term=self.term,
            student_no="1-099",
            last_name="Gone",
            first_name="Ed",
            year_level=1,
            status=Student.NOT_ENROLLED,
        )
        self.client.force_login(make_user("o", roles.OFFICER))

    def test_create_event_for_first_years(self):
        response = self.client.post(
            reverse("events:event_add"),
            {"term": self.term.pk, "name": "Orientation", "date": "2026-11-05", "has_am": "on", "year_levels": ["1"]},
        )
        event = Event.objects.get()
        self.assertRedirects(response, reverse("events:attendance", args=[event.pk]))
        self.assertEqual(event.year_levels, [1])
        self.assertEqual(event.mark_fields, ["am_in", "am_out"])
        self.assertEqual(list(event.expected_students()), [self.ana])

    def test_event_needs_a_session(self):
        response = self.client.post(
            reverse("events:event_add"), {"term": self.term.pk, "name": "X", "date": "2026-11-05"}
        )
        self.assertContains(response, "Pick at least one session")

    def test_attendance_grid_saves_marks(self):
        event = Event.objects.create(term=self.term, name="Assembly", date=datetime.date(2026, 11, 5), has_pm=True)
        url = reverse("events:attendance", args=[event.pk])
        response = self.client.get(url)
        self.assertContains(response, "Cruz, Ana")
        self.assertNotContains(response, "Gone, Ed")  # not enrolled: not expected
        self.client.post(url, {"shown": [self.ana.pk], f"am_in-{self.ana.pk}": "on", f"pm_uniform-{self.ana.pk}": "on"})
        row = Attendance.objects.get(student=self.ana)
        self.assertEqual((row.am_in, row.am_out, row.pm_uniform), (True, False, True))
        self.assertEqual(row.missing_marks(), 3)
        self.assertEqual(row.uniform_violations(), 1)
        # Unchecking in the grid is allowed (manual corrections).
        self.client.post(url, {"shown": [self.ana.pk]})
        row.refresh_from_db()
        self.assertFalse(row.am_in)

    def test_scan_upload_flow(self):
        event = Event.objects.create(term=self.term, name="Assembly", date=datetime.date(2026, 11, 5))
        response = self.client.post(
            reverse("events:scan_upload", args=[event.pk]),
            {"file": SimpleUploadedFile("s.csv", b"Code,Timestamp\n1-001,2026-11-05 07:58\n"), "mode": "auto"},
        )
        imp = ScanImport.objects.get()
        self.assertRedirects(response, reverse("events:scan_preview", args=[imp.pk]))
        response = self.client.post(reverse("events:scan_apply", args=[imp.pk]), follow=True)
        self.assertContains(response, "1 mark added")
        self.assertTrue(Attendance.objects.get(student=self.ana).am_in)

    def test_event_with_attendance_is_not_deleted(self):
        event = Event.objects.create(term=self.term, name="Assembly", date=datetime.date(2026, 11, 5))
        Attendance.objects.create(event=event, student=self.ana, am_in=True)
        self.client.post(reverse("events:event_delete", args=[event.pk]))
        self.assertTrue(Event.objects.filter(pk=event.pk).exists())

    def test_students_cannot_open_events(self):
        self.client.force_login(make_user("s", roles.STUDENT))
        self.assertEqual(self.client.get(reverse("events:event_list")).status_code, 403)
