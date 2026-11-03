"""Encrypted database backups.

A backup is the whole database as a Django JSON fixture, gzipped and then
encrypted with Fernet (AES-128-CBC with an HMAC) using the key in
DUESTRACK_BACKUP_KEY. Without the key a backup cannot be read, so keep a
copy of the key somewhere other than the server.
"""

import base64
import gzip
import hashlib
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
# Downloaded backups are locked with a password the treasurer types instead of the server key:
# MAGIC + 16-byte salt + Fernet token, with the Fernet key derived from the password by scrypt.
MAGIC = b"DUESTRACK-PW1\n"
MIN_PASSPHRASE = 10


def _passphrase_key(passphrase, salt):
    raw = hashlib.scrypt(passphrase.encode("utf-8"), salt=salt, n=2**15, r=8, p=1, maxmem=64 * 1024 * 1024, dklen=32)
    return base64.urlsafe_b64encode(raw)


def passphrase_backup(passphrase):
    """The whole database, gzipped and encrypted with a password, as bytes for download."""
    salt = os.urandom(16)
    return MAGIC + salt + Fernet(_passphrase_key(passphrase, salt)).encrypt(gzip.compress(dump_database()))


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


def is_passphrase_backup(path):
    with open(path, "rb") as f:
        return f.read(len(MAGIC)) == MAGIC


def read_backup(path, key=None, passphrase=None):
    """Decrypt a backup file (server key, or the password of a downloaded one) and return the JSON fixture."""
    blob = Path(path).read_bytes()
    if blob.startswith(MAGIC):
        if not passphrase:
            raise CommandError("This is a downloaded backup: give the password it was downloaded with.")
        salt, token = blob[len(MAGIC) : len(MAGIC) + 16], blob[len(MAGIC) + 16 :]
        try:
            return gzip.decompress(Fernet(_passphrase_key(passphrase, salt)).decrypt(token))
        except InvalidToken as exc:
            raise CommandError("Wrong password for this backup.") from exc
    try:
        return gzip.decompress(fernet(key).decrypt(blob))
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
