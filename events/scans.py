"""QR scanner export import.

A scanner export is a CSV or Excel sheet with one scan per row: what the QR
code held (usually the student number) and when it was scanned. Rows are
matched to the roster by student number; when only a name matches, the row
is held for review. Applying only ever adds marks, never removes them, and
the same file cannot be applied twice in a term.
"""

import datetime
import hashlib
import re
from collections import defaultdict

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from roster.importer import HEADER_ALIASES, RosterFileError, _norm_header, read_cells
from roster.models import Student

from .models import AM, MARK_LABELS, MARKS, PM, Attendance, ScanImport

MATCHED = "matched"
ALREADY = "already"
REVIEW = "review"
UNMATCHED = "unmatched"
ERROR = "error"
KINDS = [MATCHED, ALREADY, REVIEW, UNMATCHED, ERROR]

SCAN_ALIASES = {
    "code": HEADER_ALIASES["student_no"]
    | {"content", "data", "code", "qr", "qr code", "qr data", "qr content", "text", "barcode", "value", "scanned data"},
    "name": HEADER_ALIASES["full_name"],
    "last_name": HEADER_ALIASES["last_name"],
    "first_name": HEADER_ALIASES["first_name"],
    "timestamp": {"timestamp", "date time", "datetime", "scan time", "scanned at", "scanned on", "date and time"},
    "date": {"date", "scan date"},
    "time": {"time", "time scanned"},
    "type": {"type", "in out", "status", "mode", "action", "direction", "log type", "attendance"},
}

IN_WORDS = {"in", "time in", "timein", "check in", "login", "log in", "arrival", "entry", "enter"}
OUT_WORDS = {"out", "time out", "timeout", "check out", "logout", "log out", "departure", "exit", "leave"}

DATETIME_FORMATS = [
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%dT%H:%M",
    "%Y/%m/%d %H:%M:%S",
    "%Y/%m/%d %H:%M",
    "%m/%d/%Y %H:%M:%S",
    "%m/%d/%Y %H:%M",
    "%m/%d/%Y %I:%M:%S %p",
    "%m/%d/%Y %I:%M %p",
    "%b %d, %Y %I:%M:%S %p",
    "%b %d, %Y %I:%M %p",
    "%d-%b-%Y %H:%M:%S",
    "%d-%b-%Y %H:%M",
]
DATE_FORMATS = ["%Y-%m-%d", "%Y/%m/%d", "%m/%d/%Y", "%b %d, %Y", "%d-%b-%Y", "%Y-%m-%d %H:%M:%S"]
TIME_FORMATS = ["%H:%M:%S", "%H:%M", "%I:%M:%S %p", "%I:%M %p", "%I:%M%p"]


def _parse(text, formats):
    text = re.sub(r"\.\d+$", "", text.strip())  # drop fractional seconds
    text = re.sub(r"(?i)\s*([ap])\.?m\.?$", lambda m: f" {m.group(1).upper()}M", text)
    for fmt in formats:
        try:
            return datetime.datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def parse_when(timestamp="", date="", time=""):
    """Return (date or None, time or None) from a timestamp or separate date and time cells."""
    if timestamp:
        dt = _parse(timestamp, DATETIME_FORMATS)
        if dt:
            return dt.date(), dt.time()
        t = _parse(timestamp, TIME_FORMATS)
        if t:
            return None, t.time()
        raise ValueError(f"Could not read the scan time '{timestamp}'.")
    day = when = None
    if date:
        parsed = _parse(date, DATE_FORMATS)
        if parsed is None:
            raise ValueError(f"Could not read the scan date '{date}'.")
        day = parsed.date()
    if time:
        parsed = _parse(time, TIME_FORMATS) or _parse(time, DATETIME_FORMATS)
        if parsed is None:
            raise ValueError(f"Could not read the scan time '{time}'.")
        when = parsed.time()
    return day, when


def parse_type(text):
    word = re.sub(r"[^a-z ]+", " ", text.lower()).strip()
    word = re.sub(r"\s+", " ", word)
    if word in IN_WORDS:
        return "in"
    if word in OUT_WORDS:
        return "out"
    return None  # blank or something else, such as "Present": decide from the time


def _name_key(text):
    return " ".join(sorted(re.sub(r"[^a-z ]+", " ", text.casefold().replace(",", " ")).split()))


def map_columns(header):
    mapping = {}
    for index, cell in enumerate(header):
        key = _norm_header(cell)
        for field, aliases in SCAN_ALIASES.items():
            if key in aliases and field not in mapping:
                mapping[field] = index
                break
    return mapping


def split_header(rows):
    """Find the header row (one naming the code column) in the first 10 rows."""
    for i, row in enumerate(rows[:10]):
        mapping = map_columns(row)
        if "code" in mapping or "name" in mapping:
            body = [(n, r) for n, r in enumerate(rows[i + 1 :], start=i + 2) if any(r)]
            return mapping, body
    raise RosterFileError(
        "No header row was found. The file needs a column such as Student No., Content or Code, "
        "and a Timestamp (or Date and Time) column."
    )


class Matcher:
    """Find the roster student for a scanned code or name."""

    def __init__(self, term):
        self.by_no = {}
        self.by_name = defaultdict(list)
        for s in Student.objects.filter(term=term):
            self.by_no[s.student_no.upper()] = s
            self.by_name[_name_key(f"{s.last_name} {s.first_name}")].append(s)
            if s.middle_name:
                self.by_name[_name_key(f"{s.last_name} {s.first_name} {s.middle_name}")].append(s)

    def by_number(self, code):
        code = code.strip().upper()
        if code in self.by_no:
            return self.by_no[code]
        # Codes sometimes carry the name too, e.g. "2026-0001|CRUZ, ANA".
        for token in re.split(r"[|,;\s/]+", code):
            if token in self.by_no:
                return self.by_no[token]
        return None

    def by_full_name(self, name):
        if not name:
            return None
        found = self.by_name.get(_name_key(name), [])
        return found[0] if len(found) == 1 else None


def build_preview(event, uploaded_file, user, mode=ScanImport.AUTO):
    """Parse a scanner export and save a ScanImport preview. Raises RosterFileError."""
    data = uploaded_file.read()
    uploaded_file.seek(0)
    sha256 = hashlib.sha256(data).hexdigest()
    mapping, raw_rows = split_header(read_cells(uploaded_file))
    if len(raw_rows) > settings.ROSTER_MAX_ROWS:
        raise RosterFileError(f"The file has more than {settings.ROSTER_MAX_ROWS} rows.")
    has_time = {"timestamp"} <= mapping.keys() or {"time"} <= mapping.keys()
    if mode == ScanImport.AUTO and not has_time:
        raise RosterFileError("The file has no Timestamp or Time column, so pick which mark the file is for.")

    matcher = Matcher(event.term)
    cutoff = event.term.am_pm_cutoff
    rows = []
    for line, cells in raw_rows:

        def get(field, cells=cells):
            index = mapping.get(field)
            return cells[index] if index is not None and index < len(cells) else ""

        code = get("code")
        name = get("name") or " ".join(p for p in (get("last_name"), get("first_name")) if p)
        row = {"line": line, "code": code, "name": name, "errors": [], "notes": [], "student": None, "mark": None}
        rows.append(row)
        try:
            day, when = parse_when(get("timestamp"), get("date"), get("time"))
            scan_type = parse_type(get("type"))
        except ValueError as exc:
            row["errors"].append(str(exc))
            continue
        row["time"] = when.strftime("%H:%M") if when else ""
        if day and day != event.date:
            row["errors"].append(f"Scanned on {day:%Y-%m-%d}, not the event date {event.date:%Y-%m-%d}.")
            continue

        student = matcher.by_number(code) if code else None
        if student:
            row["kind"] = MATCHED
        else:
            student = matcher.by_full_name(name) or matcher.by_full_name(code)
            row["kind"] = REVIEW if student else UNMATCHED
        if student:
            row["student"] = student.pk
            row["student_label"] = f"{student.student_no} {student.full_name}"
            if not event.applies_to(student):
                row["notes"].append("Not expected at this event (other year level or not enrolled).")

        if mode != ScanImport.AUTO:
            row["mark"] = mode
            continue
        if when is None:
            row["errors"].append("The scan time is missing.")
            continue
        session = AM if when < cutoff else PM
        if session not in event.sessions:
            row["errors"].append(f"Scanned at {when:%H:%M}, but the event has no {session.upper()} session.")
            continue
        row["session"] = session
        row["type"] = scan_type
        if scan_type:
            row["mark"] = MARKS[session][0 if scan_type == "in" else 1]

    if mode == ScanImport.AUTO:
        _assign_in_out(rows)
    _classify(event, rows)
    counts = {kind: sum(1 for r in rows if r["kind"] == kind) for kind in KINDS}
    return ScanImport.objects.create(
        event=event,
        file_name=uploaded_file.name[:255],
        file_sha256=sha256,
        mode=mode,
        uploaded_by=user,
        rows=rows,
        counts=counts,
    )


def _assign_in_out(rows):
    """Without a type column: a student's first scan in a session is IN, the last one (if later) is OUT."""
    groups = defaultdict(list)
    for row in rows:
        if not row["errors"] and row["student"] and row["mark"] is None:
            groups[(row["student"], row["session"])].append(row)
    for (_, session), scans in groups.items():
        scans.sort(key=lambda r: r["time"])
        scans[0]["mark"] = MARKS[session][0]
        if len(scans) > 1 and scans[-1]["time"] > scans[0]["time"]:
            scans[-1]["mark"] = MARKS[session][1]
        for extra in scans[1:]:
            if extra["mark"] is None:
                extra["mark"] = scans[0]["mark"]
                extra["notes"].append("Repeat scan.")


def _classify(event, rows):
    existing = {a.student_id: a for a in Attendance.objects.filter(event=event)}
    for row in rows:
        if row["errors"]:
            row["kind"] = ERROR
        elif row["kind"] == MATCHED:
            attendance = existing.get(row["student"])
            if attendance and getattr(attendance, row["mark"]):
                row["kind"] = ALREADY
        if row.get("mark"):
            row["mark_label"] = MARK_LABELS[row["mark"]]


def already_applied(scan_import):
    """An applied import of the same file anywhere in the term, if any."""
    return (
        ScanImport.objects.filter(
            event__term=scan_import.event.term_id, file_sha256=scan_import.file_sha256, status=ScanImport.APPLIED
        )
        .exclude(pk=scan_import.pk)
        .select_related("event")
        .first()
    )


@transaction.atomic
def apply_import(scan_import, user, accepted_lines=()):
    """Add the marks from matched rows and the review rows the user accepted. Returns marks added."""
    scan_import = ScanImport.objects.select_for_update().get(pk=scan_import.pk)
    if scan_import.status != ScanImport.PREVIEW:
        raise RosterFileError("This file was already applied.")
    duplicate = already_applied(scan_import)
    if duplicate:
        raise RosterFileError(f"This exact file was already applied to {duplicate.event}.")
    accepted_lines = set(accepted_lines)
    event = scan_import.event
    added = 0
    for row in scan_import.rows:
        take = row["kind"] in (MATCHED, ALREADY) or (row["kind"] == REVIEW and row["line"] in accepted_lines)
        if not take or not row.get("mark"):
            continue
        attendance, _ = Attendance.objects.get_or_create(event=event, student_id=row["student"])
        mark = row["mark"]
        changed = False
        if not getattr(attendance, mark):
            setattr(attendance, mark, True)
            added += 1
            changed = True
        old_time = attendance.scan_times.get(mark)
        if row.get("time") and (
            old_time is None or (row["time"] < old_time if mark.endswith("_in") else row["time"] > old_time)
        ):
            attendance.scan_times[mark] = row["time"]
            changed = True
        if changed:
            attendance.updated_by = user
            attendance.save()
    scan_import.status = ScanImport.APPLIED
    scan_import.applied_at = timezone.now()
    scan_import.marks_added = added
    scan_import.save(update_fields=["status", "applied_at", "marks_added"])
    return added
