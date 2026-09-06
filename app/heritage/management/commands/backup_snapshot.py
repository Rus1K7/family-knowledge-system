"""Internal streaming protocol used by scripts/backup.py."""

import json
import select
import sys
import tarfile
from pathlib import Path, PurePosixPath

from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction

from heritage.models import MediaAsset


class Command(BaseCommand):
    help = "Согласованный снимок для scripts/backup.py; не запускайте вручную."
    requires_system_checks = []

    def handle(self, *args, **options):
        database = connection.settings_dict
        if connection.vendor != "postgresql" or database["HOST"] != "db":
            raise CommandError("Поддерживается PostgreSQL сервиса db в Docker Compose.")

        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("SET LOCAL lock_timeout = '5s'")
                cursor.execute("SET LOCAL idle_in_transaction_session_timeout = '10min'")
                cursor.execute(
                    "SELECT tablename FROM pg_tables "
                    "WHERE schemaname = 'public' ORDER BY tablename"
                )
                tables = [row[0] for row in cursor.fetchall()]
                if not tables:
                    raise CommandError("В базе нет таблиц для копирования.")
                quote = connection.ops.quote_name
                # Take the exported snapshot only AFTER all writers have finished.
                # SHARE locks allow reads but stop row changes and their file cleanup.
                cursor.execute("LOCK TABLE " + ", ".join(
                    f"public.{quote(table)}" for table in tables
                ) + " IN SHARE MODE")
                cursor.execute("SELECT pg_export_snapshot()")
                snapshot = cursor.fetchone()[0]
                counts = {}
                for table in tables:
                    cursor.execute(f"SELECT count(*) FROM public.{quote(table)}")
                    counts[table] = cursor.fetchone()[0]

            storage = MediaAsset._meta.get_field("file").storage
            root = Path(storage.location).resolve()
            names = sorted(set(MediaAsset.objects.exclude(file="").values_list("file", flat=True)))
            paths = {}
            for name in names:
                relative = PurePosixPath(name)
                if (
                    relative.is_absolute() or ".." in relative.parts
                    or "\\" in name or relative.as_posix() != name
                ):
                    raise CommandError("Обнаружен некорректный путь медиа-файла.")
                path = root / name
                if path.resolve() != path or not path.is_file():
                    raise CommandError("Медиа-файл отсутствует или является символической ссылкой.")
                paths[name] = path

            self.stdout.write(json.dumps({
                "snapshot": snapshot,
                "database": database["NAME"],
                "postgres_major": connection.pg_version // 10000,
                "table_counts": counts,
                "media_names": names,
            }))
            self.stdout.flush()

            # A disconnected or failed orchestrator must not leave writes locked.
            ready, _, _ = select.select([sys.stdin], [], [], 300)
            if not ready or sys.stdin.readline().strip() != "export-media":
                raise CommandError("Создание копии отменено или истекло время ожидания.")

            with tarfile.open(fileobj=self.stdout.buffer, mode="w|") as archive:
                for name, path in paths.items():
                    before = path.stat()
                    entry = tarfile.TarInfo(name)
                    entry.size = before.st_size
                    entry.mode = 0o600
                    entry.mtime = int(before.st_mtime)
                    with path.open("rb") as source:
                        archive.addfile(entry, source)
                    after = path.stat()
                    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                        raise CommandError("Файл изменился во время копирования; повторите операцию.")
