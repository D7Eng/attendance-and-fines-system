from django.conf import settings
from django.contrib import messages
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.urls import reverse_lazy

from audit.log import record
from roster.models import Student
from terms.models import Term

from . import logins, roles
from .forms import LoginForm, StudentSelectForm
from .models import profile_for


@login_required
def home(request):
    if roles.has_role(request.user, *roles.ATTENDANCE_EDITORS):
        return redirect("reports:dashboard")
    if roles.has_role(request.user, *roles.ROSTER_VIEWERS):
        return redirect("roster:student_list")
    if roles.has_role(request.user, roles.STUDENT):
        return redirect("me")
    return render(request, "accounts/home.html")


class LoginView(auth_views.LoginView):
    authentication_form = LoginForm


class PasswordChangeView(auth_views.PasswordChangeView):
    template_name = "registration/password_change.html"
    success_url = reverse_lazy("home")

    def form_valid(self, form):
        response = super().form_valid(form)
        record("password_changed", f"{self.request.user.get_username()} changed their password")
        profile = profile_for(self.request.user)
        if profile.must_change_password:
            profile.must_change_password = False
            profile.save(update_fields=["must_change_password"])
        messages.success(self.request, "Your password has been changed.")
        return response

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["forced"] = profile_for(self.request.user).must_change_password
        return context


def privacy(request):
    return render(
        request,
        "accounts/privacy.html",
        {"org_name": settings.DUESTRACK_ORG_NAME, "privacy_contact": settings.DUESTRACK_PRIVACY_CONTACT},
    )


@roles.role_required(*roles.ROSTER_EDITORS)
def student_logins(request):
    """List a year's students with their login status; create logins or reset passwords in bulk."""
    term = Term.objects.filter(pk=request.GET.get("term") or 0).first() or Term.objects.active() or Term.objects.first()
    if term is None:
        return redirect("roster:student_list")
    try:
        year = int(request.GET.get("year", 1))
    except ValueError:
        year = 1
    students = list(
        Student.objects.filter(term=term, year_level=year)
        .select_related("user", "user__profile")
        .order_by("group", "last_name", "first_name")
    )
    form = StudentSelectForm(request.POST or None, student_ids=[s.pk for s in students])
    if request.method == "POST" and form.is_valid():
        chosen = [s for s in students if s.pk in set(form.cleaned_data["students"])]
        issued, linked = [], 0
        for student in chosen:
            if form.cleaned_data["action"] == StudentSelectForm.ACTION_CREATE:
                _, password = logins.create_student_login(student)
            else:
                _, password = logins.reset_student_password(student)
            if password:
                issued.append((student, password))
            else:
                linked += 1
        return render(request, "accounts/login_slips.html", {"term": term, "issued": issued, "linked": linked})
    return render(
        request,
        "accounts/student_logins.html",
        {
            "term": term,
            "terms": Term.objects.all(),
            "year": year,
            "students": students,
            "form": form,
            "years": range(1, 6),
        },
    )
