from django.conf import settings
from django.core.management.base import BaseCommand

from audit.backup import prune, write_backup
from audit.log import record


class Command(BaseCommand):
    help = "Write an encrypted backup of the whole database. Run daily from cron or a systemd timer."

    def add_arguments(self, parser):
        parser.add_argument("--dir", help="Folder for backups (default DUESTRACK_BACKUP_DIR).")
        parser.add_argument(
            "--keep-days",
            type=int,
            help="Also delete backup files older than this many days. Without it, every backup is kept.",
        )

    def handle(self, *args, **options):
        directory = options["dir"] or settings.DUESTRACK_BACKUP_DIR
        path = write_backup(directory)
        record("backup", f"Encrypted backup written: {path.name}", size=path.stat().st_size)
        self.stdout.write(f"Backup written: {path}")
        if options["keep_days"]:
            for old in prune(directory, options["keep_days"]):
                self.stdout.write(f"Removed old backup: {old}")
