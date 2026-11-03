from django.contrib import admin

from .models import DuesRate, Term


class DuesRateInline(admin.TabularInline):
    model = DuesRate
    extra = 0


@admin.register(Term)
class TermAdmin(admin.ModelAdmin):
    list_display = ["name", "start_date", "end_date", "is_active"]
    inlines = [DuesRateInline]
    fieldsets = [
        (None, {"fields": ["name", "start_date", "end_date", "is_active"]}),
        (
            "Fine rates (per missing IN or OUT mark)",
            {
                "fields": [
                    "absence_fine_regular",
                    "absence_fine_officer",
                    "uniform_extra_regular",
                    "uniform_extra_officer",
                ]
            },
        ),
        ("Dues", {"fields": ["weekly_dues", "dues_weeks"]}),
        ("Attendance", {"fields": ["am_pm_cutoff"]}),
    ]
