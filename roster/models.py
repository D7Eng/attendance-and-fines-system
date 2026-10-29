from django.conf import settings
from django.db import models

from terms.models import Term

YEAR_LEVEL_CHOICES = [(1, "1st year"), (2, "2nd year"), (3, "3rd year"), (4, "4th year"), (5, "5th year")]


class Student(models.Model):
    """A student on one term's roster. Only what fines and dues need is kept."""

    ENROLLED = "enrolled"
    NOT_ENROLLED = "not_enrolled"
    STATUS_CHOICES = [(ENROLLED, "Enrolled"), (NOT_ENROLLED, "Not enrolled")]

    term = models.ForeignKey(Term, on_delete=models.PROTECT, related_name="students")
    student_no = models.CharField("student no.", max_length=30)
    last_name = models.CharField(max_length=100)
    first_name = models.CharField(max_length=100)
    middle_name = models.CharField(max_length=100, blank=True)
    year_level = models.PositiveSmallIntegerField(choices=YEAR_LEVEL_CHOICES)
    group = models.CharField(max_length=50, blank=True, help_text="Section or block.")
    is_officer = models.BooleanField(default=False)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=ENROLLED)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="student"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["year_level", "group", "last_name", "first_name"]
        constraints = [models.UniqueConstraint(fields=["term", "student_no"], name="unique_student_no_per_term")]
        indexes = [models.Index(fields=["term", "year_level", "group"])]

    def __str__(self):
        return f"{self.student_no} {self.full_name}"

    @property
    def full_name(self):
        middle = f" {self.middle_name[0]}." if self.middle_name else ""
        return f"{self.last_name}, {self.first_name}{middle}"

    @property
    def is_enrolled(self):
        return self.status == self.ENROLLED


class RosterImport(models.Model):
    """One uploaded roster file: previewed first, then applied on confirmation."""

    PREVIEW = "preview"
    APPLIED = "applied"
    STATUS_CHOICES = [(PREVIEW, "Preview"), (APPLIED, "Applied")]

    term = models.ForeignKey(Term, on_delete=models.PROTECT, related_name="roster_imports")
    file_name = models.CharField(max_length=255)
    file_sha256 = models.CharField(max_length=64)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    applied_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=PREVIEW)
    # Parsed rows and their classification, so applying uses exactly what was previewed.
    rows = models.JSONField(default=list)
    new_count = models.PositiveIntegerField(default=0)
    changed_count = models.PositiveIntegerField(default=0)
    unchanged_count = models.PositiveIntegerField(default=0)
    error_count = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-uploaded_at"]

    def __str__(self):
        return f"{self.file_name} ({self.get_status_display()})"
