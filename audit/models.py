from django.conf import settings
from django.db import models


class AuditLog(models.Model):
    """Who did what, when. Entries are only ever added."""

    at = models.DateTimeField(auto_now_add=True, db_index=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    actor_name = models.CharField(max_length=150, blank=True, help_text="Kept if the user is later removed.")
    action = models.CharField(max_length=40, db_index=True)
    target_type = models.CharField(max_length=40, blank=True)
    target_id = models.CharField(max_length=40, blank=True)
    summary = models.CharField(max_length=255)
    details = models.JSONField(default=dict, blank=True)
    ip = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        ordering = ["-at", "-id"]

    def __str__(self):
        return f"{self.at:%Y-%m-%d %H:%M} {self.actor_name} {self.action}"

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValueError("Audit entries cannot be changed.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError("Audit entries cannot be deleted.")
