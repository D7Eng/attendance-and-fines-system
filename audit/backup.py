"""Encrypted database backups.

A backup is the whole database as a Django JSON fixture, gzipped and then
encrypted with Fernet (AES-128-CBC with an HMAC) using the key in
DUESTRACK_BACKUP_KEY. Without the key a backup cannot be read, so keep a
copy of the key somewhere other than the server.
"""

import gzip
import io
import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone

EXCLUDE = ["contenttypes", "auth.permission", "sessions.session"]
SUFFIX = ".json.gz.enc"


def fernet(key=None):
    key = key or settings.DUESTRACK_BACKUP_KEY
    if not key:
        raise CommandError("Set DUESTRACK_BACKUP_KEY (make one with: manage.py make_backup_key).")
    try:
        return Fernet(key)
    except (ValueError, TypeError) as exc:
        raise CommandError("DUESTRACK_BACKUP_KEY is not a valid key.") from exc


def dump_database():
    out = io.StringIO()
    call_command("dumpdata", exclude=EXCLUDE, natural_foreign=True, natural_primary=True, indent=None, stdout=out)
    return out.getvalue().encode("utf-8")


def write_backup(directory=None, key=None):
    """Write one encrypted backup file and return its path."""
    directory = Path(directory or settings.DUESTRACK_BACKUP_DIR)
    directory.mkdir(parents=True, exist_ok=True)
    token = fernet(key).encrypt(gzip.compress(dump_database()))
    path = directory / f"duestrack-{timezone.localtime():%Y%m%d-%H%M%S}{SUFFIX}"
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(token)
    return path


def read_backup(path, key=None):
    """Decrypt a backup file and return the JSON fixture bytes."""
    try:
        return gzip.decompress(fernet(key).decrypt(Path(path).read_bytes()))
    except InvalidToken as exc:
        raise CommandError("This backup cannot be decrypted with the given key.") from exc


def prune(directory, keep_days):
    """Delete backup files older than keep_days. Only runs when asked; nothing is pruned by default."""
    cutoff = timezone.now().timestamp() - keep_days * 86400
    removed = []
    for path in Path(directory).glob(f"duestrack-*{SUFFIX}"):
        if path.stat().st_mtime < cutoff:
            path.unlink()
            removed.append(path)
    return removed
