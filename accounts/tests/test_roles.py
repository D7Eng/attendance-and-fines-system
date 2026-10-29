from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse

from accounts import roles


class RoleTests(TestCase):
    def test_role_groups_exist(self):
        self.assertEqual(set(Group.objects.values_list("name", flat=True)), set(roles.ALL_ROLES))

    def test_superuser_counts_as_admin(self):
        admin = User.objects.create_superuser("root", password="x")
        self.assertTrue(roles.has_role(admin, roles.ADMIN))

    def test_home_redirects_roster_viewers(self):
        user = User.objects.create_user("t")
        user.groups.add(Group.objects.get(name=roles.TREASURER))
        self.client.force_login(user)
        self.assertRedirects(self.client.get(reverse("home")), reverse("roster:student_list"))

    def test_login_page_shows_privacy_notice(self):
        self.assertContains(self.client.get(reverse("login")), "RA 10173")
