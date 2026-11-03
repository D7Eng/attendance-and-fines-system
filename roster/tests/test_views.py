from django.contrib.auth.models import Group, User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.urls import reverse

from roster.models import RosterImport, Student
from terms.models import Term


def make_user(username, role=None):
    user = User.objects.create_user(username, password="pw-123456!")
    if role:
        user.groups.add(Group.objects.get(name=role))
    return user


class StudentListTests(TestCase):
    def setUp(self):
        self.term = Term.objects.create(name="1st Sem", is_active=True)
        rows = [
            ("1-001", "Cruz", "Ana", 1, "A", False),
            ("1-002", "Reyes", "Ben", 1, "B", True),
            ("1-003", "Santos", "Carla", 1, "B", False),
            ("2-001", "Lim", "Dan", 2, "A", False),
        ]
        for no, last, first, year, group, officer in rows:
            Student.objects.create(
                term=self.term,
                student_no=no,
                last_name=last,
                first_name=first,
                year_level=year,
                group=group,
                is_officer=officer,
            )
        self.url = reverse("roster:student_list")

    def names(self, response):
        return [s.last_name for s in response.context["page"]]

    def test_requires_login(self):
        response = self.client.get(self.url)
        self.assertRedirects(response, f"{reverse('login')}?next={self.url}")

    def test_students_cannot_see_roster(self):
        self.client.force_login(make_user("s", "Student"))
        self.assertEqual(self.client.get(self.url).status_code, 403)

    def test_officer_sees_first_year_by_default(self):
        self.client.force_login(make_user("o", "Officer"))
        response = self.client.get(self.url)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.names(response), ["Cruz", "Reyes", "Santos"])
        self.assertEqual(response.context["groups"], ["A", "B"])
        self.assertNotContains(response, reverse("roster:import_upload"))

    def test_year_group_officer_and_search_filters(self):
        self.client.force_login(make_user("t", "Treasurer"))
        self.assertEqual(self.names(self.client.get(self.url, {"year": 2})), ["Lim"])
        self.assertEqual(self.names(self.client.get(self.url, {"year": 1, "group": "b"})), ["Reyes", "Santos"])
        self.assertEqual(self.names(self.client.get(self.url, {"year": 1, "officer": "yes"})), ["Reyes"])
        self.assertEqual(self.names(self.client.get(self.url, {"year": 1, "q": "carla"})), ["Santos"])
        self.assertEqual(self.names(self.client.get(self.url, {"year": 1, "q": "1-002"})), ["Reyes"])

    def test_no_term_yet(self):
        Student.objects.all().delete()
        Term.objects.all().delete()
        self.client.force_login(make_user("t", "Treasurer"))
        self.assertContains(self.client.get(self.url), "No term has been set up yet")


class ImportViewTests(TestCase):
    def setUp(self):
        self.term = Term.objects.create(name="1st Sem", is_active=True)
        self.upload_url = reverse("roster:import_upload")

    def upload(self, text):
        return self.client.post(
            self.upload_url,
            {"term": self.term.pk, "file": SimpleUploadedFile("r.csv", text.encode()), "default_year_level": ""},
        )

    def test_officer_cannot_import(self):
        self.client.force_login(make_user("o", "Officer"))
        self.assertEqual(self.client.get(self.upload_url).status_code, 403)

    def test_upload_preview_apply_flow(self):
        self.client.force_login(make_user("t", "Treasurer"))
        response = self.upload("Student No.,Last Name,First Name,Year\n1-001,Cruz,Ana,1\n1-002,,Ben,1\n")
        imp = RosterImport.objects.get()
        self.assertRedirects(response, reverse("roster:import_preview", args=[imp.pk]))

        preview = self.client.get(reverse("roster:import_preview", args=[imp.pk]))
        self.assertContains(preview, "Apply: add 1, update 0")
        self.assertContains(preview, "Last name is missing.")
        self.assertEqual(Student.objects.count(), 0)

        response = self.client.post(reverse("roster:import_apply", args=[imp.pk]), follow=True)
        self.assertContains(response, "1 added, 0 changed")
        self.assertContains(response, "1 row(s) with errors were skipped")
        self.assertEqual(Student.objects.get().student_no, "1-001")

        # Re-uploading the same file warns that it was already applied.
        self.upload("Student No.,Last Name,First Name,Year\n1-001,Cruz,Ana,1\n1-002,,Ben,1\n")
        again = RosterImport.objects.first()
        self.assertContains(self.client.get(reverse("roster:import_preview", args=[again.pk])), "already applied")

    def test_apply_requires_post(self):
        self.client.force_login(make_user("t", "Treasurer"))
        self.upload("Student No.,Last Name,First Name,Year\n1-001,Cruz,Ana,1\n")
        imp = RosterImport.objects.get()
        self.assertEqual(self.client.get(reverse("roster:import_apply", args=[imp.pk])).status_code, 405)

    def test_bad_file_shows_form_error(self):
        self.client.force_login(make_user("t", "Treasurer"))
        response = self.upload("Name,Year\nA,1\n")
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "No header row with a student number column")
        self.assertFalse(RosterImport.objects.exists())
