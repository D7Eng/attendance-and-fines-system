from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

urlpatterns = [
    path("", include("accounts.urls")),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("students/", include("roster.urls")),
    path("admin/", admin.site.urls),
]
