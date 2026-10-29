from . import roles as r


def roles(request):
    user_roles = r.user_roles(request.user)
    return {
        "user_roles": user_roles,
        "can_view_roster": bool(user_roles & r.ROSTER_VIEWERS),
        "can_edit_roster": bool(user_roles & r.ROSTER_EDITORS),
        "is_student": r.STUDENT in user_roles,
    }
