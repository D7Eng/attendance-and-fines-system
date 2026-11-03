from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import User

from .models import Profile


class ProfileInline(admin.StackedInline):
    model = Profile
    can_delete = False
    fields = ["must_change_password", "temp_password_issued_at"]
    readonly_fields = ["temp_password_issued_at"]


admin.site.unregister(User)


@admin.register(User)
class DuesTrackUserAdmin(UserAdmin):
    inlines = [ProfileInline]
