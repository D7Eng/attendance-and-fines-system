"""Student login accounts and temporary passwords.

A student logs in with their student number. One User is shared by all of a
person's roster records across terms. Temporary passwords are shown once to
the treasurer for handing out and are never stored in readable form.
"""

import secrets

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.db import transaction
from django.utils import timezone

from audit.log import record

from . import roles
from .models import profile_for

# No 0/O, 1/l/I, so a printed slip is easy to type.
TEMP_ALPHABET = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789"
TEMP_LENGTH = 10


def make_temp_password():
    return "".join(secrets.choice(TEMP_ALPHABET) for _ in range(TEMP_LENGTH))


def issue_temp_password(user):
    """Set a new temporary password, flag it for change, and return it."""
    password = make_temp_password()
    user.set_password(password)
    user.save(update_fields=["password"])
    profile = profile_for(user)
    profile.must_change_password = True
    profile.temp_password_issued_at = timezone.now()
    profile.save(update_fields=["must_change_password", "temp_password_issued_at"])
    record("temp_password", f"Temporary password issued to {user.get_username()}", target=user)
    return password


@transaction.atomic
def create_student_login(student):
    """Give a student a login. Returns (user, temp password or None).

    If the student already has an account from another term (same student
    number), it is linked and keeps its password, so None is returned.
    """
    if student.user_id:
        return student.user, None
    User = get_user_model()
    user = User.objects.filter(username__iexact=student.student_no).first()
    password = None
    if user is None:
        user = User.objects.create_user(
            username=student.student_no, first_name=student.first_name[:150], last_name=student.last_name[:150]
        )
        password = issue_temp_password(user)
    user.groups.add(Group.objects.get(name=roles.STUDENT))
    student.user = user
    student.save(update_fields=["user", "updated_at"])
    record("login_linked", f"Login {user.get_username()} linked to {student} ({student.term})", target=student)
    return user, password


def reset_student_password(student):
    if not student.user_id:
        return create_student_login(student)
    return student.user, issue_temp_password(student.user)
