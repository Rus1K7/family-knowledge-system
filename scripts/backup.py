"""Compose backups and isolated restore drills. Python 3.11+, stdlib only."""

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath


PROJECT = Path(__file__).resolve().parents[1]
COMPOSE = ["docker", "compose"]
OUTPUT = PROJECT / "backups"
PRODUCTION_OUTPUT = OUTPUT / "production"
COMPOSE_SOURCE_VARIABLES = (
    "COMPOSE_PROJECT_NAME", "COMPOSE_FILE", "COMPOSE_PROFILES",
    "COMPOSE_ENV_FILES", "COMPOSE_DISABLE_ENV_FILE",
)
IDENTIFIER = re.compile(r"[a-z_][a-z0-9_]*\Z")


class BackupError(Exception):
    def __init__(self, message, *, diagnostic=b""):
        super().__init__(message)
        self.diagnostic = diagnostic


def run(args, *, stdin=None, stdout=subprocess.PIPE, timeout=300):
    result = subprocess.run(
        args, cwd=PROJECT, stdin=stdin, stdout=stdout, stderr=subprocess.PIPE,
        timeout=timeout, check=False,
    )
    if result.returncode:
        # Database errors can contain private row values. Don't print them.
        operation = next((item for item in args if item in {"pg_dump", "pg_restore", "psql"}), args[0])
        raise BackupError(
            f"Не выполнена команда {operation} (код {result.returncode}).",
            diagnostic=result.stderr,
        )
    return result.stdout


def compose_command(*, production=False):
    if production:
        return COMPOSE + ["-p", "family-production", "-f", "compose.production.yaml"]
    return list(COMPOSE)


def backup_source(*, production=False):
    """Record routing context, never configuration contents or credentials."""
    try:
        daemon_id = run(["docker", "info", "--format", "{{.ID}}"], timeout=10).strip()
    except (BackupError, OSError, subprocess.TimeoutExpired) as error:
        raise BackupError("Не удалось определить источник Docker. Проверьте выбранный сервер и соединение.") from error
    if not re.fullmatch(rb"[A-Za-z0-9][A-Za-z0-9:-]{7,127}", daemon_id):
        raise BackupError("Docker не вернул идентификатор источника; копирование не подтверждено.")
    source = {
        "project_directory": str(PROJECT),
        "compose": compose_command(production=production),
        "docker_daemon_sha256": hashlib.sha256(daemon_id).hexdigest(),
        "compose_environment": {
            name: os.environ[name] for name in COMPOSE_SOURCE_VARIABLES if name in os.environ
        },
    }
    if production:
        env_file = os.environ.get("FKS_PRODUCTION_ENV_FILE") or "production.env"
        source["environment_file"] = str((PROJECT / env_file).resolve())
    return source


def db_command(program, *args, production=False):
    return compose_command(production=production) + [
        "exec", "-T", "db", "sh", "-c",
        'exec "$@" --username="$POSTGRES_USER" --dbname="$POSTGRES_DB"',
        "sh", program, *args,
    ]


def digest(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def inspect_media(path, *, expected=None, destination=None):
    """Validate entries and stream regular files only; never use extractall()."""
    files = {}
    with tarfile.open(path, "r|*") as archive:
        for entry in archive:
            relative = PurePosixPath(entry.name)
            if (
                not entry.isfile() or entry.sparse is not None
                or relative.is_absolute() or ".." in relative.parts
                or "\\" in entry.name or relative.as_posix() != entry.name
                or not relative.parts or entry.name in files
            ):
                raise BackupError("Недопустимый путь или тип файла в архиве.")
            if expected is not None and (
                entry.name not in expected or entry.size != expected[entry.name]["size"]
            ):
                raise BackupError("Состав медиа-архива не совпадает с манифестом.")
            checksum = hashlib.sha256()
            target = None
            try:
                if destination is not None:
                    target_path = destination / entry.name
                    target_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                    target = target_path.open("xb")
                    target_path.chmod(0o600)
                with archive.extractfile(entry) as source:
                    while chunk := source.read(1024 * 1024):
                        checksum.update(chunk)
                        if target is not None:
                            target.write(chunk)
            finally:
                if target is not None:
                    target.close()
            files[entry.name] = {"size": entry.size, "sha256": checksum.hexdigest()}
    if expected is not None and files != expected:
        raise BackupError("Контрольные суммы или состав медиа-файлов не совпадают.")
    return files


def create_backup(output, *, production=False):
    source = backup_source(production=production)
    output.mkdir(mode=0o700, parents=True, exist_ok=True)
    compose = compose_command(production=production)
    image_container = run(compose + ["ps", "-q", "db"]).decode().strip()
    if not image_container:
        raise BackupError("Сервис db должен быть запущен.")
    image = run(["docker", "inspect", "--format", "{{.Image}}", image_container]).decode().strip()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    final = output / f"fks-{stamp}-{uuid.uuid4().hex[:8]}"
    staging = Path(tempfile.mkdtemp(prefix=".incomplete-", dir=output))
    holder = None
    try:
        with tempfile.TemporaryFile() as errors:
            holder = subprocess.Popen(
                compose + ["exec", "-T", "web", "python", "manage.py", "backup_snapshot"],
                cwd=PROJECT, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=errors,
            )
            header = holder.stdout.readline()
            if not header:
                raise BackupError("Не удалось получить снимок. Проверьте доступность базы и медиа-файлов.")
            metadata = json.loads(header)
            database_name = run(db_command(
                "psql", "-XAt", "-c", "SELECT current_database()", production=production,
            )).decode().strip()
            if database_name != metadata["database"]:
                raise BackupError("Приложение и сервис db используют разные базы.")
            with (staging / "database.dump").open("xb") as dump:
                run(db_command(
                    "pg_dump", "--format=custom", "--no-owner", "--no-privileges",
                    "--schema=public", "--lock-wait-timeout=5s",
                    f"--snapshot={metadata['snapshot']}",
                    production=production,
                ), stdout=dump, timeout=240)
            holder.stdin.write(b"export-media\n")
            holder.stdin.flush()
            holder.stdin.close()
            with (staging / "media.tar").open("xb") as archive:
                shutil.copyfileobj(holder.stdout, archive, length=1024 * 1024)
            if holder.wait(timeout=30):
                raise BackupError("Копирование медиа не завершилось; копия не сохранена.")

        files = inspect_media(staging / "media.tar")
        if sorted(files) != metadata["media_names"]:
            raise BackupError("Архив не содержит все файлы снимка базы.")
        if backup_source(production=production) != source:
            raise BackupError("Источник Docker изменился во время копирования; повторите запуск.")
        manifest = {
            "format_version": 1,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "source": source,
            "postgres_image": image,
            "postgres_major": metadata["postgres_major"],
            "table_counts": metadata["table_counts"],
            "media_files": files,
            "sha256": {name: digest(staging / name) for name in ("database.dump", "media.tar")},
        }
        (staging / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
        )
        for name in ("database.dump", "media.tar", "manifest.json"):
            (staging / name).chmod(0o600)
        staging.rename(final)
        print(f"Копия создана: {final}")
        print(f"Таблиц: {len(manifest['table_counts'])}; файлов: {len(files)}.")
        return final
    finally:
        if holder is not None:
            if holder.stdin and not holder.stdin.closed:
                holder.stdin.close()
            try:
                holder.wait(timeout=10)
            except subprocess.TimeoutExpired:
                holder.kill()
                holder.wait(timeout=10)
            holder.stdout.close()
        # Only the fresh, private staging directory is ever removed.
        if staging.exists():
            shutil.rmtree(staging)


def load_manifest(backup):
    manifest = json.loads((backup / "manifest.json").read_text(encoding="utf-8"))
    if manifest["format_version"] != 1:
        raise BackupError("Неподдерживаемый формат копии.")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", manifest["postgres_image"]):
        raise BackupError("Некорректный идентификатор образа PostgreSQL.")
    for table, count in manifest["table_counts"].items():
        if not IDENTIFIER.fullmatch(table) or type(count) is not int or count < 0:
            raise BackupError("Некорректный список таблиц.")
    for name in ("database.dump", "media.tar"):
        if digest(backup / name) != manifest["sha256"][name]:
            raise BackupError(f"Нарушена целостность {name}.")
    return manifest


def verify_backup(backup):
    manifest = load_manifest(backup)
    name = f"fks-restore-check-{uuid.uuid4().hex}"
    container = None
    with tempfile.TemporaryDirectory(prefix="fks-restore-") as temporary:
        media_root = Path(temporary) / "private_media"
        media_root.mkdir(mode=0o700)
        files = inspect_media(
            backup / "media.tar", expected=manifest["media_files"], destination=media_root,
        )
        try:
            # No host ports, no network, no project mounts, no production DB target.
            container = run([
                "docker", "run", "--detach", "--rm", "--pull=never", "--network=none",
                "--name", name, "--env", "POSTGRES_HOST_AUTH_METHOD=trust",
                "--env", "POSTGRES_DB=restore_check", manifest["postgres_image"],
            ]).decode().strip()
            if not re.fullmatch(r"[0-9a-f]{64}", container):
                raise BackupError("Не удалось определить временный контейнер.")
            psql = ["docker", "exec", "-i", container, "psql", "-XAt", "-v", "ON_ERROR_STOP=1", "-U", "postgres", "-d", "restore_check"]
            for attempt in range(60):
                # TCP is only used inside the isolated container; it becomes ready
                # after the entrypoint finishes its temporary initialization server.
                ready = subprocess.run(
                    ["docker", "exec", container, "pg_isready", "-h", "127.0.0.1", "-U", "postgres", "-d", "restore_check"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10,
                )
                if ready.returncode == 0:
                    break
                time.sleep(1)
            else:
                raise BackupError("Временная база не запустилась.")

            # The schema-qualified dump recreates public. Remove only the empty
            # default schema in this freshly created, isolated database (no CASCADE).
            run(psql + ["-c", "DROP SCHEMA public"])
            with (backup / "database.dump").open("rb") as dump:
                run([
                    "docker", "exec", "-i", container, "pg_restore", "-U", "postgres",
                    "--dbname=restore_check", "--exit-on-error", "--single-transaction",
                    "--no-owner", "--no-privileges",
                ], stdin=dump)
            for table, count in manifest["table_counts"].items():
                actual = int(run(psql + ["-c", f'SELECT count(*) FROM public."{table}"']))
                if actual != count:
                    raise BackupError(f"Количество записей после восстановления не совпало: {table}.")
            file_list = run(psql + ["-c",
                "SELECT COALESCE(json_agg(file ORDER BY file), '[]'::json) "
                "FROM (SELECT DISTINCT file FROM heritage_mediaasset WHERE file <> '') files"
            ])
            if json.loads(file_list) != sorted(files):
                raise BackupError("Файлы восстановленной базы не совпадают с архивом.")
            for relative, info in files.items():
                if digest(media_root / relative) != info["sha256"]:
                    raise BackupError("Ошибка проверки восстановленного файла.")
        finally:
            if container and re.fullmatch(r"[0-9a-f]{64}", container):
                # --rm removes this disposable container and its anonymous volume.
                run(["docker", "stop", "--time=10", container], timeout=30)

    print(f"Восстановление проверено: {len(manifest['table_counts'])} таблиц, {len(files)} файлов.")
    print("Временная база и извлечённые файлы удалены. Исходная копия сохранена.")


def main():
    parser = argparse.ArgumentParser(description="Копирование семейной базы и проверка восстановления")
    commands = parser.add_subparsers(dest="action", required=True)
    create = commands.add_parser("create", help="создать новую копию на этом компьютере")
    create.add_argument("--production", action="store_true", help="копировать проект family-production")
    create.add_argument("--output", type=Path, help="каталог копий (production по умолчанию: backups/production)")
    verify = commands.add_parser("verify", help="восстановить доверенную копию во временном окружении")
    verify.add_argument("backup", type=Path)
    args = parser.parse_args()
    os.umask(0o077)
    try:
        if args.action == "create":
            output = args.output if args.output is not None else (PRODUCTION_OUTPUT if args.production else OUTPUT)
            if args.production:
                create_backup(output.resolve(), production=True)
            else:
                create_backup(output.resolve())
        else:
            verify_backup(args.backup.resolve())
    except (BackupError, OSError, ValueError, KeyError, tarfile.TarError, subprocess.TimeoutExpired) as error:
        parser.exit(1, f"Операция не завершена: {error}\n")


if __name__ == "__main__":
    main()
