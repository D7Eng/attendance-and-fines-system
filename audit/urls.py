from django.urls import path

from . import views

app_name = "audit"

urlpatterns = [
    path("", views.audit_log, name="log"),
    path("backup/", views.backup_download, name="backup"),
]
