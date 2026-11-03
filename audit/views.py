import datetime

from django import forms
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import render
from django.utils import timezone

from accounts.roles import AUDIT_VIEWERS, role_required

from .backup import MIN_PASSPHRASE, passphrase_backup
from .log import record
from .models import AuditLog


def _date(value):
    try:
        return datetime.date.fromisoformat(value)
    except (TypeError, ValueError):
        return None


@role_required(*AUDIT_VIEWERS)
def audit_log(request):
    entries = AuditLog.objects.all()
    action = request.GET.get("action", "")
    if action:
        entries = entries.filter(action=action)
    who = request.GET.get("who", "").strip()
    if who:
        entries = entries.filter(actor_name__icontains=who)
    q = request.GET.get("q", "").strip()
    for word in q.split():
        entries = entries.filter(Q(summary__icontains=word) | Q(target_id=word))
    start, end = _date(request.GET.get("from")), _date(request.GET.get("to"))
    if start:
        entries = entries.filter(at__date__gte=start)
    if end:
        entries = entries.filter(at__date__lte=end)
    actions = AuditLog.objects.order_by("action").values_list("action", flat=True).distinct()
    return render(
        request,
        "audit/log.html",
        {
            "page": Paginator(entries, 100).get_page(request.GET.get("page")),
            "actions": actions,
            "action": action,
            "who": who,
            "q": q,
            "start": start,
            "end": end,
        },
    )


class BackupDownloadForm(forms.Form):
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}),
        min_length=MIN_PASSPHRASE,
        help_text=f"At least {MIN_PASSPHRASE} characters. Without it the file cannot be opened, so keep it safe.",
    )
    confirm = forms.CharField(label="Type it again", widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}))

    def clean(self):
        data = super().clean()
        if data.get("password") and data.get("password") != data.get("confirm"):
            self.add_error("confirm", "The two passwords do not match.")
        return data


@role_required(*AUDIT_VIEWERS)
def backup_download(request):
    """Download the whole database, encrypted with a password, so a copy can be kept off the host."""
    form = BackupDownloadForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        blob = passphrase_backup(form.cleaned_data["password"])
        name = f"duestrack-{timezone.localtime():%Y%m%d-%H%M%S}.backup"
        record("backup", f"Encrypted backup downloaded: {name}", size=len(blob))
        response = HttpResponse(blob, content_type="application/octet-stream")
        response["Content-Disposition"] = f'attachment; filename="{name}"'
        response["Cache-Control"] = "no-store"
        return response
    return render(request, "audit/backup.html", {"form": form})
