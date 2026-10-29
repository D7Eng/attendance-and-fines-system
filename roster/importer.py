"""Roster file parsing, validation and preview classification.

A roster file is a CSV or Excel sheet with one student per row. Rows are
matched to the term's existing roster by student number only. Nothing is
written until the treasurer confirms the preview, and students missing
from the file are never removed.
"""

import csv
import hashlib
import io
import re

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from audit.log import record

from .models import RosterImport, Student

NEW = "new"
CHANGED = "changed"
UNCHANGED = "unchanged"
ERROR = "error"

# Fields compared and written on import, in display order.
FIELDS = ["student_no", "last_name", "first_name", "middle_name", "year_level", "group", "is_officer", "status"]

HEADER_ALIASES = {
    "student_no": {"student no", "student number", "student id", "id number", "id no", "stud no", "studentno"},
    "last_name": {"last name", "lastname", "surname", "family name"},
    "first_name": {"first name", "firstname", "given name"},
    "middle_name": {"middle name", "middlename", "middle initial", "mi"},
    "full_name": {"name", "full name", "student name", "fullname"},
    "year_level": {"year", "year level", "yr", "yr level", "level"},
    "group": {"group", "section", "block", "class"},
    "is_officer": {"officer", "is officer", "position", "role"},
    "status": {"status", "enrollment status", "enrolment status", "enrolled"},
}

YEAR_WORDS = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "i": 1, "ii": 2, "iii": 3, "iv": 4, "v": 5}
TRUE_WORDS = {"yes", "y", "true", "1", "officer", "x"}
FALSE_WORDS = {"", "no", "n", "false", "0", "none", "member", "student", "-"}
NOT_ENROLLED_WORDS = {
    "not enrolled",
    "not_enrolled",
    "no",
    "n",
    "dropped",
    "inactive",
    "unenrolled",
    "loa",
    "false",
    "0",
}
ENROLLED_WORDS = {"", "enrolled", "yes", "y", "active", "true", "1", "regular", "irregular"}


class RosterFileError(Exception):
    """The file as a whole cannot be read."""


def _norm_header(value):
    text = str(value or "").lower().replace(".", "")
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def _cell_text(value):
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    return re.sub(r"\s+", " ", str(value)).strip()


def read_table(uploaded_file):
    """Return (header, rows) from a CSV or XLSX upload; rows are (line number, cells)."""
    return _split_header(read_cells(uploaded_file))


def read_cells(uploaded_file):
    """Return every row of a CSV or XLSX upload (first sheet) as lists of cleaned text."""
    name = uploaded_file.name.lower()
    data = uploaded_file.read()
    if name.endswith(".xlsx"):
        return _read_xlsx(data)
    if name.endswith(".csv"):
        return _read_csv(data)
    raise RosterFileError("Upload a .csv or .xlsx file.")


def _read_csv(data):
    for encoding in ("utf-8-sig", "cp1252"):
        try:
            text = data.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise RosterFileError("The CSV file's text encoding could not be read. Save it as UTF-8.")
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    return [[_cell_text(c) for c in row] for row in csv.reader(io.StringIO(text), dialect)]


def _read_xlsx(data):
    from openpyxl import load_workbook

    try:
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception as exc:  # openpyxl raises many types for bad files
        raise RosterFileError("The Excel file could not be opened.") from exc
    try:
        ws = wb.worksheets[0]
        rows = [[_cell_text(c) for c in row] for row in ws.iter_rows(values_only=True)]
    finally:
        wb.close()
    return rows


def _split_header(rows):
    """Find the header row; return it and the non-blank (sheet row number, cells) after it."""
    # The header is the first row that names a student number column.
    for i, row in enumerate(rows[:10]):
        if any(_norm_header(c) in HEADER_ALIASES["student_no"] for c in row):
            body = [(n, r) for n, r in enumerate(rows[i + 1 :], start=i + 2) if any(r)]
            return row, body
    raise RosterFileError("No header row with a student number column was found in the first 10 rows.")


def map_columns(header):
    mapping = {}
    for index, cell in enumerate(header):
        key = _norm_header(cell)
        for field, aliases in HEADER_ALIASES.items():
            if key in aliases and field not in mapping:
                mapping[field] = index
    return mapping


def parse_year_level(value):
    text = value.lower().replace("year", "").replace("yr", "").strip(" .-")
    match = re.match(r"^(\d)(st|nd|rd|th)?$", text)
    if match:
        level = int(match.group(1))
    else:
        level = YEAR_WORDS.get(text)
    if level is None or not 1 <= level <= 5:
        raise ValueError(f"Year level '{value}' is not 1 to 5.")
    return level


def parse_officer(value):
    text = value.lower()
    if text in TRUE_WORDS:
        return True
    if text in FALSE_WORDS:
        return False
    # A position title such as "President" means the student is an officer.
    return True


def parse_status(value):
    text = value.lower().strip()
    if text in ENROLLED_WORDS:
        return Student.ENROLLED
    if text in NOT_ENROLLED_WORDS:
        return Student.NOT_ENROLLED
    raise ValueError(f"Status '{value}' is not Enrolled or Not enrolled.")


def split_full_name(value):
    """Split 'LAST, FIRST MIDDLE' into parts. Without a comma, we cannot tell."""
    if "," not in value:
        raise ValueError("Name must be 'Last, First Middle' or use separate name columns.")
    last, rest = (p.strip() for p in value.split(",", 1))
    return last, rest, ""


def parse_row(cells, mapping, default_year_level=None):
    """Return (values, errors) for one data row."""

    def get(field):
        index = mapping.get(field)
        return cells[index] if index is not None and index < len(cells) else ""

    errors = []
    values = {"student_no": get("student_no").upper()}
    if not values["student_no"]:
        errors.append("Student number is missing.")

    last, first, middle = get("last_name"), get("first_name"), get("middle_name")
    if not (last or first) and get("full_name"):
        try:
            last, first, middle = split_full_name(get("full_name"))
        except ValueError as exc:
            errors.append(str(exc))
    if not last:
        errors.append("Last name is missing.")
    if not first:
        errors.append("First name is missing.")
    values.update(last_name=last, first_name=first, middle_name=middle)

    year_text = get("year_level")
    if year_text:
        try:
            values["year_level"] = parse_year_level(year_text)
        except ValueError as exc:
            errors.append(str(exc))
    elif default_year_level:
        values["year_level"] = default_year_level
    else:
        errors.append("Year level is missing.")

    values["group"] = get("group")
    values["is_officer"] = parse_officer(get("is_officer"))
    try:
        values["status"] = parse_status(get("status"))
    except ValueError as exc:
        errors.append(str(exc))

    for field in ("student_no", "last_name", "first_name", "middle_name", "group"):
        limit = Student._meta.get_field(field).max_length
        if len(values.get(field) or "") > limit:
            errors.append(
                f"{Student._meta.get_field(field).verbose_name.capitalize()} is longer than {limit} characters."
            )
    return values, errors


def student_values(student):
    return {field: getattr(student, field) for field in FIELDS}


def build_preview(term, uploaded_file, user, default_year_level=None):
    """Parse an upload and save a RosterImport preview. Raises RosterFileError."""
    data = uploaded_file.read()
    uploaded_file.seek(0)
    sha256 = hashlib.sha256(data).hexdigest()
    header, raw_rows = read_table(uploaded_file)
    mapping = map_columns(header)
    has_name = {"last_name", "first_name"} <= mapping.keys() or "full_name" in mapping
    if not has_name:
        raise RosterFileError("The file needs Last name and First name columns, or a Name column.")
    if "year_level" not in mapping and not default_year_level:
        raise RosterFileError("The file has no Year column. Pick the year level these students belong to.")
    if len(raw_rows) > settings.ROSTER_MAX_ROWS:
        raise RosterFileError(f"The file has more than {settings.ROSTER_MAX_ROWS} rows.")

    existing = {s.student_no.upper(): s for s in Student.objects.filter(term=term)}
    seen = {}
    rows = []
    counts = {NEW: 0, CHANGED: 0, UNCHANGED: 0, ERROR: 0}
    for line, cells in raw_rows:
        values, errors = parse_row(cells, mapping, default_year_level)
        student_no = values["student_no"]
        if student_no and student_no in seen:
            errors.append(f"Student number is repeated (first seen on row {seen[student_no]}).")
        elif student_no:
            seen[student_no] = line
        row = {"line": line, "values": values, "errors": errors, "changes": {}}
        if errors:
            row["kind"] = ERROR
        elif student_no not in existing:
            row["kind"] = NEW
        else:
            old = student_values(existing[student_no])
            row["changes"] = {f: [old[f], values[f]] for f in FIELDS if f != "student_no" and old[f] != values[f]}
            row["kind"] = CHANGED if row["changes"] else UNCHANGED
        counts[row["kind"]] += 1
        rows.append(row)

    return RosterImport.objects.create(
        term=term,
        file_name=uploaded_file.name[:255],
        file_sha256=sha256,
        uploaded_by=user,
        rows=rows,
        new_count=counts[NEW],
        changed_count=counts[CHANGED],
        unchanged_count=counts[UNCHANGED],
        error_count=counts[ERROR],
    )


def missing_from_file(roster_import):
    """Students on the term's roster that the file does not list (kept, not removed)."""
    listed = {r["values"]["student_no"] for r in roster_import.rows if r["values"].get("student_no")}
    return Student.objects.filter(term=roster_import.term).exclude(student_no__in=listed)


@transaction.atomic
def apply_import(roster_import):
    """Write the previewed new and changed rows. Error rows are skipped."""
    roster_import = RosterImport.objects.select_for_update().get(pk=roster_import.pk)
    if roster_import.status != RosterImport.PREVIEW:
        raise RosterFileError("This import was already applied.")
    created = updated = 0
    for row in roster_import.rows:
        if row["kind"] not in (NEW, CHANGED):
            continue
        values = dict(row["values"])
        student_no = values.pop("student_no")
        _, was_created = Student.objects.update_or_create(
            term=roster_import.term, student_no=student_no, defaults=values
        )
        created += was_created
        updated += not was_created
    roster_import.status = RosterImport.APPLIED
    roster_import.applied_at = timezone.now()
    roster_import.save(update_fields=["status", "applied_at"])
    record(
        "roster_import",
        f"Roster file {roster_import.file_name} applied to {roster_import.term}: {created} added, {updated} changed",
        target=roster_import,
        sha256=roster_import.file_sha256,
        skipped_errors=roster_import.error_count,
    )
    return created, updated
