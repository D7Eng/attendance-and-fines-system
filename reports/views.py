import csv
import datetime

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Sum
from django.db.models.functions import TruncDate
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone

from accounts import roles
from accounts.roles import ATTENDANCE_EDITORS, FINANCE_VIEWERS, role_required
from events.models import Event
from finance.ledger import account_for
from finance.models import Payment
from roster.models import YEAR_LEVEL_CHOICES, Student
from terms.models import Term

from .summary import term_summary

YEARS = dict(YEAR_LEVEL_CHOICES)


def _selected_term(request):
    term_id = request.GET.get("term")
    if term_id and term_id.isdigit():
        return Term.objects.filter(pk=term_id).first()
    return Term.objects.active() or Term.objects.first()


def _int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _date(value):
    try:
        return datetime.date.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def _csv_response(filename, header, rows):
    response = HttpResponse(content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    response.write("﻿")  # so Excel reads UTF-8
    writer = csv.writer(response)
    writer.writerow(header)
    writer.writerows(rows)
    return response


@role_required(*ATTENDANCE_EDITORS)
def dashboard(request):
    term = _selected_term(request)
    context = {"term": term, "terms": Term.objects.all()}
    if term is None:
        return render(request, "reports/dashboard.html", context)
    _, overall, by_year, events = term_summary(term)
    context.update(
        overall=overall,
        by_year=[(y, YEARS[y], t) for y, t in by_year.items()],
        events=events[-10:][::-1],
        today=timezone.localdate(),
    )
    if roles.has_role(request.user, *FINANCE_VIEWERS):
        active = Payment.objects.filter(term=term, reversed_at__isnull=True)
        context["recent"] = Payment.objects.filter(term=term).select_related("student")[:8]
        context["daily"] = (
            active.filter(
                kind=Payment.PAYMENT, recorded_at__date__gte=timezone.localdate() - datetime.timedelta(days=13)
            )
            .annotate(day=TruncDate("recorded_at"))
            .values("day")
            .annotate(total=Sum("amount"), n=Count("id"))
            .order_by("-day")
        )
    return render(request, "reports/dashboard.html", context)


@role_required(*FINANCE_VIEWERS)
def balances(request):
    """Every student's fines, dues, payments and balance, by year and group."""
    term = _selected_term(request)
    if term is None:
        return render(request, "reports/balances.html", {"term": None})
    students = Student.objects.filter(term=term)
    year, group = _int(request.GET.get("year")), request.GET.get("group", "")
    if year:
        students = students.filter(year_level=year)
    if group:
        students = students.filter(group__iexact=group)
    accounts, overall, _, _ = term_summary(term, students)
    show = request.GET.get("show", "")
    rows = [a for a in accounts.values() if a.student.is_enrolled or a.paid]
    if show == "owing":
        rows = [a for a in rows if a.balance > 0]
    elif show == "credit":
        rows = [a for a in rows if a.balance < 0]
    rows.sort(
        key=lambda a: (a.student.year_level, a.student.group.casefold(), a.student.last_name, a.student.first_name)
    )
    if request.GET.get("format") == "csv":
        return _csv_response(
            f"balances-{term.pk}.csv",
            [
                "Student no.",
                "Name",
                "Year",
                "Group",
                "Officer",
                "Absences",
                "Uniform",
                "Fines",
                "Waived",
                "Dues",
                "Paid",
                "Refunded",
                "Balance",
            ],
            [
                [
                    a.student.student_no,
                    a.student.full_name,
                    a.student.year_level,
                    a.student.group,
                    "yes" if a.student.is_officer else "",
                    a.absences,
                    a.uniform_violations,
                    a.fines,
                    a.waived,
                    a.dues,
                    a.paid,
                    a.refunded,
                    a.balance,
                ]
                for a in rows
            ],
        )
    groups = sorted(
        {g for g in Student.objects.filter(term=term).values_list("group", flat=True) if g}, key=str.casefold
    )
    return render(
        request,
        "reports/balances.html",
        {
            "term": term,
            "terms": Term.objects.all(),
            "rows": rows,
            "overall": overall,
            "year": year,
            "group": group,
            "show": show,
            "years": YEAR_LEVEL_CHOICES,
            "groups": groups,
            "printed": timezone.localtime(),
        },
    )


@role_required(*FINANCE_VIEWERS)
def collections(request):
    """Payments and refunds in a date range, with daily and per-method totals."""
    term = _selected_term(request)
    if term is None:
        return render(request, "reports/collections.html", {"term": None})
    today = timezone.localdate()
    start = _date(request.GET.get("from")) or today.replace(day=1)
    end = _date(request.GET.get("to")) or today
    entries = (
        Payment.objects.filter(term=term, recorded_at__date__gte=start, recorded_at__date__lte=end)
        .select_related("student", "recorded_by")
        .order_by("recorded_at", "id")
    )
    active = [p for p in entries if not p.is_reversed]
    by_method = {}
    by_day = {}
    for p in active:
        by_method.setdefault(p.get_method_display(), {"payment": 0, "refund": 0})[p.kind] += p.amount
        day = timezone.localtime(p.recorded_at).date()
        by_day.setdefault(day, {"payment": 0, "refund": 0})[p.kind] += p.amount
    paid = sum((p.amount for p in active if p.kind == Payment.PAYMENT), 0)
    refunded = sum((p.amount for p in active if p.kind == Payment.REFUND), 0)
    if request.GET.get("format") == "csv":
        return _csv_response(
            f"collections-{start}-{end}.csv",
            [
                "Receipt",
                "Date",
                "Student no.",
                "Name",
                "Kind",
                "Method",
                "GCash ref",
                "Amount",
                "Reversed",
                "Recorded by",
            ],
            [
                [
                    p.receipt_no,
                    timezone.localtime(p.recorded_at).strftime("%Y-%m-%d %H:%M"),
                    p.student.student_no,
                    p.student.full_name,
                    p.get_kind_display(),
                    p.get_method_display(),
                    p.gcash_ref,
                    p.amount,
                    "yes" if p.is_reversed else "",
                    p.recorded_by or "",
                ]
                for p in entries
            ],
        )
    return render(
        request,
        "reports/collections.html",
        {
            "term": term,
            "terms": Term.objects.all(),
            "entries": entries,
            "start": start,
            "end": end,
            "paid": paid,
            "refunded": refunded,
            "net": paid - refunded,
            "by_method": by_method,
            "by_day": sorted(by_day.items()),
            "printed": timezone.localtime(),
        },
    )


@role_required(*ATTENDANCE_EDITORS)
def event_report(request, pk):
    """Who missed marks at one event, for posting or checking."""
    event = get_object_or_404(Event.objects.select_related("term"), pk=pk)
    students = event.expected_students()
    year = _int(request.GET.get("year"))
    if year:
        students = students.filter(year_level=year)
    _, _, _, events = term_summary(event.term, students, as_of=max(event.date, timezone.localdate()))
    totals = next(t for t in events if t.event.pk == event.pk)
    show_money = roles.has_role(request.user, *FINANCE_VIEWERS)
    absentees = sorted(totals.absentees, key=lambda pair: (pair[0].year_level, pair[0].group, pair[0].last_name))
    if request.GET.get("format") == "csv":
        header = ["Student no.", "Name", "Year", "Group", "Missing marks", "Uniform violations"]
        if show_money:
            header += ["Fine", "Waived"]
        rows = []
        for s, line in absentees:
            row = [s.student_no, s.full_name, s.year_level, s.group, "; ".join(line.missing_labels), line.uniform]
            if show_money:
                row += [line.amount, "yes" if line.waiver else ""]
            rows.append(row)
        return _csv_response(f"event-{event.pk}.csv", header, rows)
    return render(
        request,
        "reports/event_report.html",
        {
            "event": event,
            "totals": totals,
            "absentees": absentees,
            "show_money": show_money,
            "year": year,
            "years": YEAR_LEVEL_CHOICES,
            "printed": timezone.localtime(),
        },
    )


def _statement_context(student):
    return {
        "student": student,
        "acct": account_for(student, include_clear=True),
        "payments": student.payments.select_related("recorded_by"),
        "printed": timezone.localtime(),
    }


@role_required(*FINANCE_VIEWERS)
def statement(request, pk):
    student = get_object_or_404(Student.objects.select_related("term"), pk=pk)
    return render(request, "reports/statement.html", _statement_context(student))


@login_required
def my_record(request):
    """A student's own statement for one of their terms. Students see nothing else."""
    if not roles.has_role(request.user, roles.STUDENT):
        raise PermissionDenied
    records = list(
        Student.objects.filter(user=request.user).select_related("term").order_by("-term__start_date", "-term_id")
    )
    context = {"records": records}
    if records:
        chosen = _int(request.GET.get("term"))
        active = Term.objects.active()
        student = next((r for r in records if r.term_id == chosen), None) or next(
            (r for r in records if active and r.term_id == active.pk), records[0]
        )
        context.update(_statement_context(student))
    return render(request, "reports/my_record.html", context)
