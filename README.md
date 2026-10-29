# DuesTrack

Attendance, fines, weekly dues and payments for a student organization, one term at a time.
Django 5.2 on Python 3.13.

## Status

- Milestone 1: term setup with configurable fine and dues rates, roles, roster import
  (CSV or Excel, with preview), and the per-year student list.
- Milestone 2: student logins by student number, temporary passwords with forced change, login lockout.
- Milestone 3: events, the attendance grid, and QR scanner imports.
- Milestone 4: fines, waivers, dues, payments with receipts, refunds and reversals.
- Milestone 5: dashboard, printable reports with CSV export, statements, and student self-service.
- Milestone 6: audit log, settings screen, encrypted backups, privacy notice, deployment files.

## Run it locally

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Log in, give staff users a role in Setup (`/admin/`) by adding them to one of the groups **Admin**,
**Treasurer** or **Officer**, create a term under **Settings**, then import the roster under **Import roster**.
Students get the **Student** role automatically when their login is created.

Run the tests with `python manage.py test`.

## Roles

| | Admin | Treasurer | Officer | Student |
| --- | --- | --- | --- |
| Roster list | yes | yes | yes | no |
| Roster import, student logins | yes | yes | no | no |
| Events, attendance grid, QR import | yes | yes | yes | no |
| Dashboard | yes | yes | yes, without money | no |
| Balances, payments, receipts, reports | view | yes | no | own record and receipts only |
| Take payments, refunds, reversals, waivers | no | yes | no | no |
| Settings (terms, rates, dues by group) | yes | yes | no | no |
| Audit log | yes | yes | no | no |

A superuser counts as Admin. Setup (`/admin/`) is for user accounts; money and audit records are read-only
there.

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

## Fines, dues and payments

Fines are worked out from the attendance marks whenever a balance is shown, never stored, so fixing a mark,
adding a waiver or changing a rate is reflected everywhere at once. For each event dated today or earlier
that a student is expected at:

    fine = missing IN/OUT marks × absence rate + uniform violations × (absence rate + uniform extra)

with the officer or regular rates of the term. Dues are the student's weekly rate × the term's weeks.
Students who are not enrolled owe no fines and no dues.

    balance = fines (not waived) + dues − payments + refunds

- **Waivers** (Treasurer) excuse one student from all of one event's fines, with a reason. Revoking a waiver
  keeps it on record.
- **Payments** (Treasurer) are cash or GCash. A payment above the balance is rejected. A GCash payment needs
  its reference number, which can be used once per term (spaces and dashes are ignored). There is no
  screenshot upload. Each payment gets the next official receipt number, `OR-00001`, `OR-00002`, ..., and a
  printable receipt showing the balance after it.
- **Refunds** return money a student overpaid, for example after a waiver or after they stopped being
  enrolled. A refund can be at most the student's credit. Refunds are numbered `RF-00001`, ...
- **Reversals** void a payment or refund entered by mistake. The entry stays on record, marked reversed with
  the reason, and no longer counts. Its receipt number is not reused, and its GCash reference can be used
  again on the corrected entry.

Payments, waivers and receipts are never deleted; Setup shows them read-only. Officers cannot see payments.
Admins can view balances and payments but only Treasurers change them.

## Dashboard, reports and statements

- **Dashboard** (Officers, Treasurers, Admins): totals for the term and by year level, and attendance for
  recent events. Money figures are shown to Treasurers and Admins only.
- **Balances report**: each student's absences, uniform violations, fines, dues, payments and balance,
  filtered by year, group, and owing or in credit.
- **Collections report**: payments and refunds in a date range with daily and per-method totals.
- **Event report**: who missed which marks at one event (fines shown to Treasurers and Admins only).
- **Statement of account** for one student: every event with its missing marks and fine, dues, payments,
  and balance.

Every report prints on US Letter (`@page size: letter`) without the navigation, and downloads as CSV.

**Students** see only **My record**: their own statement for each term they were on the roster, with
links to their own receipts. Every other page returns 403 for them.

`python manage.py fine_totals [--term NAME|ID] [--as-of YYYY-MM-DD]` prints fine and dues totals per year
level from the command line, for checking against the old spreadsheet.

## Term rates

Every term carries its own rules, edited under **Settings** (Treasurer or Admin). Changes are logged.

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

## Audit log

Logins (and failed logins), logouts, password changes, temporary passwords, roster imports, event changes,
attendance edits (with each student's before and after), QR scan imports, payments, refunds, reversals,
waivers, settings changes and backups are written to the audit log with the user, time and address. Entries
cannot be edited or deleted, in the app or in Setup. Treasurers and Admins can search it under **Audit log**.

## Records and privacy

Nothing is deleted automatically. Payments, refunds, waivers and audit entries cannot be deleted at all;
mistakes are reversed or revoked and stay on record. Roster records, events with attendance and terms are
protected from deletion while anything refers to them.

Every page needs a login except the login page and the privacy notice (`/privacy/`), which explains under
RA 10173 what is kept, why, who can see it, how long, and how to exercise data subject rights. Set
`DUESTRACK_ORG_NAME` and `DUESTRACK_PRIVACY_CONTACT` to fill in the organization and contact. Pages carry
`noindex`. Sessions end when the browser closes or after 8 hours.

## Backups

`python manage.py backup` writes the whole database as a gzipped JSON fixture encrypted with Fernet (AES
with an HMAC) to `DUESTRACK_BACKUP_DIR`, readable only by the app user. Make the key once with
`python manage.py make_backup_key`, put it in `DUESTRACK_BACKUP_KEY`, and keep a copy off the server:
without it the backups cannot be read. Old backups are kept unless you pass `--keep-days N`. Copy the backup
folder off the server too (for example with `rclone` to cloud storage).

To restore into a fresh database: `python manage.py migrate`, then
`python manage.py restore_backup FILE --load`. `--output data.json` only decrypts it.

## Production

`deploy/` has a systemd unit for gunicorn, a daily backup timer, an nginx site with HTTPS (certbot), and an
example environment file. On a VPS (a Singapore region keeps latency low from the Philippines):

```bash
sudo useradd --system --home /srv/duestrack duestrack
# copy the code to /srv/duestrack, then as duestrack:
python3.13 -m venv .venv && .venv/bin/pip install -r requirements.txt
sudo cp deploy/duestrack.env.example /etc/duestrack.env   # fill it in, chmod 640
set -a; . /etc/duestrack.env; set +a
.venv/bin/python manage.py migrate && .venv/bin/python manage.py collectstatic --noinput
.venv/bin/python manage.py createsuperuser
sudo cp deploy/duestrack*.service deploy/duestrack-backup.timer /etc/systemd/system/
sudo systemctl enable --now duestrack duestrack-backup.timer
sudo cp deploy/nginx.conf /etc/nginx/sites-available/duestrack   # set your domain, then certbot --nginx
```

With `DJANGO_DEBUG=0` the app requires `DJANGO_SECRET_KEY`, redirects to HTTPS, sends HSTS, and marks
cookies secure. It reads the client address from nginx's `X-Real-IP` for lockouts and the audit log.
