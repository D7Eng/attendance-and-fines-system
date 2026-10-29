from django.urls import path

from . import views

app_name = "reports"

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("reports/balances/", views.balances, name="balances"),
    path("reports/collections/", views.collections, name="collections"),
    path("reports/events/<int:pk>/", views.event_report, name="event_report"),
    path("reports/statements/<int:pk>/", views.statement, name="statement"),
]
