import json
from pathlib import Path, PurePosixPath

from django.core.management.base import BaseCommand, CommandError

from heritage.models import MediaAsset


class Command(BaseCommand):
    help = "Формирует отчёт о согласованности закрытого хранилища медиа."
    requires_system_checks = []

    def add_arguments(self, parser):
        parser.add_argument("--json", action="store_true", dest="as_json")

    def handle(self, *args, **options):
        storage = MediaAsset._meta.get_field("file").storage
        root = Path(storage.location).resolve()
        if not root.is_dir():
            raise CommandError("Каталог закрытого хранилища не существует.")

        referenced = set(MediaAsset.objects.exclude(file="").values_list("file", flat=True))
        invalid_references = []
        missing = []
        for name in sorted(referenced):
            relative = PurePosixPath(name)
            path = root / name
            if (relative.is_absolute() or ".." in relative.parts or "\\" in name
                    or relative.as_posix() != name or path.resolve() != path):
                invalid_references.append(name)
            elif not path.is_file():
                missing.append(name)

        files = set()
        symlinks = []
        for path in root.rglob("*"):
            relative = path.relative_to(root).as_posix()
            if path.is_symlink():
                symlinks.append(relative)
            elif path.is_file():
                files.add(relative)
        report = {
            "root": str(root), "referenced": len(referenced), "files": len(files),
            "missing": missing, "orphans": sorted(files - referenced),
            "invalid_references": invalid_references, "symlinks": sorted(symlinks),
        }
        if options["as_json"]:
            self.stdout.write(json.dumps(report, ensure_ascii=False, indent=2))
        else:
            self.stdout.write(
                "Медиа-файлов: {files}; ссылок в базе: {referenced}; "
                "пропущено: {missing}; сирот: {orphans}; символических ссылок: {symlinks}.".format(
                    files=len(files), referenced=len(referenced), missing=len(missing),
                    orphans=len(report["orphans"]), symlinks=len(symlinks),
                )
            )
            if any(report[key] for key in ("missing", "orphans", "invalid_references", "symlinks")):
                self.stdout.write(json.dumps(report, ensure_ascii=False, indent=2))
