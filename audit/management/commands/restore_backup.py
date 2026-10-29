import tempfile
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

from audit.backup import read_backup


class Command(BaseCommand):
    help = "Decrypt a backup to a JSON fixture, or load it into an empty database with --load."

    def add_arguments(self, parser):
        parser.add_argument("file")
        parser.add_argument("--output", help="Write the decrypted JSON fixture here.")
        parser.add_argument("--load", action="store_true", help="Load the backup into the (freshly migrated) database.")

    def handle(self, *args, **options):
        data = read_backup(options["file"])
        if options["output"]:
            Path(options["output"]).write_bytes(data)
            self.stdout.write(f"Decrypted fixture written to {options['output']}")
        if options["load"]:
            with tempfile.NamedTemporaryFile(suffix=".json") as f:
                f.write(data)
                f.flush()
                call_command("loaddata", f.name, stdout=self.stdout)
        if not options["output"] and not options["load"]:
            raise CommandError("Pass --output FILE and/or --load. The backup was decrypted successfully.")
