from django.contrib import messages
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from accounts.roles import ATTENDANCE_EDITORS, role_required
from roster.importer import RosterFileError
from roster.models import YEAR_LEVEL_CHOICES
from terms.models import Term

from . import scans
from .forms import EventForm, ScanUploadForm
from .models import MARK_LABELS, UNIFORM, Attendance, Event, ScanImport


def _selected_term(request):
    term_id = request.GET.get("term")
    if term_id and term_id.isdigit():
        return Term.objects.filter(pk=term_id).first()
    return Term.objects.active() or Term.objects.first()


@role_required(*ATTENDANCE_EDITORS)
def event_list(request):
    term = _selected_term(request)
    events = Event.objects.filter(term=term).annotate(scan_count=Count("scan_imports")) if term else []
    return render(request, "events/event_list.html", {"term": term, "terms": Term.objects.all(), "events": events})


@role_required(*ATTENDANCE_EDITORS)
def event_form(request, pk=None):
    event = get_object_or_404(Event, pk=pk) if pk else None
    form = EventForm(request.POST or None, instance=event)
    if request.method == "POST" and form.is_valid():
        event = form.save(commit=False)
        if not event.pk:
            event.created_by = request.user
        event.save()
        messages.success(request, f"Saved {event}.")
        return redirect("events:attendance", pk=event.pk)
    return render(request, "events/event_form.html", {"form": form, "event": event})


@require_POST
@role_required(*ATTENDANCE_EDITORS)
def event_delete(request, pk):
    event = get_object_or_404(Event, pk=pk)
    if event.attendance.exists() or event.scan_imports.exists():
        messages.error(request, "This event already has attendance, so it is kept. Edit it instead.")
        return redirect("events:attendance", pk=pk)
    term_id = event.term_id
    event.delete()
    messages.success(request, "Event deleted.")
    return redirect(f"{reverse('events:event_list')}?term={term_id}")


@role_required(*ATTENDANCE_EDITORS)
def attendance(request, pk):
    """The attendance grid: one row per expected student, one checkbox per mark."""
    event = get_object_or_404(Event.objects.select_related("term"), pk=pk)
    students = event.expected_students()
    years = sorted(set(students.values_list("year_level", flat=True)))
    try:
        year = int(request.GET.get("year", ""))
    except ValueError:
        year = None
    if year not in years:
        year = years[0] if years else None
    students = students.filter(year_level=year)
    groups = sorted({g for g in students.values_list("group", flat=True) if g}, key=str.casefold)
    group = request.GET.get("group", "")
    if group:
        students = students.filter(group__iexact=group)
    q = request.GET.get("q", "").strip()
    for word in q.split():
        students = students.filter(
            Q(student_no__icontains=word) | Q(last_name__icontains=word) | Q(first_name__icontains=word)
        )
    students = list(students)
    fields = event.mark_fields + event.uniform_fields
    existing = {a.student_id: a for a in Attendance.objects.filter(event=event, student__in=students)}

    if request.method == "POST":
        shown = {int(i) for i in request.POST.getlist("shown") if i.isdigit()}
        changed = 0
        for student in students:
            if student.pk not in shown:
                continue
            values = {f: f"{f}-{student.pk}" in request.POST for f in fields}
            row = existing.get(student.pk)
            if row is None:
                if not any(values.values()):
                    continue
                row = Attendance(event=event, student=student)
            elif all(getattr(row, f) == v for f, v in values.items()):
                continue
            for f, v in values.items():
                setattr(row, f, v)
            row.updated_by = request.user
            row.save()
            changed += 1
        messages.success(request, f"Attendance saved ({changed} student{'s' if changed != 1 else ''} changed).")
        return redirect(request.get_full_path())

    rows = []
    for student in students:
        row = existing.get(student.pk)
        rows.append(
            {
                "student": student,
                "cells": [(f, bool(row and getattr(row, f))) for f in fields],
                "missing": row.missing_marks(event) if row else len(event.mark_fields),
                "times": row.scan_times if row else {},
            }
        )
    labels = {**MARK_LABELS, **{v: f"{k.upper()} uniform" for k, v in UNIFORM.items()}}
    return render(
        request,
        "events/attendance.html",
        {
            "event": event,
            "rows": rows,
            "columns": [(f, labels[f], f in event.uniform_fields) for f in fields],
            "years": [(y, dict(YEAR_LEVEL_CHOICES)[y]) for y in years],
            "year": year,
            "groups": groups,
            "group": group,
            "q": q,
            "imports": event.scan_imports.select_related("uploaded_by")[:10],
        },
    )


@role_required(*ATTENDANCE_EDITORS)
def scan_upload(request, pk):
    event = get_object_or_404(Event.objects.select_related("term"), pk=pk)
    form = ScanUploadForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        try:
            scan_import = scans.build_preview(event, form.cleaned_data["file"], request.user, form.cleaned_data["mode"])
        except RosterFileError as exc:
            form.add_error("file", str(exc))
        else:
            return redirect("events:scan_preview", pk=scan_import.pk)
    return render(request, "events/scan_upload.html", {"event": event, "form": form})


@role_required(*ATTENDANCE_EDITORS)
def scan_preview(request, pk):
    scan_import = get_object_or_404(ScanImport.objects.select_related("event__term"), pk=pk)
    show = request.GET.get("show", "")
    rows = scan_import.rows
    if show in scans.KINDS:
        rows = [r for r in rows if r["kind"] == show]
    return render(
        request,
        "events/scan_preview.html",
        {
            "imp": scan_import,
            "event": scan_import.event,
            "rows": rows,
            "show": show,
            "kinds": [(k, scan_import.counts.get(k, 0)) for k in scans.KINDS],
            "already_applied": scans.already_applied(scan_import),
        },
    )


@require_POST
@role_required(*ATTENDANCE_EDITORS)
def scan_apply(request, pk):
    scan_import = get_object_or_404(ScanImport, pk=pk)
    accepted = [int(n) for n in request.POST.getlist("accept") if n.isdigit()]
    try:
        added = scans.apply_import(scan_import, request.user, accepted)
    except RosterFileError as exc:
        messages.error(request, str(exc))
        return redirect("events:scan_preview", pk=pk)
    messages.success(request, f"Scans applied: {added} mark{'s' if added != 1 else ''} added. No marks were removed.")
    return redirect("events:attendance", pk=scan_import.event_id)
