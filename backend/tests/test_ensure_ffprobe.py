import hashlib
import importlib.util
from io import BytesIO
from pathlib import Path
import tarfile

import pytest


SCRIPT = Path(__file__).parents[1] / "deploy" / "ensure_ffprobe.py"
SPEC = importlib.util.spec_from_file_location("ensure_ffprobe", SCRIPT)
assert SPEC and SPEC.loader
ensure = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ensure)


def package(binary: bytes) -> bytes:
    payload = BytesIO()
    with tarfile.open(fileobj=payload, mode="w:xz") as archive:
        info = tarfile.TarInfo(ensure.ARCHIVE_MEMBER)
        info.size = len(binary)
        archive.addfile(info, BytesIO(binary))
    return payload.getvalue()


def test_extracts_only_the_pinned_binary(tmp_path, monkeypatch):
    binary = b"safe static ffprobe"
    monkeypatch.setattr(ensure, "BINARY_SHA256", hashlib.sha256(binary).hexdigest())
    archive = tmp_path / "package.tar.xz"
    archive.write_bytes(package(binary))
    destination = tmp_path / "tools" / "ffprobe"
    destination.parent.mkdir()

    ensure._extract_binary(archive, destination)

    assert destination.read_bytes() == binary
    assert destination.stat().st_mode & 0o111


def test_rejects_a_binary_with_the_wrong_digest(tmp_path):
    archive = tmp_path / "package.tar.xz"
    archive.write_bytes(package(b"tampered"))
    destination = tmp_path / "ffprobe"

    with pytest.raises(RuntimeError, match="binary integrity"):
        ensure._extract_binary(archive, destination)

    assert not destination.exists()


def test_cached_pinned_binary_avoids_network(tmp_path, monkeypatch):
    binary = b"already installed"
    destination = tmp_path / "ffprobe"
    destination.write_bytes(binary)
    monkeypatch.setattr(ensure, "BINARY_SHA256", hashlib.sha256(binary).hexdigest())
    monkeypatch.setattr(
        ensure,
        "_download_archive",
        lambda _path: (_ for _ in ()).throw(AssertionError("network used")),
    )

    assert ensure.ensure_ffprobe(destination) == destination
    assert destination.stat().st_mode & 0o111
