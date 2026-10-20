#!/usr/bin/env python3
"""Install the pinned ffprobe used by Azure App Service without root access."""

from __future__ import annotations

import argparse
import hashlib
from http.client import IncompleteRead
import os
from pathlib import Path
import shutil
import ssl
import sys
import tarfile
import tempfile
import time
from urllib.error import URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


ARCHIVE_URL = (
    "https://johnvansickle.com/ffmpeg/releases/"
    "ffmpeg-7.0.2-amd64-static.tar.xz"
)
# Availability mirrors are not trust roots: BOTH existing digests below must
# still match. This immutable release contains the exact upstream archive.
ARCHIVE_URLS = (
    "https://github.com/publicala/ffmpeg-static/releases/download/"
    "v7.0.2/ffmpeg-7.0.2-amd64-static.tar.xz",
    ARCHIVE_URL,
)
ARCHIVE_SHA512 = (
    "e80880362208de7437f0eb98d25ec6676df122a04613a818bb14101c3e1ccf91f"
    "eab06246d40359b887b147af65d80eef5dba99964cac469bcb560f1a063d737"
)
BINARY_SHA256 = "4f231a1960d83e403d08f7971e271707bec278a9ae18e21b8b5b03186668450d"
ARCHIVE_MEMBER = "ffmpeg-7.0.2-amd64-static/ffprobe"
MAX_ARCHIVE_BYTES = 64 * 1024 * 1024
MAX_BINARY_BYTES = 96 * 1024 * 1024
DOWNLOAD_ATTEMPTS_PER_SOURCE = 2
DOWNLOAD_DEADLINE_SECONDS = 90
SOCKET_TIMEOUT_SECONDS = 15


class HTTPSOnlyRedirectHandler(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if urlsplit(newurl).scheme.lower() != "https":
            raise RuntimeError("ffprobe download requires HTTPS redirects")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _remaining(deadline: float) -> float:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("ffprobe download deadline reached")
    return remaining


def _file_digest(path: Path, algorithm: str) -> str:
    digest = hashlib.new(algorithm)
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _download_once(url: str, destination: Path, deadline: float) -> None:
    request = Request(url, headers={"User-Agent": "Flare-release/1"})
    digest = hashlib.sha512()
    size = 0
    opener = build_opener(HTTPSOnlyRedirectHandler())
    with (
        opener.open(request, timeout=min(SOCKET_TIMEOUT_SECONDS, _remaining(deadline))) as response,
        destination.open("wb") as output,
    ):
        declared_size = response.headers.get("Content-Length")
        if declared_size and int(declared_size) > MAX_ARCHIVE_BYTES:
            raise RuntimeError("ffprobe archive exceeds the release size limit")
        while True:
            _remaining(deadline)
            chunk = response.read(1024 * 1024)
            _remaining(deadline)
            if not chunk:
                break
            size += len(chunk)
            if size > MAX_ARCHIVE_BYTES:
                raise RuntimeError("ffprobe archive exceeds the release size limit")
            digest.update(chunk)
            output.write(chunk)
    if digest.hexdigest() != ARCHIVE_SHA512:
        raise RuntimeError("ffprobe archive integrity check failed")


def _download_archive(destination: Path) -> None:
    deadline = time.monotonic() + DOWNLOAD_DEADLINE_SECONDS
    last_error = None
    for source, url in enumerate(ARCHIVE_URLS, start=1):
        for attempt in range(1, DOWNLOAD_ATTEMPTS_PER_SOURCE + 1):
            try:
                _remaining(deadline)
                _download_once(url, destination, deadline)
                return
            except (URLError, TimeoutError, ConnectionError, IncompleteRead, ssl.SSLError) as error:
                destination.unlink(missing_ok=True)
                last_error = error
                print(f"ffprobe source {source}, attempt {attempt}: {type(error).__name__}", file=sys.stderr)
                if time.monotonic() >= deadline:
                    raise RuntimeError("ffprobe download deadline reached") from error
                if attempt < DOWNLOAD_ATTEMPTS_PER_SOURCE:
                    time.sleep(min(1, _remaining(deadline)))
    raise RuntimeError("Unable to download pinned ffprobe from approved HTTPS sources") from last_error


def _extract_binary(archive: Path, destination: Path) -> None:
    with tarfile.open(archive, "r:xz") as package:
        member = package.getmember(ARCHIVE_MEMBER)
        if not member.isfile() or member.size > MAX_BINARY_BYTES:
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
    if destination.is_symlink():
        raise RuntimeError("ffprobe destination must not be a symlink")
    destination = destination.resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    if (
        destination.is_file()
        and destination.stat().st_size <= MAX_BINARY_BYTES
        and _file_digest(destination, "sha256") == BINARY_SHA256
    ):
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
