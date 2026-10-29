from django.conf import settings

from . import roles as r


def roles(request):
    user_roles = r.user_roles(request.user)
    return {
        "org_name": settings.DUESTRACK_ORG_NAME,
        "user_roles": user_roles,
        "can_view_roster": bool(user_roles & r.ROSTER_VIEWERS),
        "can_edit_roster": bool(user_roles & r.ROSTER_EDITORS),
        "can_take_attendance": bool(user_roles & r.ATTENDANCE_EDITORS),
        "can_view_finance": bool(user_roles & r.FINANCE_VIEWERS),
        "can_edit_finance": bool(user_roles & r.FINANCE_EDITORS),
        "can_edit_settings": bool(user_roles & r.SETTINGS_EDITORS),
        "can_view_audit": bool(user_roles & r.AUDIT_VIEWERS),
        "is_student": r.STUDENT in user_roles,
    }
