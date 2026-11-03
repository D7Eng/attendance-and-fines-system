from django import forms

from roster.models import YEAR_LEVEL_CHOICES
from terms.models import Term

from .models import Event, ScanImport


class EventForm(forms.ModelForm):
    year_levels = forms.TypedMultipleChoiceField(
        choices=YEAR_LEVEL_CHOICES,
        coerce=int,
        required=False,
        widget=forms.CheckboxSelectMultiple,
        help_text="Leave all unchecked if every year must attend.",
    )

    class Meta:
        model = Event
        fields = ["term", "name", "date", "has_am", "has_pm", "year_levels", "notes"]
        widgets = {"date": forms.DateInput(attrs={"type": "date"})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if not self.instance.pk:
            active = Term.objects.active()
            if active:
                self.fields["term"].initial = active.pk
        else:
            # Moving an event to another term would orphan its attendance.
            self.fields["term"].disabled = True

    def clean(self):
        cleaned = super().clean()
        if not cleaned.get("has_am") and not cleaned.get("has_pm"):
            raise forms.ValidationError("Pick at least one session (morning or afternoon).")
        return cleaned

    def clean_year_levels(self):
        return sorted(self.cleaned_data["year_levels"])


class ScanUploadForm(forms.Form):
    file = forms.FileField(help_text="The QR scanner's CSV or Excel export.")
    mode = forms.ChoiceField(
        choices=ScanImport.MODE_CHOICES,
        initial=ScanImport.AUTO,
        label="Marks",
        help_text="Automatic: scans before the AM/PM cutoff are morning; a student's first scan in a session is IN "
        "and the last is OUT, unless the file has an IN/OUT column. Or say which single mark every scan is for.",
    )

    def clean_file(self):
        f = self.cleaned_data["file"]
        if not f.name.lower().endswith((".csv", ".xlsx")):
            raise forms.ValidationError("Upload a .csv or .xlsx file.")
        return f
