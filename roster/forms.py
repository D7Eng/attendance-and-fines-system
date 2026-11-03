from django import forms

from terms.models import Term

from .models import YEAR_LEVEL_CHOICES


class RosterUploadForm(forms.Form):
    term = forms.ModelChoiceField(queryset=Term.objects.all())
    file = forms.FileField(help_text="CSV or Excel (.xlsx). The first sheet is read.")
    default_year_level = forms.TypedChoiceField(
        choices=[("", "Use the file's Year column")] + YEAR_LEVEL_CHOICES,
        coerce=int,
        empty_value=None,
        required=False,
        label="Year level",
        help_text="Used for rows with no year level, e.g. when the file is one year's sheet.",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        active = Term.objects.active()
        if active:
            self.fields["term"].initial = active.pk

    def clean_file(self):
        f = self.cleaned_data["file"]
        if not f.name.lower().endswith((".csv", ".xlsx")):
            raise forms.ValidationError("Upload a .csv or .xlsx file.")
        return f
