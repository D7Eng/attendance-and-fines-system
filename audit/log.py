"""Write audit entries from anywhere: views, services, signals."""

import contextvars
from decimal import Decimal

from duestrack.net import client_ip

from .models import AuditLog

_request = contextvars.ContextVar("duestrack_request", default=None)


class RequestContextMiddleware:
    """Remember the current request so audit entries get the user and address."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        token = _request.set(request)
        try:
            return self.get_response(request)
        finally:
            _request.reset(token)


def _plain(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_plain(v) for v in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def record(action, summary, target=None, actor=None, **details):
    request = _request.get()
    if actor is None and request is not None and getattr(request, "user", None) and request.user.is_authenticated:
        actor = request.user
    return AuditLog.objects.create(
        actor=actor if actor is not None and actor.pk else None,
        actor_name=actor.get_username() if actor is not None else "",
        action=action,
        target_type=target._meta.label_lower if target is not None else "",
        target_id=str(target.pk) if target is not None else "",
        summary=summary[:255],
        details=_plain(details),
        ip=client_ip(request),
    )


def changes(old, new, fields):
    """{field: [old, new]} for fields that differ between two objects or dicts."""

    def get(obj, f):
        return obj.get(f) if isinstance(obj, dict) else getattr(obj, f)

    return {f: [get(old, f), get(new, f)] for f in fields if get(old, f) != get(new, f)}
