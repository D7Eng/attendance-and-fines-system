from django import forms
from django.forms import BaseInlineFormSet, inlineformset_factory

from roster.models import YEAR_LEVEL_CHOICES

from .models import DuesRate, Term

TERM_FIELDS = [
    "name",
    "start_date",
    "end_date",
    "is_active",
    "absence_fine_regular",
    "absence_fine_officer",
    "uniform_extra_regular",
    "uniform_extra_officer",
    "weekly_dues",
    "dues_weeks",
    "am_pm_cutoff",
]


class TermForm(forms.ModelForm):
    class Meta:
        model = Term
        fields = TERM_FIELDS
        labels = {
            "is_active": "Active term (the one pages open by default)",
            "absence_fine_regular": "Absence fine per missing mark, members",
            "absence_fine_officer": "Absence fine per missing mark, officers",
            "uniform_extra_regular": "Uniform violation extra, members",
            "uniform_extra_officer": "Uniform violation extra, officers",
            "weekly_dues": "Weekly dues (default)",
            "dues_weeks": "Weeks of dues in the term",
            "am_pm_cutoff": "AM/PM cutoff",
        }
        widgets = {
            "start_date": forms.DateInput(attrs={"type": "date"}),
            "end_date": forms.DateInput(attrs={"type": "date"}),
            "am_pm_cutoff": forms.TimeInput(attrs={"type": "time"}, format="%H:%M"),
        }

    def clean(self):
        cleaned = super().clean()
        start, end = cleaned.get("start_date"), cleaned.get("end_date")
        if start and end and end < start:
            self.add_error("end_date", "The term cannot end before it starts.")
        return cleaned


class BaseDuesRateFormSet(BaseInlineFormSet):
    def clean(self):
        super().clean()
        seen = set()
        for form in self.forms:
            if not form.cleaned_data or form.cleaned_data.get("DELETE"):
                continue
            key = (
                form.cleaned_data.get("officer") or "",
                form.cleaned_data.get("year_level"),
                (form.cleaned_data.get("group") or "").casefold(),
            )
            if key in seen:
                raise forms.ValidationError("Two dues rates have the same officer, year and group criteria.")
            seen.add(key)


DuesRateFormSet = inlineformset_factory(
    Term,
    DuesRate,
    formset=BaseDuesRateFormSet,
    fields=["label", "officer", "year_level", "group", "weekly_amount"],
    widgets={"year_level": forms.Select(choices=[("", "Any")] + YEAR_LEVEL_CHOICES)},
    extra=2,
    can_delete=True,
)
