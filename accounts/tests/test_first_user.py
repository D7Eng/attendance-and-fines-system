import os
from io import StringIO
from unittest import mock

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.test import TestCase

from accounts.models import Profile
from accounts.roles import TREASURER, user_roles

ENV = {"DUESTRACK_FIRST_USERNAME": "treasurer", "DUESTRACK_FIRST_PASSWORD": "temp-pass-123"}


def run():
    call_command("ensure_first_user", stdout=StringIO(), stderr=StringIO())


class EnsureFirstUserTests(TestCase):
    def test_creates_treasurer_with_forced_password_change(self):
        with mock.patch.dict(os.environ, ENV):
            run()
        user = get_user_model().objects.get(username="treasurer")
        self.assertTrue(user.is_superuser)
        self.assertTrue(user.check_password("temp-pass-123"))
        self.assertIn(TREASURER, user_roles(user))
        self.assertTrue(Profile.objects.get(user=user).must_change_password)

    def test_never_touches_existing_admin(self):
        with mock.patch.dict(os.environ, ENV):
            run()
            user = get_user_model().objects.get(username="treasurer")
            user.set_password("my-own-password-9")
            user.save()
            run()
        user.refresh_from_db()
        self.assertTrue(user.check_password("my-own-password-9"))
        self.assertEqual(get_user_model().objects.count(), 1)

    def test_skips_without_variables(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            run()
        self.assertFalse(get_user_model().objects.exists())
