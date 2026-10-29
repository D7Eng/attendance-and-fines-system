from django.contrib import admin

from .models import Attendance, Event, ScanImport


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = ["name", "date", "term", "has_am", "has_pm"]
    list_filter = ["term"]


@admin.register(Attendance)
class AttendanceAdmin(admin.ModelAdmin):
    list_display = ["event", "student", "am_in", "am_out", "pm_in", "pm_out", "am_uniform", "pm_uniform"]
    list_filter = ["event__term", "event"]
    search_fields = ["student__student_no", "student__last_name"]
    raw_id_fields = ["student"]


@admin.register(ScanImport)
class ScanImportAdmin(admin.ModelAdmin):
    list_display = ["file_name", "event", "status", "uploaded_by", "uploaded_at", "marks_added"]
    readonly_fields = [f.name for f in ScanImport._meta.fields]
