from django.urls import path

from . import views

app_name = "finance"

urlpatterns = [
    path("", views.payment_list, name="payment_list"),
    path("student/<int:pk>/", views.account, name="account"),
    path("student/<int:pk>/pay/", views.record_payment, name="pay"),
    path("student/<int:pk>/refund/", views.record_refund, name="refund"),
    path("student/<int:pk>/waive/<int:event_pk>/", views.waive, name="waive"),
    path("waivers/<int:pk>/revoke/", views.revoke_waiver, name="revoke_waiver"),
    path("<int:pk>/receipt/", views.receipt, name="receipt"),
    path("<int:pk>/reverse/", views.reverse_payment, name="reverse"),
]
