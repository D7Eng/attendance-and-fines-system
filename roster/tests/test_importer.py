import io

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from openpyxl import Workbook

from roster import importer
from roster.models import RosterImport, Student
from terms.models import Term


def csv_file(text, name="roster.csv"):
    return SimpleUploadedFile(name, text.encode("utf-8"))


def xlsx_file(rows, name="roster.xlsx"):
    wb = Workbook()
    ws = wb.active
    for row in rows:
        ws.append(row)
    buf = io.BytesIO()
    wb.save(buf)
    return SimpleUploadedFile(name, buf.getvalue())


class ParsingTests(TestCase):
    def test_year_level_forms(self):
        for text, level in [("1", 1), ("1st", 1), ("1st Year", 1), ("Second Year", 2), ("III", 3), ("4th yr", 4)]:
            self.assertEqual(importer.parse_year_level(text), level, text)
        with self.assertRaises(ValueError):
            importer.parse_year_level("7")

    def test_officer_column(self):
        self.assertTrue(importer.parse_officer("Yes"))
        self.assertTrue(importer.parse_officer("President"))
        self.assertFalse(importer.parse_officer(""))
        self.assertFalse(importer.parse_officer("Member"))

    def test_status_column(self):
        self.assertEqual(importer.parse_status(""), Student.ENROLLED)
        self.assertEqual(importer.parse_status("Not Enrolled"), Student.NOT_ENROLLED)
        self.assertEqual(importer.parse_status("Dropped"), Student.NOT_ENROLLED)
        with self.assertRaises(ValueError):
            importer.parse_status("maybe")

    def test_header_aliases(self):
        mapping = importer.map_columns(["Student No.", "Surname", "Given Name", "M.I.", "Yr Level", "Section"])
        self.assertEqual(
            mapping, {"student_no": 0, "last_name": 1, "first_name": 2, "middle_name": 3, "year_level": 4, "group": 5}
        )


class PreviewAndApplyTests(TestCase):
    def setUp(self):
        self.term = Term.objects.create(name="1st Sem", is_active=True)
        self.user = User.objects.create_user("treasurer")
        Student.objects.create(
            term=self.term, student_no="2026-0001", last_name="Cruz", first_name="Ana", year_level=1, group="A"
        )
        Student.objects.create(
            term=self.term, student_no="2026-0002", last_name="Reyes", first_name="Ben", year_level=1, group="A"
        )
        Student.objects.create(
            term=self.term, student_no="2026-0099", last_name="Keep", first_name="Me", year_level=1, group="A"
        )

    def preview(self, f, **kwargs):
        return importer.build_preview(self.term, f, self.user, **kwargs)

    def test_classifies_rows(self):
        f = csv_file(
            "Student No.,Last Name,First Name,Middle Name,Year,Section,Officer,Status\n"
            "2026-0001,Cruz,Ana,,1,A,,Enrolled\n"  # unchanged
            "2026-0002,Reyes,Ben,Santos,1,B,President,\n"  # changed: middle name, group, officer
            "2026-0003,Lim,Carla,,1st Year,A,no,\n"  # new
            ",Nobody,Here,,1,A,,\n"  # error: no student no
            "2026-0004,Tan,,,1,A,,\n"  # error: no first name
            "2026-0003,Lim,Carla,,1,A,,\n"  # error: duplicate
        )
        imp = self.preview(f)
        self.assertEqual((imp.new_count, imp.changed_count, imp.unchanged_count, imp.error_count), (1, 1, 1, 3))
        kinds = [r["kind"] for r in imp.rows]
        self.assertEqual(kinds, ["unchanged", "changed", "new", "error", "error", "error"])
        self.assertEqual([r["line"] for r in imp.rows], [2, 3, 4, 5, 6, 7])
        self.assertEqual(
            imp.rows[1]["changes"],
            {"middle_name": ["", "Santos"], "group": ["A", "B"], "is_officer": [False, True]},
        )
        self.assertIn("repeated", imp.rows[5]["errors"][0])
        # Preview writes nothing to the roster.
        self.assertEqual(Student.objects.count(), 3)
        self.assertEqual(importer.missing_from_file(imp).get().student_no, "2026-0099")

    def test_apply_writes_new_and_changed_only(self):
        f = csv_file(
            "Student No.,Last Name,First Name,Year,Section,Officer\n"
            "2026-0002,Reyes,Ben,1,B,yes\n"
            "2026-0003,Lim,Carla,1,A,\n"
            "2026-0005,Bad,Row,9,A,\n"
        )
        imp = self.preview(f)
        created, updated = importer.apply_import(imp)
        self.assertEqual((created, updated), (1, 1))
        ben = Student.objects.get(student_no="2026-0002")
        self.assertEqual((ben.group, ben.is_officer), ("B", True))
        self.assertTrue(Student.objects.filter(student_no="2026-0003").exists())
        self.assertFalse(Student.objects.filter(student_no="2026-0005").exists())
        # Students missing from the file are never removed.
        self.assertTrue(Student.objects.filter(student_no="2026-0099").exists())
        imp.refresh_from_db()
        self.assertEqual(imp.status, RosterImport.APPLIED)
        with self.assertRaises(importer.RosterFileError):
            importer.apply_import(imp)

    def test_matches_by_student_no_only(self):
        # Same name, different number: a new student, not a change.
        imp = self.preview(csv_file("Student No.,Last Name,First Name,Year\n2026-1111,Cruz,Ana,1\n"))
        self.assertEqual(imp.rows[0]["kind"], "new")

    def test_student_no_match_ignores_case_and_spaces(self):
        Student.objects.create(term=self.term, student_no="ABC-1", last_name="X", first_name="Y", year_level=2)
        imp = self.preview(csv_file("Student No.,Last Name,First Name,Year\n abc-1 ,X,Y,2\n"))
        self.assertEqual(imp.rows[0]["kind"], "unchanged")

    def test_xlsx_with_title_rows_full_name_and_default_year(self):
        f = xlsx_file(
            [
                ["1st Year Roster"],
                [],
                ["Student No", "Name", "Section"],
                [20260007, "Dela Cruz, Juan P.", "C"],
                [20260008, "No Comma Name", "C"],
            ]
        )
        imp = self.preview(f, default_year_level=1)
        first, second = imp.rows
        self.assertEqual(first["kind"], "new")
        self.assertEqual(first["line"], 4)
        self.assertEqual(first["values"]["student_no"], "20260007")
        self.assertEqual(first["values"]["last_name"], "Dela Cruz")
        self.assertEqual(first["values"]["first_name"], "Juan P.")
        self.assertEqual(first["values"]["year_level"], 1)
        self.assertEqual(second["kind"], "error")

    def test_semicolon_csv_and_cp1252(self):
        f = SimpleUploadedFile(
            "r.csv", "Student No;Last Name;First Name;Year\n2026-0010;Peña;José;2\n".encode("cp1252")
        )
        imp = self.preview(f)
        self.assertEqual(imp.rows[0]["values"]["last_name"], "Peña")

    def test_file_level_errors(self):
        with self.assertRaisesMessage(importer.RosterFileError, "student number"):
            self.preview(csv_file("Name,Year\nA,1\n"))
        with self.assertRaisesMessage(importer.RosterFileError, "Year column"):
            self.preview(csv_file("Student No.,Last Name,First Name\n1,A,B\n"))
        with self.assertRaisesMessage(importer.RosterFileError, ".csv or .xlsx"):
            self.preview(SimpleUploadedFile("r.txt", b"x"))
        with self.assertRaisesMessage(importer.RosterFileError, "Excel file"):
            self.preview(SimpleUploadedFile("r.xlsx", b"not a zip"))

    def test_records_file_hash(self):
        imp = self.preview(csv_file("Student No.,Last Name,First Name,Year\n1,A,B,1\n"))
        self.assertEqual(len(imp.file_sha256), 64)
