import datetime

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db.models import Q, Sum
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from accounts import roles
from accounts.roles import FINANCE_EDITORS, FINANCE_VIEWERS, role_required
from events.models import Event
from roster.models import Student
from terms.models import Term

from . import services
from .forms import PaymentForm, ReasonForm, RefundForm
from .ledger import account_for
from .models import Payment, Waiver


def _selected_term(request):
    term_id = request.GET.get("term")
    if term_id and term_id.isdigit():
        return Term.objects.filter(pk=term_id).first()
    return Term.objects.active() or Term.objects.first()


def _parse_date(value):
    try:
        return datetime.date.fromisoformat(value)
    except (TypeError, ValueError):
        return None


@role_required(*FINANCE_VIEWERS)
def payment_list(request):
    term = _selected_term(request)
    context = {"term": term, "terms": Term.objects.all()}
    if term is None:
        return render(request, "finance/payment_list.html", context)

    find = request.GET.get("find", "").strip()
    found = []
    if find:
        found = Student.objects.filter(term=term)
        for word in find.split():
            found = found.filter(
                Q(student_no__icontains=word) | Q(last_name__icontains=word) | Q(first_name__icontains=word)
            )
        found = list(found[:20])
        if len(found) == 1:
            return redirect("finance:account", pk=found[0].pk)

    payments = Payment.objects.filter(term=term).select_related("student", "recorded_by")
    start, end = _parse_date(request.GET.get("from")), _parse_date(request.GET.get("to"))
    if start:
        payments = payments.filter(recorded_at__date__gte=start)
    if end:
        payments = payments.filter(recorded_at__date__lte=end)
    method = request.GET.get("method", "")
    if method in dict(Payment.METHOD_CHOICES):
        payments = payments.filter(method=method)
    active = payments.filter(reversed_at__isnull=True)
    totals = {
        "collected": active.filter(kind=Payment.PAYMENT).aggregate(t=Sum("amount"))["t"] or 0,
        "refunded": active.filter(kind=Payment.REFUND).aggregate(t=Sum("amount"))["t"] or 0,
    }
    context.update(
        find=find,
        found=found,
        page=Paginator(payments, 50).get_page(request.GET.get("page")),
        start=start,
        end=end,
        method=method,
        methods=Payment.METHOD_CHOICES,
        totals=totals,
    )
    return render(request, "finance/payment_list.html", context)


@role_required(*FINANCE_VIEWERS)
def account(request, pk):
    student = get_object_or_404(Student.objects.select_related("term"), pk=pk)
    acct = account_for(student)
    return render(
        request,
        "finance/account.html",
        {
            "student": student,
            "acct": acct,
            "payments": student.payments.select_related("recorded_by", "reversed_by"),
            "waivers": Waiver.objects.filter(student=student).select_related("event", "created_by", "revoked_by"),
        },
    )


@role_required(*FINANCE_EDITORS)
def record_payment(request, pk):
    student = get_object_or_404(Student.objects.select_related("term"), pk=pk)
    acct = account_for(student)
    form = PaymentForm(request.POST or None, initial={"amount": acct.balance if acct.balance > 0 else None})
    if request.method == "POST" and form.is_valid():
        try:
            payment = services.record_payment(student, user=request.user, **form.cleaned_data)
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            messages.success(request, f"Payment recorded: {payment.receipt_no}.")
            return redirect("finance:receipt", pk=payment.pk)
    return render(request, "finance/payment_form.html", {"student": student, "acct": acct, "form": form})


@role_required(*FINANCE_EDITORS)
def record_refund(request, pk):
    student = get_object_or_404(Student.objects.select_related("term"), pk=pk)
    acct = account_for(student)
    form = RefundForm(request.POST or None, initial={"amount": acct.credit or None})
    if request.method == "POST" and form.is_valid():
        try:
            refund = services.record_refund(student, user=request.user, **form.cleaned_data)
        except ValidationError as exc:
            form.add_error(None, exc)
        else:
            messages.success(request, f"Refund recorded: {refund.receipt_no}.")
            return redirect("finance:receipt", pk=refund.pk)
    return render(request, "finance/refund_form.html", {"student": student, "acct": acct, "form": form})


@role_required(*FINANCE_EDITORS)
def reverse_payment(request, pk):
    payment = get_object_or_404(Payment.objects.select_related("student"), pk=pk)
    form = ReasonForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        try:
            services.reverse_payment(payment, request.user, form.cleaned_data["reason"])
        except ValidationError as exc:
            messages.error(request, exc.messages[0])
        else:
            messages.success(request, f"{payment.receipt_no} reversed. It stays on record marked as reversed.")
        return redirect("finance:account", pk=payment.student_id)
    return render(request, "finance/reverse_form.html", {"payment": payment, "form": form})


@login_required
def receipt(request, pk):
    payment = get_object_or_404(Payment.objects.select_related("student", "term", "recorded_by"), pk=pk)
    is_own = payment.student.user_id == request.user.pk
    if not (roles.has_role(request.user, *FINANCE_VIEWERS) or is_own):
        raise PermissionDenied
    return render(request, "finance/receipt.html", {"p": payment})


@require_POST
@role_required(*FINANCE_EDITORS)
def waive(request, pk, event_pk):
    student = get_object_or_404(Student, pk=pk)
    event = get_object_or_404(Event, pk=event_pk)
    try:
        services.waive(event, student, request.user, request.POST.get("reason", ""))
    except ValidationError as exc:
        messages.error(request, exc.messages[0])
    else:
        messages.success(request, f"Fines for {event.name} waived.")
    return redirect("finance:account", pk=pk)


@require_POST
@role_required(*FINANCE_EDITORS)
def revoke_waiver(request, pk):
    waiver = get_object_or_404(Waiver, pk=pk)
    try:
        services.revoke_waiver(waiver, request.user)
    except ValidationError as exc:
        messages.error(request, exc.messages[0])
    else:
        messages.success(request, "Waiver revoked; the fines apply again.")
    return redirect("finance:account", pk=waiver.student_id)
