from django import forms
from django.contrib.auth.forms import AuthenticationForm
from django.core.cache import cache

from duestrack.net import client_ip

# After this many failed logins for one username from one address, wait LOCKOUT_SECONDS.
MAX_FAILURES = 5
LOCKOUT_SECONDS = 15 * 60


class LoginForm(AuthenticationForm):
    """Django's login form with a label students understand and a simple lockout."""

    error_messages = {
        **AuthenticationForm.error_messages,
        "locked": "Too many failed attempts. Try again in 15 minutes.",
    }

    def __init__(self, request=None, *args, **kwargs):
        super().__init__(request, *args, **kwargs)
        self.fields["username"].label = "Username or student no."

    def _key(self):
        username = (self.data.get("username") or "").strip().lower()
        return f"login-fail:{client_ip(self.request) or ''}:{username}"

    def clean(self):
        key = self._key()
        if cache.get(key, 0) >= MAX_FAILURES:
            raise forms.ValidationError(self.error_messages["locked"], code="locked")
        try:
            cleaned = super().clean()
        except forms.ValidationError:
            try:
                cache.incr(key)
            except ValueError:
                cache.set(key, 1, LOCKOUT_SECONDS)
            raise
        cache.delete(key)
        return cleaned


class StudentSelectForm(forms.Form):
    """Checked students on the logins page."""

    ACTION_CREATE = "create"
    ACTION_RESET = "reset"

    action = forms.ChoiceField(choices=[(ACTION_CREATE, "Create logins"), (ACTION_RESET, "Reset passwords")])
    students = forms.TypedMultipleChoiceField(coerce=int, choices=[])

    def __init__(self, *args, student_ids=(), **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["students"].choices = [(i, i) for i in student_ids]
