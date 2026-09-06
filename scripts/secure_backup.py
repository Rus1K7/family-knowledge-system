"""Local age encryption around the existing PostgreSQL/media backup workflow."""

import argparse
import fcntl
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import uuid
from contextlib import contextmanager, redirect_stdout
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.backup import BackupError, PROJECT, create_backup, digest, run, verify_backup
from scripts.install_age import TARGET


AGE = TARGET / "age"
KEYGEN = TARGET / "age-keygen"
KEY_DIRECTORY = PROJECT / "secrets"
IDENTITY = KEY_DIRECTORY / "backup.agekey"
RECIPIENT = KEY_DIRECTORY / "backup-recipient.txt"
OUTPUT = PROJECT / "backups" / "encrypted"
CONTENTS = {"database.dump", "media.tar", "manifest.json"}


def require_age():
    if not AGE.is_file() or not KEYGEN.is_file():
        raise BackupError("Сначала выполните python3 scripts/install_age.py.")


def read_recipient(path):
    recipient = path.read_text(encoding="ascii").strip()
    # Only native public recipients: no plugin execution or interactive prompts.
    if not re.fullmatch(r"age1[a-z0-9]{58}", recipient):
        raise BackupError("Некорректный открытый ключ резервных копий.")
    return recipient


def initialize_keys(directory):
    require_age()
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    identity = directory / "backup.agekey"
    recipient_path = directory / "backup-recipient.txt"
    if recipient_path.exists() and not identity.exists():
        raise BackupError("Открытый ключ уже существует; верните исходный ключ восстановления.")
    if not identity.exists():
        with tempfile.TemporaryDirectory(prefix=".backup-key-", dir=directory) as temporary:
            staged = Path(temporary) / "identity"
            with staged.open("xb") as output:
                run([str(KEYGEN)], stdout=output)
            staged.chmod(0o600)
            # Never replace an existing recovery key, including a concurrent init.
            os.link(staged, identity)
    recipient = run([str(KEYGEN), "-y", str(identity)]).decode("ascii").strip()
    if recipient_path.exists():
        if read_recipient(recipient_path) != recipient:
            raise BackupError("Открытый ключ не соответствует ключу восстановления.")
    else:
        with recipient_path.open("x", encoding="ascii") as output:
            output.write(recipient + "\n")
    identity.chmod(0o600)
    recipient_path.chmod(0o600)
    print(f"Ключ восстановления сохранён: {identity}")
    print("Содержимое ключа не выводится. Сохраните его отдельно: без него восстановление невозможно.")


def encrypt_backup(backup, recipient, target):
    """Encrypt a tar stream; no second unencrypted tar file is needed."""
    with target.open("xb") as encrypted, tempfile.TemporaryFile() as errors:
        process = subprocess.Popen(
            [str(AGE), "--encrypt", "--recipient", recipient],
            stdin=subprocess.PIPE, stdout=encrypted, stderr=errors,
        )
        try:
            with tarfile.open(fileobj=process.stdin, mode="w|") as archive:
                for name in sorted(CONTENTS):
                    source_path = backup / name
                    info = tarfile.TarInfo(name)
                    info.size = source_path.stat().st_size
                    info.mode = 0o600
                    with source_path.open("rb") as source:
                        archive.addfile(info, source)
            process.stdin.close()
            if process.wait(timeout=120):
                raise BackupError("Шифрование age не завершилось.")
            encrypted.flush()
            os.fsync(encrypted.fileno())
        finally:
            if not process.stdin.closed:
                try:
                    process.stdin.close()
                except BrokenPipeError:
                    pass
            if process.poll() is None:
                process.kill()
                process.wait(timeout=10)
    target.chmod(0o600)


@contextmanager
def backup_lock(output):
    output.mkdir(mode=0o700, parents=True, exist_ok=True)
    with (output / ".run.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise BackupError("Другая зашифрованная копия уже создаётся.") from error
        try:
            yield
        finally:
            fcntl.flock(lock, fcntl.LOCK_UN)


def matching_daily_backup(output, date, recipient):
    state_path = output / ".daily.json"
    if not state_path.exists():
        return None
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
        name = state["archive"]
        if (
            state["date"] != date or state["recipient"] != recipient
            or not re.fullmatch(r"fks-\d{8}T\d{6}Z-[0-9a-f]{8}\.tar\.age", name)
        ):
            return None
        archive = output / name
        if archive.is_file() and not archive.is_symlink() and digest(archive) == state["sha256"]:
            return archive
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return None


def create_encrypted(output=OUTPUT, recipient_path=RECIPIENT, *, daily=False):
    require_age()
    recipient = read_recipient(recipient_path)
    date = datetime.now(ZoneInfo("Europe/Moscow")).date().isoformat()
    with backup_lock(output):
        if daily:
            previous = matching_daily_backup(output, date, recipient)
            if previous is not None:
                print(f"За сегодня копия уже создана и её целостность подтверждена: {previous}")
                return previous
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        final = output / f"fks-{stamp}-{uuid.uuid4().hex[:8]}.tar.age"
        with tempfile.TemporaryDirectory(prefix=".secure-", dir=output) as temporary:
            temporary = Path(temporary)
            with redirect_stdout(io.StringIO()):
                backup = create_backup(temporary / "raw")
            encrypted = temporary / "encrypted.age"
            encrypt_backup(backup, recipient, encrypted)
            checksum = digest(encrypted)
            os.link(encrypted, final)
            state = {
                "date": date, "archive": final.name,
                "sha256": checksum, "recipient": recipient,
            }
            marker = temporary / "daily.json"
            marker.write_text(json.dumps(state) + "\n", encoding="utf-8")
            marker.chmod(0o600)
            marker.replace(output / ".daily.json")
        print(f"Создана зашифрованная копия: {final}")
        print("Временные незашифрованные файлы этого запуска удалены.")
        return final


def decrypt_backup(archive, identity, destination):
    # Authenticate the COMPLETE age stream before parsing or restoring plaintext.
    with tempfile.TemporaryDirectory(prefix=".decrypt-", dir=destination.parent) as temporary:
        plaintext = Path(temporary) / "backup.tar"
        with plaintext.open("xb") as output:
            try:
                run([str(AGE), "--decrypt", "--identity", str(identity), str(archive)], stdout=output)
            except BackupError as error:
                raise BackupError("Не удалось расшифровать копию: проверьте ключ и целостность файла.") from error
        destination.mkdir(mode=0o700)
        seen = set()
        with tarfile.open(plaintext, "r|") as restored:
            for entry in restored:
                if entry.name not in CONTENTS or entry.name in seen or not entry.isfile() or entry.sparse is not None:
                    raise BackupError("Неожиданный состав расшифрованной копии.")
                with restored.extractfile(entry) as source, (destination / entry.name).open("xb") as target:
                    shutil.copyfileobj(source, target)
                (destination / entry.name).chmod(0o600)
                seen.add(entry.name)
        if seen != CONTENTS:
            raise BackupError("В расшифрованной копии отсутствуют обязательные файлы.")


def verify_encrypted(archive, identity=IDENTITY):
    require_age()
    with tempfile.TemporaryDirectory(prefix="fks-decrypted-check-") as temporary:
        backup = Path(temporary) / "backup"
        decrypt_backup(archive, identity, backup)
        verify_backup(backup)
    print("Зашифрованная копия успешно расшифрована и восстановлена в отдельном окружении.")


def main():
    parser = argparse.ArgumentParser(description="Зашифрованные локальные резервные копии")
    commands = parser.add_subparsers(dest="action", required=True)
    commands.add_parser("init", help="создать ключи без перезаписи существующих")
    create = commands.add_parser("create", help="создать зашифрованную копию")
    create.add_argument("--daily", action="store_true", help="не повторять успешное копирование за сегодня")
    verify = commands.add_parser("verify", help="проверить расшифровку и полное восстановление")
    verify.add_argument("archive", type=Path)
    verify.add_argument("--identity", type=Path, default=IDENTITY)
    args = parser.parse_args()
    os.umask(0o077)
    try:
        if args.action == "init":
            initialize_keys(KEY_DIRECTORY)
        elif args.action == "create":
            create_encrypted(daily=args.daily)
        else:
            verify_encrypted(args.archive.resolve(), args.identity.resolve())
    except (BackupError, OSError, ValueError, KeyError, TypeError, tarfile.TarError, subprocess.TimeoutExpired) as error:
        parser.exit(1, f"Операция не завершена: {error}\n")


if __name__ == "__main__":
    main()
