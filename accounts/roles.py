"""Role definitions. Each role is a Django auth Group with the same name."""

from functools import wraps

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied

ADMIN = "Admin"
TREASURER = "Treasurer"
OFFICER = "Officer"
STUDENT = "Student"

ALL_ROLES = [ADMIN, TREASURER, OFFICER, STUDENT]

# Who may see the full roster, and who may change it.
ROSTER_VIEWERS = {ADMIN, TREASURER, OFFICER}
ROSTER_EDITORS = {ADMIN, TREASURER}


def user_roles(user):
    if not user.is_authenticated:
        return set()
    if not hasattr(user, "_duestrack_roles"):
        roles = set(user.groups.values_list("name", flat=True))
        if user.is_superuser:
            roles.add(ADMIN)
        user._duestrack_roles = roles
    return user._duestrack_roles


def has_role(user, *roles):
    return bool(user_roles(user) & set(roles))


def role_required(*roles):
    """Require login and at least one of the given roles; otherwise 403."""

    def decorator(view):
        @wraps(view)
        @login_required
        def wrapped(request, *args, **kwargs):
            if not has_role(request.user, *roles):
                raise PermissionDenied
            return view(request, *args, **kwargs)

        return wrapped

    return decorator
