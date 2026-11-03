from django.urls import path

from . import views

app_name = "events"

urlpatterns = [
    path("", views.event_list, name="event_list"),
    path("new/", views.event_form, name="event_add"),
    path("<int:pk>/", views.attendance, name="attendance"),
    path("<int:pk>/edit/", views.event_form, name="event_edit"),
    path("<int:pk>/delete/", views.event_delete, name="event_delete"),
    path("<int:pk>/scans/", views.scan_upload, name="scan_upload"),
    path("scans/<int:pk>/", views.scan_preview, name="scan_preview"),
    path("scans/<int:pk>/apply/", views.scan_apply, name="scan_apply"),
]
