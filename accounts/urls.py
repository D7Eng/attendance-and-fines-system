from django.urls import path

from reports.views import my_record

from . import views

urlpatterns = [
    path("", views.home, name="home"),
    path("login/", views.LoginView.as_view(), name="login"),
    path("password/", views.PasswordChangeView.as_view(), name="password_change"),
    path("privacy/", views.privacy, name="privacy"),
    path("me/", my_record, name="me"),
    path("students/logins/", views.student_logins, name="student_logins"),
]
