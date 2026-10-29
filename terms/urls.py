from django.urls import path

from . import views

app_name = "terms"

urlpatterns = [
    path("", views.term_list, name="term_list"),
    path("new/", views.term_form, name="term_add"),
    path("<int:pk>/", views.term_form, name="term_edit"),
]
