from django.contrib.auth.models import Group, User
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from accounts import logins, roles
from accounts.models import Profile
from roster.models import Student
from terms.models import Term


def make_user(username, role=None):
    user = User.objects.create_user(username, password="pw-123456!")
    if role:
        user.groups.add(Group.objects.get(name=role))
    return user


class StudentLoginTests(TestCase):
    def setUp(self):
        cache.clear()
        self.term = Term.objects.create(name="1st Sem", is_active=True)
        self.ana = Student.objects.create(
            term=self.term, student_no="2026-0001", last_name="Cruz", first_name="Ana", year_level=1
        )

    def test_create_login_issues_temp_password(self):
        user, password = logins.create_student_login(self.ana)
        self.assertEqual(user.username, "2026-0001")
        self.assertEqual(len(password), logins.TEMP_LENGTH)
        self.assertTrue(user.check_password(password))
        self.assertTrue(roles.has_role(user, roles.STUDENT))
        self.assertTrue(user.profile.must_change_password)
        self.ana.refresh_from_db()
        self.assertEqual(self.ana.user, user)
        # Creating again does nothing.
        self.assertEqual(logins.create_student_login(self.ana), (user, None))

    def test_next_term_record_links_existing_account(self):
        user, _ = logins.create_student_login(self.ana)
        term2 = Term.objects.create(name="2nd Sem")
        again = Student.objects.create(
            term=term2, student_no="2026-0001", last_name="Cruz", first_name="Ana", year_level=1
        )
        linked, password = logins.create_student_login(again)
        self.assertEqual(linked, user)
        self.assertIsNone(password)
        self.assertEqual(user.student_records.count(), 2)

    def test_login_by_student_no_in_any_case_then_forced_change(self):
        Student.objects.filter(pk=self.ana.pk).update(student_no="AB-0001")
        self.ana.refresh_from_db()
        _, password = logins.create_student_login(self.ana)
        response = self.client.post(reverse("login"), {"username": " ab-0001 ", "password": password})
        self.assertRedirects(response, reverse("home"), fetch_redirect_response=False)
        # Every page sends them to change the temporary password first.
        self.assertRedirects(self.client.get(reverse("me")), reverse("password_change"))
        response = self.client.post(
            reverse("password_change"),
            {
                "old_password": password,
                "new_password1": "a-much-better-pass-77",
                "new_password2": "a-much-better-pass-77",
            },
        )
        self.assertRedirects(response, reverse("home"), fetch_redirect_response=False)
        self.assertFalse(Profile.objects.get(user__username="AB-0001").must_change_password)
        response = self.client.get(reverse("me"))
        self.assertContains(response, "Cruz, Ana")

    def test_lockout_after_repeated_failures(self):
        make_user("treasurer")
        for _ in range(5):
            self.client.post(reverse("login"), {"username": "treasurer", "password": "wrong"})
        response = self.client.post(reverse("login"), {"username": "treasurer", "password": "pw-123456!"})
        self.assertContains(response, "Too many failed attempts")

    def test_student_sees_only_own_record_page(self):
        student_user, _ = logins.create_student_login(self.ana)
        Profile.objects.filter(user=student_user).update(must_change_password=False)
        self.client.force_login(student_user)
        self.assertRedirects(self.client.get(reverse("home")), reverse("me"))
        self.assertEqual(self.client.get(reverse("roster:student_list")).status_code, 403)
        self.assertEqual(self.client.get(reverse("student_logins")).status_code, 403)

    def test_logins_page_bulk_create_and_reset(self):
        ben = Student.objects.create(
            term=self.term, student_no="2026-0002", last_name="Reyes", first_name="Ben", year_level=1
        )
        self.client.force_login(make_user("t", roles.TREASURER))
        url = reverse("student_logins")
        self.assertContains(self.client.get(url), "2026-0002")
        response = self.client.post(url, {"action": "create", "students": [self.ana.pk, ben.pk]})
        self.assertEqual(len(response.context["issued"]), 2)
        self.assertContains(response, "Temporary password")
        old_hash = User.objects.get(username="2026-0002").password
        response = self.client.post(url, {"action": "reset", "students": [ben.pk]})
        self.assertEqual(len(response.context["issued"]), 1)
        self.assertNotEqual(User.objects.get(username="2026-0002").password, old_hash)

    def test_officer_cannot_manage_logins(self):
        self.client.force_login(make_user("o", roles.OFFICER))
        self.assertEqual(self.client.get(reverse("student_logins")).status_code, 403)

    def test_privacy_page_is_reachable_before_login(self):
        self.assertContains(self.client.get(reverse("privacy")), "RA 10173")
