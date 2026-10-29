# DuesTrack

Attendance, fines, weekly dues and payments for a student organization, one term at a time.
Django 5.2 on Python 3.13.

## Status

- Milestone 1: term setup with configurable fine and dues rates, roles, roster import
  (CSV or Excel, with preview), and the per-year student list.
- Milestone 2: student logins by student number, temporary passwords with forced change, login lockout.
- Milestone 3: events, the attendance grid, and QR scanner imports.

## Run it locally

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Log in at `/admin/`, create a term (Setup → Terms) and give users a role by adding them to one of the
groups **Admin**, **Treasurer**, **Officer** or **Student**. Then open `/students/import/`.

Run the tests with `python manage.py test`.

## Roles

| Role | Roster list | Roster import |
| --- | --- | --- |
| Admin | yes | yes |
| Treasurer | yes | yes |
| Officer | yes | no |
| Student | no (own record only, later milestone) | no |

## Student logins

Open **Logins** (Treasurer or Admin), pick the year, check students and choose **Create logins**. Each new
login uses the student number as its username and gets a 10-character temporary password, shown once on a
printable page of slips. Passwords are stored hashed only, so a lost slip means **Reset passwords**.

A student's first login sends them to change the temporary password before anything else. Usernames are
matched without regard to case. One account serves a student across terms: creating a login for next term's
record links the existing account and keeps its password. After 5 failed attempts for one username from one
address, logins are refused for 15 minutes.

## Events and attendance

An event has a morning session, an afternoon session, or both, and can be limited to some year levels. Each
session has an IN and an OUT mark; every missing mark is fined (milestone 4). Only enrolled students of the
event's year levels are expected. The attendance grid shows one row per expected student with a checkbox per
mark plus a uniform-violation box per session. Officers, Treasurers and Admins can edit it. An event that has
any attendance cannot be deleted.

### QR scanner import

Upload the scanner's CSV or Excel export from an event's page. Recognized columns:

| Field | Header names |
| --- | --- |
| Scanned code | Student No. (and its aliases), Content, Code, Data, QR Code, Text, Barcode, Value |
| Name (fallback) | Name, Full Name, Student Name, or Last Name + First Name |
| When | Timestamp / Date Time, or separate Date and Time |
| IN/OUT (optional) | Type, In/Out, Status, Mode, Action, Direction |

With **automatic** marks, a scan before the term's AM/PM cutoff (12:30 by default) is morning, otherwise
afternoon. An IN/OUT column decides the mark when present; otherwise a student's first scan in a session is
IN and their last later scan is OUT. Or pick one mark (e.g. "PM out") for the whole file.

Scans are matched by student number, including codes that carry extra text such as `2026-0001|CRUZ, ANA`. A
scan that matches only by name is shown for **review** and applied only if ticked. Scans dated on another day
are rejected. Applying only adds marks, never removes them, and keeps the earliest IN and latest OUT time. A
file whose SHA-256 matches one already applied in the term cannot be applied again.

## Term rates

Every term carries its own rules, editable in Setup until the settings page arrives in milestone 6:

- Absence fine per missing IN or OUT mark: 25 regular, 50 officers.
- Uniform violation: one absence charge plus an extra (75 regular, 50 officers), so 100 total by default.
- Weekly dues: 15 for 18 weeks by default. **Dues rates** override this for part of the roster,
  matched by officer status, year level and/or group. When several match, the most specific wins.
- AM/PM cutoff: 12:30.

## Roster file format

One student per row, first sheet of an `.xlsx` or a `.csv` (comma, semicolon or tab). The header row can
sit below title rows. Recognized columns, case-insensitive:

| Field | Header names |
| --- | --- |
| Student number (required) | Student No., Student Number, Student ID, ID Number |
| Last name, first name (required) | Last Name / Surname, First Name / Given Name, or one Name column as "Last, First Middle" |
| Middle name | Middle Name, M.I. |
| Year level | Year, Year Level, Yr (1, 1st, 1st Year, First Year, I). Or pick a year on upload for one-year sheets. |
| Group | Group, Section, Block |
| Officer | Officer (yes/no) or Position (any title such as "President" means officer) |
| Status | Status: Enrolled (default) or Not enrolled / Dropped |

Rows are matched to the term's roster by student number only. The preview shows new, changed, unchanged
and error rows; applying writes only new and changed rows. Students missing from the file are kept.

## Production

Set `DJANGO_DEBUG=0`, `DJANGO_SECRET_KEY`, `DJANGO_ALLOWED_HOSTS`, and `POSTGRES_DB`, `POSTGRES_USER`,
`POSTGRES_PASSWORD`, `POSTGRES_HOST` to use PostgreSQL. Serve with gunicorn behind nginx over HTTPS.
