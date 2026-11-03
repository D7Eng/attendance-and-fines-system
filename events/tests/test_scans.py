import datetime

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase

from events import scans
from events.models import Attendance, Event, ScanImport
from roster.importer import RosterFileError
from roster.models import Student
from terms.models import Term


def csv_file(text, name="scans.csv"):
    return SimpleUploadedFile(name, text.encode("utf-8"))


class ParseTests(TestCase):
    def test_timestamp_forms(self):
        for text in ["2026-11-05 07:58:12", "11/05/2026 7:58 AM", "2026-11-05T07:58", "Nov 05, 2026 07:58 am"]:
            day, when = scans.parse_when(text)
            self.assertEqual(day, datetime.date(2026, 11, 5), text)
            self.assertEqual(when, datetime.time(7, 58, when.second), text)
        self.assertEqual(
            scans.parse_when("", "2026-11-05", "1:05 PM"), (datetime.date(2026, 11, 5), datetime.time(13, 5))
        )
        with self.assertRaises(ValueError):
            scans.parse_when("yesterday")

    def test_type_words(self):
        self.assertEqual(scans.parse_type("Time In"), "in")
        self.assertEqual(scans.parse_type("OUT"), "out")
        self.assertIsNone(scans.parse_type("Present"))


class ScanImportTests(TestCase):
    def setUp(self):
        self.term = Term.objects.create(name="1st Sem", is_active=True)
        self.user = User.objects.create_user("officer")
        self.event = Event.objects.create(
            term=self.term, name="Assembly", date=datetime.date(2026, 11, 5), has_am=True, has_pm=True
        )

        def add(no, last, first, **kw):
            return Student.objects.create(
                term=self.term, student_no=no, last_name=last, first_name=first, year_level=1, **kw
            )

        self.ana = add("2026-0001", "Cruz", "Ana")
        self.ben = add("2026-0002", "Reyes", "Ben")
        self.carla = add("2026-0003", "Santos", "Carla", middle_name="Diaz")

    def preview(self, text, mode=ScanImport.AUTO, name="scans.csv"):
        return scans.build_preview(self.event, csv_file(text, name), self.user, mode)

    def test_auto_marks_from_times(self):
        imp = self.preview(
            "Content,Timestamp\n"
            "2026-0001,2026-11-05 07:55\n"  # AM in
            "2026-0001,2026-11-05 12:01\n"  # AM out (before 12:30 cutoff)
            "2026-0001,2026-11-05 12:45\n"  # PM in
            "2026-0002|REYES BEN,2026-11-05 08:10\n"  # AM in, code carries name
            "Santos Carla,2026-11-05 08:15\n"  # name only: review
            "9999-9999,2026-11-05 08:20\n"  # unmatched
            "2026-0002,2026-11-04 08:20\n"  # wrong day
        )
        by_line = {r["line"]: r for r in imp.rows}
        self.assertEqual([by_line[n]["mark"] for n in (2, 3, 4, 5)], ["am_in", "am_out", "pm_in", "am_in"])
        self.assertEqual(by_line[6]["kind"], "review")
        self.assertEqual(by_line[7]["kind"], "unmatched")
        self.assertEqual(by_line[8]["kind"], "error")
        self.assertEqual(imp.counts, {"matched": 4, "already": 0, "review": 1, "unmatched": 1, "error": 1})
        self.assertFalse(Attendance.objects.exists())

        added = scans.apply_import(imp, self.user, accepted_lines=[6])
        self.assertEqual(added, 5)
        ana = Attendance.objects.get(student=self.ana)
        self.assertEqual((ana.am_in, ana.am_out, ana.pm_in, ana.pm_out), (True, True, True, False))
        self.assertEqual(ana.scan_times, {"am_in": "07:55", "am_out": "12:01", "pm_in": "12:45"})
        self.assertTrue(Attendance.objects.get(student=self.carla).am_in)

    def test_name_match_ignores_order_accents_and_punctuation(self):
        Student.objects.create(
            term=self.term, student_no="2026-0009", last_name="Peña", first_name="José", year_level=1
        )
        imp = self.preview("Name,Time\njose pena,08:00\n")
        self.assertEqual(imp.rows[0]["student_label"], "2026-0009 Peña, José")

    def test_review_rows_need_acceptance(self):
        imp = self.preview('Name,Time\n"Santos, Carla Diaz",08:00\n')
        self.assertEqual(imp.rows[0]["kind"], "review")
        self.assertEqual(scans.apply_import(imp, self.user), 0)
        self.assertFalse(Attendance.objects.exists())

    def test_type_column_and_fixed_mode(self):
        imp = self.preview("Student No.,Time,Type\n2026-0001,13:00,IN\n2026-0001,16:00,Time out\n")
        self.assertEqual([r["mark"] for r in imp.rows], ["pm_in", "pm_out"])
        imp = self.preview("Student No.\n2026-0002\n", mode="am_out", name="other.csv")
        self.assertEqual(imp.rows[0]["mark"], "am_out")

    def test_never_removes_marks_and_keeps_earliest_in(self):
        Attendance.objects.create(
            event=self.event, student=self.ana, am_in=True, am_out=True, scan_times={"am_in": "07:30"}
        )
        imp = self.preview("Student No.,Timestamp\n2026-0001,2026-11-05 07:50\n")
        self.assertEqual(imp.rows[0]["kind"], "already")
        self.assertEqual(scans.apply_import(imp, self.user), 0)
        ana = Attendance.objects.get(student=self.ana)
        self.assertTrue(ana.am_out)
        self.assertEqual(ana.scan_times["am_in"], "07:30")

    def test_same_file_cannot_be_applied_twice(self):
        text = "Student No.,Timestamp\n2026-0001,2026-11-05 07:50\n"
        scans.apply_import(self.preview(text), self.user)
        second = self.preview(text)
        with self.assertRaisesMessage(RosterFileError, "already applied"):
            scans.apply_import(second, self.user)

    def test_session_not_in_event(self):
        self.event.has_pm = False
        self.event.save()
        imp = self.preview("Student No.,Timestamp\n2026-0001,2026-11-05 14:00\n")
        self.assertIn("no PM session", imp.rows[0]["errors"][0])

    def test_file_errors(self):
        with self.assertRaisesMessage(RosterFileError, "No header row"):
            self.preview("foo,bar\n1,2\n")
        with self.assertRaisesMessage(RosterFileError, "pick which mark"):
            self.preview("Student No.\n2026-0001\n")
