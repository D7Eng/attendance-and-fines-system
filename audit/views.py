import datetime

from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import render

from accounts.roles import AUDIT_VIEWERS, role_required

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
