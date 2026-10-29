from django.conf import settings
from django.db import models


class Profile(models.Model):
    """Per-user flags that Django's User has no field for."""

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile")
    must_change_password = models.BooleanField(
        default=False, help_text="Set when a temporary password is issued; cleared when the user picks their own."
    )
    temp_password_issued_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"Profile of {self.user}"


def profile_for(user):
    profile, _ = Profile.objects.get_or_create(user=user)
    return profile
