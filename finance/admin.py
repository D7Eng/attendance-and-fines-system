from django.contrib import admin

from .models import Payment, Waiver


class ReadOnlyAdmin(admin.ModelAdmin):
    """Money records change only through the app, so every change is checked and logged."""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Payment)
class PaymentAdmin(ReadOnlyAdmin):
    list_display = ["receipt_no", "student", "kind", "amount", "method", "gcash_ref", "recorded_at", "reversed_at"]
    list_filter = ["term", "kind", "method"]
    search_fields = ["receipt_no", "gcash_ref", "student__student_no", "student__last_name"]


@admin.register(Waiver)
class WaiverAdmin(ReadOnlyAdmin):
    list_display = ["student", "event", "reason", "created_by", "created_at", "revoked_at"]
    list_filter = ["event__term"]
