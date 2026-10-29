from django.contrib import admin

from .models import RosterImport, Student


@admin.register(Student)
class StudentAdmin(admin.ModelAdmin):
    list_display = ["student_no", "last_name", "first_name", "year_level", "group", "is_officer", "status", "term"]
    list_filter = ["term", "year_level", "group", "is_officer", "status"]
    search_fields = ["student_no", "last_name", "first_name"]


@admin.register(RosterImport)
class RosterImportAdmin(admin.ModelAdmin):
    list_display = [
        "file_name",
        "term",
        "status",
        "uploaded_by",
        "uploaded_at",
        "new_count",
        "changed_count",
        "error_count",
    ]
    readonly_fields = [f.name for f in RosterImport._meta.fields] + ["rows"]
