import getpass
import tempfile
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import BaseCommand, CommandError

from audit.backup import is_passphrase_backup, read_backup


class Command(BaseCommand):
    help = "Decrypt a backup to a JSON fixture, or load it into an empty database with --load."

    def add_arguments(self, parser):
        parser.add_argument("file")
        parser.add_argument("--output", help="Write the decrypted JSON fixture here.")
        parser.add_argument("--load", action="store_true", help="Load the backup into the (freshly migrated) database.")
        parser.add_argument("--password", help="Password of a backup downloaded from the app (asked if not given).")

    def handle(self, *args, **options):
        password = options["password"]
        if is_passphrase_backup(options["file"]) and not password:
            password = getpass.getpass("Backup password: ")
        data = read_backup(options["file"], passphrase=password)
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
