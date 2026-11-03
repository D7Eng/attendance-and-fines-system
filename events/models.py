from django.conf import settings
from django.db import models

from roster.models import Student
from terms.models import Term

AM = "am"
PM = "pm"
SESSION_CHOICES = [(AM, "AM"), (PM, "PM")]

# Attendance mark fields, each a required IN or OUT scan; a missing one is fined.
MARKS = {AM: ["am_in", "am_out"], PM: ["pm_in", "pm_out"]}
MARK_LABELS = {"am_in": "AM in", "am_out": "AM out", "pm_in": "PM in", "pm_out": "PM out"}
UNIFORM = {AM: "am_uniform", PM: "pm_uniform"}


class Event(models.Model):
    """An activity where attendance is taken, in the morning, afternoon, or both."""

    term = models.ForeignKey(Term, on_delete=models.PROTECT, related_name="events")
    name = models.CharField(max_length=150)
    date = models.DateField()
    has_am = models.BooleanField("morning session", default=True)
    has_pm = models.BooleanField("afternoon session", default=False)
    year_levels = models.JSONField(
        default=list, blank=True, help_text="Year levels required to attend; empty means every year."
    )
    notes = models.CharField(max_length=255, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["date", "id"]

    def __str__(self):
        return f"{self.name} ({self.date:%b} {self.date.day}, {self.date.year})"

    @property
    def sessions(self):
        return [s for s, on in ((AM, self.has_am), (PM, self.has_pm)) if on]

    @property
    def mark_fields(self):
        return [field for session in self.sessions for field in MARKS[session]]

    @property
    def uniform_fields(self):
        return [UNIFORM[session] for session in self.sessions]

    @property
    def year_levels_display(self):
        return ", ".join(str(y) for y in sorted(self.year_levels)) if self.year_levels else "All years"

    def applies_to(self, student):
        """Whether the student is expected at this event (and so can be fined for it)."""
        if not student.is_enrolled or student.term_id != self.term_id:
            return False
        return not self.year_levels or student.year_level in self.year_levels

    def expected_students(self):
        students = Student.objects.filter(term=self.term_id, status=Student.ENROLLED)
        if self.year_levels:
            students = students.filter(year_level__in=self.year_levels)
        return students


class Attendance(models.Model):
    """One student's marks at one event. No row means no marks at all."""

    event = models.ForeignKey(Event, on_delete=models.PROTECT, related_name="attendance")
    student = models.ForeignKey(Student, on_delete=models.PROTECT, related_name="attendance")
    am_in = models.BooleanField(default=False)
    am_out = models.BooleanField(default=False)
    pm_in = models.BooleanField(default=False)
    pm_out = models.BooleanField(default=False)
    am_uniform = models.BooleanField("AM uniform violation", default=False)
    pm_uniform = models.BooleanField("PM uniform violation", default=False)
    # Scan times by mark field, e.g. {"am_in": "07:58"}, from QR imports.
    scan_times = models.JSONField(default=dict, blank=True)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["event", "student"], name="one_attendance_per_student")]

    def __str__(self):
        return f"{self.student} at {self.event}"

    def missing_marks(self, event=None):
        event = event or self.event
        return sum(1 for field in event.mark_fields if not getattr(self, field))

    def uniform_violations(self, event=None):
        event = event or self.event
        return sum(1 for field in event.uniform_fields if getattr(self, field))


class ScanImport(models.Model):
    """One QR scanner export for an event: previewed first, then applied."""

    PREVIEW = "preview"
    APPLIED = "applied"
    STATUS_CHOICES = [(PREVIEW, "Preview"), (APPLIED, "Applied")]

    AUTO = "auto"
    MODE_CHOICES = [(AUTO, "Work it out from the scan times")] + [(f, label) for f, label in MARK_LABELS.items()]

    event = models.ForeignKey(Event, on_delete=models.PROTECT, related_name="scan_imports")
    file_name = models.CharField(max_length=255)
    file_sha256 = models.CharField(max_length=64)
    mode = models.CharField(max_length=10, choices=MODE_CHOICES, default=AUTO)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    uploaded_at = models.DateTimeField(auto_now_add=True)
    applied_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default=PREVIEW)
    rows = models.JSONField(default=list)
    counts = models.JSONField(default=dict)
    marks_added = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["-uploaded_at"]

    def __str__(self):
        return f"{self.file_name} → {self.event}"
