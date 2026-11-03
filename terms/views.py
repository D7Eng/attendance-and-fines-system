from django.contrib import messages
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render

from accounts.roles import SETTINGS_EDITORS, role_required
from audit.log import changes, record

from .forms import TERM_FIELDS, DuesRateFormSet, TermForm
from .models import Term

RATE_FIELDS = ["label", "officer", "year_level", "group", "weekly_amount"]


@role_required(*SETTINGS_EDITORS)
def term_list(request):
    return render(request, "terms/term_list.html", {"terms": Term.objects.prefetch_related("dues_rates")})


@role_required(*SETTINGS_EDITORS)
def term_form(request, pk=None):
    term = get_object_or_404(Term, pk=pk) if pk else Term()
    before = {f: getattr(term, f) for f in TERM_FIELDS} if pk else None
    old_rates = {r.pk: {f: getattr(r, f) for f in RATE_FIELDS} for r in term.dues_rates.all()} if pk else {}
    form = TermForm(request.POST or None, instance=term)
    formset = DuesRateFormSet(request.POST or None, instance=term, prefix="rates")
    if request.method == "POST" and form.is_valid() and formset.is_valid():
        with transaction.atomic():
            term = form.save()
            formset.instance = term
            formset.save()
            new_rates = {r.pk: {f: getattr(r, f) for f in RATE_FIELDS} for r in term.dues_rates.all()}
            rate_log = {
                "added": [v for k, v in new_rates.items() if k not in old_rates],
                "removed": [v for k, v in old_rates.items() if k not in new_rates],
                "changed": {
                    old_rates[k]["label"]: changes(old_rates[k], v, RATE_FIELDS)
                    for k, v in new_rates.items()
                    if k in old_rates and old_rates[k] != v
                },
            }
            rate_log = {k: v for k, v in rate_log.items() if v}
            if before is None:
                record("term_created", f"Term {term} created", target=term, rates=rate_log)
            else:
                diff = changes(before, term, TERM_FIELDS)
                if diff or rate_log:
                    record("settings_changed", f"Settings of {term} changed", target=term, changes=diff, rates=rate_log)
        messages.success(request, f"Saved {term}.")
        return redirect("terms:term_list")
    return render(request, "terms/term_form.html", {"form": form, "formset": formset, "term": term if pk else None})
