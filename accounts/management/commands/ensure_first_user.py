"""Create the first Treasurer account from environment variables.

Used on hosts with no terminal (e.g. Render): set DUESTRACK_FIRST_USERNAME and
DUESTRACK_FIRST_PASSWORD, and the start command runs this on every deploy.
It does nothing once any superuser exists, so it never changes or resets an
existing account. The password is temporary: the user must change it on first login.
"""

import os

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management.base import BaseCommand
from django.db import transaction

from accounts.models import profile_for
from accounts.roles import TREASURER


class Command(BaseCommand):
    help = "Create the first Treasurer (a superuser) from DUESTRACK_FIRST_USERNAME / DUESTRACK_FIRST_PASSWORD."

    def handle(self, *args, **options):
        username = os.environ.get("DUESTRACK_FIRST_USERNAME", "").strip()
        password = os.environ.get("DUESTRACK_FIRST_PASSWORD", "")
        User = get_user_model()
        if User.objects.filter(is_superuser=True).exists():
            self.stdout.write("First user: an administrator already exists, nothing to do.")
            return
        if not username or not password:
            self.stdout.write("First user: DUESTRACK_FIRST_USERNAME / DUESTRACK_FIRST_PASSWORD not set, skipping.")
            return
        if len(password) < 8:
            self.stderr.write("First user: DUESTRACK_FIRST_PASSWORD must be at least 8 characters, skipping.")
            return
        if User.objects.filter(username__iexact=username).exists():
            self.stderr.write(f"First user: the username {username!r} is already taken, skipping.")
            return
        with transaction.atomic():
            user = User.objects.create_superuser(username=username, email="", password=password)
            group, _ = Group.objects.get_or_create(name=TREASURER)
            user.groups.add(group)
            profile = profile_for(user)
            profile.must_change_password = True
            profile.save(update_fields=["must_change_password"])
        self.stdout.write(self.style.SUCCESS(f"First user: created Treasurer {username!r} (must change password)."))
