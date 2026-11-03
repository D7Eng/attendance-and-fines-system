from django.urls import path

from . import views

app_name = "roster"

urlpatterns = [
    path("", views.student_list, name="student_list"),
    path("import/", views.import_upload, name="import_upload"),
    path("import/<int:pk>/", views.import_preview, name="import_preview"),
    path("import/<int:pk>/apply/", views.import_apply, name="import_apply"),
]
