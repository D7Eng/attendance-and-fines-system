# DuesTrack

Attendance, fines, weekly dues and payments for a student organization, one term at a time.
Django 5.2 on Python 3.13.

## Status

Milestone 1 is in: term setup with configurable fine and dues rates, roles, roster import
(CSV or Excel, with preview), and the per-year student list.

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
