#!/usr/bin/env python3
"""Install the pinned ffprobe used by Azure App Service without root access."""

from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import shutil
import tarfile
import tempfile
from urllib.request import Request, urlopen


ARCHIVE_URL = (
    "https://johnvansickle.com/ffmpeg/releases/"
    "ffmpeg-7.0.2-amd64-static.tar.xz"
)
ARCHIVE_SHA512 = (
    "e80880362208de7437f0eb98d25ec6676df122a04613a818bb14101c3e1ccf91f"
    "eab06246d40359b887b147af65d80eef5dba99964cac469bcb560f1a063d737"
)
BINARY_SHA256 = "4f231a1960d83e403d08f7971e271707bec278a9ae18e21b8b5b03186668450d"
ARCHIVE_MEMBER = "ffmpeg-7.0.2-amd64-static/ffprobe"
MAX_ARCHIVE_BYTES = 64 * 1024 * 1024


def _file_digest(path: Path, algorithm: str) -> str:
    digest = hashlib.new(algorithm)
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _download_archive(destination: Path) -> None:
    request = Request(ARCHIVE_URL, headers={"User-Agent": "Flare-release/1"})
    digest = hashlib.sha512()
    size = 0
    with urlopen(request, timeout=120) as response, destination.open("wb") as output:
        declared_size = response.headers.get("Content-Length")
        if declared_size and int(declared_size) > MAX_ARCHIVE_BYTES:
            raise RuntimeError("ffprobe archive exceeds the release size limit")
        while chunk := response.read(1024 * 1024):
            size += len(chunk)
            if size > MAX_ARCHIVE_BYTES:
                raise RuntimeError("ffprobe archive exceeds the release size limit")
            digest.update(chunk)
            output.write(chunk)
    if digest.hexdigest() != ARCHIVE_SHA512:
        raise RuntimeError("ffprobe archive integrity check failed")


def _extract_binary(archive: Path, destination: Path) -> None:
    with tarfile.open(archive, "r:xz") as package:
        member = package.getmember(ARCHIVE_MEMBER)
        if not member.isfile() or member.size > 96 * 1024 * 1024:
            raise RuntimeError("ffprobe archive member is invalid")
        source = package.extractfile(member)
        if source is None:
            raise RuntimeError("ffprobe archive member is missing")
        temporary: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                prefix=f".{destination.name}-",
                suffix=".tmp",
                dir=destination.parent,
                delete=False,
            ) as output:
                temporary = Path(output.name)
                shutil.copyfileobj(source, output, length=1024 * 1024)
            if _file_digest(temporary, "sha256") != BINARY_SHA256:
                raise RuntimeError("ffprobe binary integrity check failed")
            temporary.chmod(0o555)
            os.replace(temporary, destination)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)


def ensure_ffprobe(destination: Path) -> Path:
    destination = destination.resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_file() and _file_digest(destination, "sha256") == BINARY_SHA256:
        destination.chmod(0o555)
        return destination

    with tempfile.NamedTemporaryFile(
        prefix="ffprobe-", suffix=".tar.xz", dir=destination.parent, delete=False
    ) as temporary:
        archive = Path(temporary.name)
    try:
        _download_archive(archive)
        _extract_binary(archive, destination)
    finally:
        archive.unlink(missing_ok=True)
    return destination


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--destination", required=True, type=Path)
    args = parser.parse_args()
    print(ensure_ffprobe(args.destination))


if __name__ == "__main__":
    main()
