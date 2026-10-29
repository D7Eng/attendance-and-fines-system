from django.shortcuts import redirect
from django.urls import reverse

from .models import Profile


class ForcePasswordChangeMiddleware:
    """Send users holding a temporary password to the change-password page."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = request.user
        if user.is_authenticated and Profile.objects.filter(user=user, must_change_password=True).exists():
            allowed = {reverse("password_change"), reverse("logout"), reverse("privacy")}
            if request.path not in allowed and not request.path.startswith("/static/"):
                return redirect("password_change")
        return self.get_response(request)
