from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from accounts.roles import ROSTER_EDITORS, ROSTER_VIEWERS, role_required
from terms.models import Term

from . import importer
from .forms import RosterUploadForm
from .models import YEAR_LEVEL_CHOICES, RosterImport, Student


def _selected_term(request):
    term_id = request.GET.get("term")
    if term_id and term_id.isdigit():
        return Term.objects.filter(pk=term_id).first()
    return Term.objects.active() or Term.objects.first()


@role_required(*ROSTER_VIEWERS)
def student_list(request):
    term = _selected_term(request)
    context = {"term": term, "terms": Term.objects.all()}
    if term is None:
        return render(request, "roster/student_list.html", context)

    in_term = Student.objects.filter(term=term)
    year_counts = dict(in_term.values_list("year_level").annotate(n=Count("id")))
    years = [(value, label, year_counts.get(value, 0)) for value, label in YEAR_LEVEL_CHOICES]
    try:
        year = int(request.GET.get("year", ""))
    except ValueError:
        year = None
    if year not in year_counts:
        year = min(year_counts) if year_counts else 1

    students = in_term.filter(year_level=year)
    groups = sorted({g for g in students.values_list("group", flat=True) if g}, key=str.casefold)
    group = request.GET.get("group", "")
    if group:
        students = students.filter(group__iexact=group)
    officer = request.GET.get("officer", "")
    if officer in ("yes", "no"):
        students = students.filter(is_officer=officer == "yes")
    status = request.GET.get("status", "")
    if status in dict(Student.STATUS_CHOICES):
        students = students.filter(status=status)
    q = request.GET.get("q", "").strip()
    if q:
        for word in q.split():
            students = students.filter(
                Q(student_no__icontains=word)
                | Q(last_name__icontains=word)
                | Q(first_name__icontains=word)
                | Q(middle_name__icontains=word)
            )

    page = Paginator(students, 50).get_page(request.GET.get("page"))
    context.update(
        years=years,
        year=year,
        groups=groups,
        group=group,
        officer=officer,
        status=status,
        q=q,
        page=page,
        status_choices=Student.STATUS_CHOICES,
        result_count=page.paginator.count,
    )
    return render(request, "roster/student_list.html", context)


@role_required(*ROSTER_EDITORS)
def import_upload(request):
    form = RosterUploadForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        try:
            roster_import = importer.build_preview(
                form.cleaned_data["term"],
                form.cleaned_data["file"],
                request.user,
                form.cleaned_data["default_year_level"],
            )
        except importer.RosterFileError as exc:
            form.add_error("file", str(exc))
        else:
            return redirect("roster:import_preview", pk=roster_import.pk)
    recent = RosterImport.objects.select_related("term", "uploaded_by")[:10]
    return render(request, "roster/import_upload.html", {"form": form, "recent": recent})


@role_required(*ROSTER_EDITORS)
def import_preview(request, pk):
    roster_import = get_object_or_404(RosterImport.objects.select_related("term"), pk=pk)
    show = request.GET.get("show", "")
    rows = roster_import.rows
    if show in (importer.NEW, importer.CHANGED, importer.UNCHANGED, importer.ERROR):
        rows = [r for r in rows if r["kind"] == show]
    already_applied = (
        RosterImport.objects.filter(
            term=roster_import.term, file_sha256=roster_import.file_sha256, status=RosterImport.APPLIED
        )
        .exclude(pk=roster_import.pk)
        .first()
    )
    return render(
        request,
        "roster/import_preview.html",
        {
            "imp": roster_import,
            "rows": rows,
            "show": show,
            "missing_count": importer.missing_from_file(roster_import).count(),
            "already_applied": already_applied,
            "field_labels": {
                "last_name": "Last name",
                "first_name": "First name",
                "middle_name": "Middle name",
                "year_level": "Year",
                "group": "Group",
                "is_officer": "Officer",
                "status": "Status",
            },
        },
    )


@require_POST
@role_required(*ROSTER_EDITORS)
def import_apply(request, pk):
    roster_import = get_object_or_404(RosterImport, pk=pk)
    try:
        created, updated = importer.apply_import(roster_import)
    except importer.RosterFileError as exc:
        messages.error(request, str(exc))
        return redirect("roster:import_preview", pk=pk)
    skipped = roster_import.error_count
    msg = f"Roster updated: {created} added, {updated} changed."
    if skipped:
        msg += f" {skipped} row(s) with errors were skipped."
    messages.success(request, msg)
    return redirect(f"{reverse('roster:student_list')}?term={roster_import.term_id}")
