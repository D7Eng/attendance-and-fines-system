from cryptography.fernet import Fernet
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Print a new key for DUESTRACK_BACKUP_KEY. Store a copy away from the server."

    def handle(self, *args, **options):
        self.stdout.write(Fernet.generate_key().decode())
