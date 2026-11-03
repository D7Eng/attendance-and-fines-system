from django.core.management.base import BaseCommand, CommandError

from reports.summary import term_summary
from terms.models import Term


class Command(BaseCommand):
    help = "Print fine and dues totals per year level for a term (default: the active term)."

    def add_arguments(self, parser):
        parser.add_argument("--term", help="Term name or id.")
        parser.add_argument("--as-of", help="Count events up to this date (YYYY-MM-DD); default today.")

    def handle(self, *args, **options):
        import datetime

        term_arg = options["term"]
        if term_arg:
            term = Term.objects.filter(pk=term_arg).first() if term_arg.isdigit() else None
            term = term or Term.objects.filter(name=term_arg).first()
        else:
            term = Term.objects.active()
        if term is None:
            raise CommandError("Term not found.")
        as_of = datetime.date.fromisoformat(options["as_of"]) if options["as_of"] else None
        _, overall, by_year, _ = term_summary(term, as_of=as_of)
        self.stdout.write(f"{term}")
        self.stdout.write(
            f"{'Year':<8}{'Students':>10}{'Absences':>10}{'Uniform':>9}{'Fines':>14}{'Waived':>12}{'Dues':>14}"
        )
        for year, t in by_year.items():
            self.stdout.write(
                f"{year:<8}{t.students:>10}{t.absences:>10}{t.uniform_violations:>9}{t.fines:>14,.2f}{t.waived:>12,.2f}{t.dues:>14,.2f}"
            )
        self.stdout.write(
            f"{'All':<8}{overall.students:>10}{overall.absences:>10}{overall.uniform_violations:>9}"
            f"{overall.fines:>14,.2f}{overall.waived:>12,.2f}{overall.dues:>14,.2f}"
        )
