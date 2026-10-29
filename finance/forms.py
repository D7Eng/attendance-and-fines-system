from django import forms

from .models import Payment


class PaymentForm(forms.Form):
    amount = forms.DecimalField(max_digits=10, decimal_places=2, min_value=0.01)
    method = forms.ChoiceField(choices=Payment.METHOD_CHOICES, initial=Payment.CASH)
    gcash_ref = forms.CharField(
        label="GCash reference no.", max_length=40, required=False, help_text="Required for GCash. Checked for reuse."
    )
    note = forms.CharField(max_length=255, required=False)


class RefundForm(forms.Form):
    amount = forms.DecimalField(max_digits=10, decimal_places=2, min_value=0.01)
    method = forms.ChoiceField(choices=Payment.METHOD_CHOICES, initial=Payment.CASH)
    gcash_ref = forms.CharField(label="GCash reference no.", max_length=40, required=False)
    reason = forms.CharField(max_length=255)


class ReasonForm(forms.Form):
    reason = forms.CharField(max_length=255)
