import hashlib
import importlib.util
from io import BytesIO
from http.client import IncompleteRead
from pathlib import Path
import tarfile
from types import SimpleNamespace
from urllib.error import URLError
from urllib.request import Request

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


class Response(BytesIO):
    def __init__(self, body, declared_size=None):
        super().__init__(body)
        self.headers = {} if declared_size is None else {"Content-Length": str(declared_size)}
        self.reads = 0

    def read(self, size=-1):
        self.reads += 1
        return super().read(size)


def transport(monkeypatch, outcomes):
    calls = []
    outcomes = iter(outcomes)

    class Opener:
        def open(self, request, *, timeout):
            calls.append((request.full_url, timeout))
            outcome = next(outcomes)
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

    def factory(handler):
        assert isinstance(handler, ensure.HTTPSOnlyRedirectHandler)
        return Opener()

    monkeypatch.setattr(ensure, "build_opener", factory)
    monkeypatch.setattr(ensure, "time", SimpleNamespace(
        monotonic=ensure.time.monotonic, sleep=lambda _: None,
    ))
    return calls


def pin(monkeypatch, binary):
    archive = package(binary)
    monkeypatch.setattr(ensure, "BINARY_SHA256", hashlib.sha256(binary).hexdigest())
    monkeypatch.setattr(ensure, "ARCHIVE_SHA512", hashlib.sha512(archive).hexdigest())
    return archive


def test_downloads_and_installs_verified_mirror_archive(tmp_path, monkeypatch):
    binary = b"pinned binary"
    archive = pin(monkeypatch, binary)
    calls = transport(monkeypatch, [Response(archive, len(archive))])
    destination = tmp_path / "tools" / "ffprobe"

    ensure.ensure_ffprobe(destination)

    assert destination.read_bytes() == binary
    assert destination.stat().st_mode & 0o111
    assert calls[0][0] == ensure.ARCHIVE_URLS[0]
    assert 0 < calls[0][1] <= ensure.SOCKET_TIMEOUT_SECONDS
    assert list(destination.parent.iterdir()) == [destination]


def test_network_failure_falls_back_only_to_approved_upstream(tmp_path, monkeypatch):
    archive = pin(monkeypatch, b"pinned")
    calls = transport(monkeypatch, [URLError("TLS timeout"), URLError("TLS timeout"), Response(archive)])

    destination = ensure.ensure_ffprobe(tmp_path / "ffprobe")

    assert destination.read_bytes() == b"pinned"
    assert [url for url, _ in calls] == [ensure.ARCHIVE_URLS[0], ensure.ARCHIVE_URLS[0], ensure.ARCHIVE_URL]


def test_partial_transport_is_retried_without_appending_old_bytes(tmp_path, monkeypatch):
    archive = pin(monkeypatch, b"pinned")

    class Interrupted(Response):
        def read(self, size=-1):
            if self.reads:
                raise IncompleteRead(b"truncated")
            return super().read(9)

    interrupted = Interrupted(archive)
    calls = transport(monkeypatch, [interrupted, Response(archive)])
    destination = tmp_path / "archive"

    ensure._download_archive(destination)

    assert destination.read_bytes() == archive
    assert interrupted.closed
    assert len(calls) == 2


def test_transport_exhaustion_is_bounded_and_cleans_temporary_files(tmp_path, monkeypatch):
    calls = transport(monkeypatch, [URLError("offline")] * 4)

    with pytest.raises(RuntimeError, match="Unable to download pinned ffprobe"):
        ensure.ensure_ffprobe(tmp_path / "ffprobe")

    assert len(calls) == 4
    assert list(tmp_path.iterdir()) == []


def test_archive_integrity_failure_never_tries_another_source_or_publishes(tmp_path, monkeypatch):
    calls = transport(monkeypatch, [Response(b"tampered")])

    with pytest.raises(RuntimeError, match="archive integrity"):
        ensure.ensure_ffprobe(tmp_path / "ffprobe")

    assert len(calls) == 1
    assert list(tmp_path.iterdir()) == []


def test_declared_oversize_is_rejected_before_body_read(tmp_path, monkeypatch):
    response = Response(b"not read", ensure.MAX_ARCHIVE_BYTES + 1)
    calls = transport(monkeypatch, [response])

    with pytest.raises(RuntimeError, match="size limit"):
        ensure.ensure_ffprobe(tmp_path / "ffprobe")

    assert response.reads == 0
    assert len(calls) == 1
    assert list(tmp_path.iterdir()) == []


def test_unannounced_oversize_is_rejected_without_installation(tmp_path, monkeypatch):
    monkeypatch.setattr(ensure, "MAX_ARCHIVE_BYTES", 4)
    calls = transport(monkeypatch, [Response(b"oversized")])

    with pytest.raises(RuntimeError, match="size limit"):
        ensure.ensure_ffprobe(tmp_path / "ffprobe")

    assert len(calls) == 1
    assert list(tmp_path.iterdir()) == []


def test_total_deadline_stops_slow_reads_without_another_request(tmp_path, monkeypatch):
    clock = [0]
    monkeypatch.setattr(ensure, "time", SimpleNamespace(
        monotonic=lambda: clock[0], sleep=lambda _: None,
    ))

    class Slow(Response):
        def read(self, size=-1):
            clock[0] += ensure.DOWNLOAD_DEADLINE_SECONDS + 1
            return super().read(size)

    response = Slow(b"body")
    calls = transport(monkeypatch, [response])

    with pytest.raises(RuntimeError, match="deadline reached"):
        ensure.ensure_ffprobe(tmp_path / "ffprobe")

    assert len(calls) == 1
    assert response.closed
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("url", ["http://example.invalid/tool", "file:///tmp/tool", "ftp://example.invalid/tool"])
def test_redirect_cannot_downgrade_transport(url):
    with pytest.raises(RuntimeError, match="requires HTTPS"):
        ensure.HTTPSOnlyRedirectHandler().redirect_request(
            Request(ensure.ARCHIVE_URLS[0]), None, 302, "Found", {}, url,
        )


def test_https_asset_redirect_still_works():
    target = "https://release-assets.githubusercontent.com/pinned-asset"
    request = ensure.HTTPSOnlyRedirectHandler().redirect_request(
        Request(ensure.ARCHIVE_URLS[0]), None, 302, "Found", {}, target,
    )
    assert request.full_url == target


def test_corrupt_cache_is_replaced_only_after_full_verification(tmp_path, monkeypatch):
    archive = pin(monkeypatch, b"verified")
    destination = tmp_path / "ffprobe"
    destination.write_bytes(b"corrupt cache")
    calls = transport(monkeypatch, [Response(archive)])

    ensure.ensure_ffprobe(destination)

    assert len(calls) == 1
    assert destination.read_bytes() == b"verified"


def test_cached_symlink_is_rejected_without_reading_target(tmp_path, monkeypatch):
    target = tmp_path / "unrelated"
    target.write_bytes(b"unrelated data")
    destination = tmp_path / "ffprobe"
    destination.symlink_to(target)
    monkeypatch.setattr(ensure, "_file_digest", lambda *_: pytest.fail("must not read symlink target"))
    transport(monkeypatch, [])

    with pytest.raises(RuntimeError, match="must not be a symlink"):
        ensure.ensure_ffprobe(destination)

    assert target.read_bytes() == b"unrelated data"
