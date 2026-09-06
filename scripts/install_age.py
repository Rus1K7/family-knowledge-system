"""Install the pinned official age binaries locally, without a package manager."""

import hashlib
import os
import platform
import shutil
import subprocess
import tarfile
import tempfile
from pathlib import Path


VERSION = "v1.3.2"
TOOLS = Path(__file__).resolve().parents[1] / ".tools"
TARGET = TOOLS / f"age-{VERSION}"
# SHA-256 published by GitHub's FiloSottile/age release asset API.
CHECKSUMS = {
    "arm64": "e2020b073c44f692685a24d6abc378817eb81ffaaf49fd0531ef8565f767f2f5",
    "x86_64": "1d1e4bc66e1427edad7739ae7616157de0e79db8b6d2a1497d7d9925fb06a539",
}


def main():
    os.umask(0o077)
    machine = platform.machine()
    if platform.system() != "Darwin" or machine not in CHECKSUMS:
        raise SystemExit("Этот установщик поддерживает macOS arm64 и x86_64.")
    if TARGET.exists():
        for binary in ("age", "age-keygen"):
            version = subprocess.check_output([str(TARGET / binary), "--version"], text=True).strip()
            if version != VERSION:
                raise SystemExit("Каталог инструмента уже существует с другой версией.")
        print(f"age {VERSION} уже установлен: {TARGET}")
        return
    TOOLS.mkdir(mode=0o700, exist_ok=True)
    arch = "arm64" if machine == "arm64" else "amd64"
    url = f"https://github.com/FiloSottile/age/releases/download/{VERSION}/age-{VERSION}-darwin-{arch}.tar.gz"
    with tempfile.TemporaryDirectory(prefix=".age-install-", dir=TOOLS) as temporary:
        root = Path(temporary)
        download = root / "release.tar.gz"
        subprocess.run([
            "curl", "--fail", "--silent", "--show-error", "--location",
            "--max-time", "120", "--output", str(download), url,
        ], check=True)
        with download.open("rb") as source:
            checksum = hashlib.file_digest(source, "sha256").hexdigest()
        if checksum != CHECKSUMS[machine]:
            raise SystemExit("Контрольная сумма age не совпала; установка отменена.")
        staged = root / "binaries"
        staged.mkdir(mode=0o700)
        with tarfile.open(download) as archive:
            for binary in ("age", "age-keygen"):
                member = archive.getmember(f"age/{binary}")
                if not member.isfile():
                    raise SystemExit("Неожиданный тип файла в выпуске age.")
                with archive.extractfile(member) as source, (staged / binary).open("xb") as target:
                    shutil.copyfileobj(source, target)
                (staged / binary).chmod(0o700)
        staged.rename(TARGET)
    print(f"age {VERSION} установлен и проверен: {TARGET}")


if __name__ == "__main__":
    main()
