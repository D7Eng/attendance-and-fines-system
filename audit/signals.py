from django.contrib.auth.signals import user_logged_in, user_logged_out, user_login_failed
from django.dispatch import receiver

from .log import record


@receiver(user_logged_in)
def logged_in(sender, request, user, **kwargs):
    record("login", f"{user.get_username()} logged in", actor=user)


@receiver(user_logged_out)
def logged_out(sender, request, user, **kwargs):
    if user is not None:
        record("logout", f"{user.get_username()} logged out", actor=user)


@receiver(user_login_failed)
def login_failed(sender, credentials, request=None, **kwargs):
    username = (credentials.get("username") or "")[:150]
    record("login_failed", f"Failed login for '{username}'", username=username)
