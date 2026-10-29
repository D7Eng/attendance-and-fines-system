from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render

from . import roles


@login_required
def home(request):
    if roles.has_role(request.user, *roles.ROSTER_VIEWERS):
        return redirect("roster:student_list")
    return render(request, "accounts/home.html")
