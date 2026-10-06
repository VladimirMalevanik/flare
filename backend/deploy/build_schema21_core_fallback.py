#!/usr/bin/env python3
"""Export a pinned, temporary legacy core with the exact schema-0021 DB boundary.

This does not migrate, deploy, read an environment file, or contact a provider.
The only accepted-source substitution is the complete database.py blob. The
fallback intentionally does not include the new billing or ZIP application code.
"""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import tempfile
import unittest


LEGACY_CORE_SHA = "8679d075ea973d2d8ca63e178591fb520642412e"
ACCEPTED_DATABASE_SHA = "453ebec4b6592d1e089a3f5d04da0f35a78a4f09"
SCHEMA_REVISION = "0021"
DATABASE_PATH = "backend/app/models/database.py"
MANIFEST_NAME = "schema21-core-fallback-manifest.json"
MANIFEST_HASH_NAME = MANIFEST_NAME + ".sha256"
LEGACY_FILES = {
    "backend/pyproject.toml",
    "backend/deploy/bootstrap_flare_api.sh",
    "backend/deploy/bootstrap_flare_worker.sh",
    "backend/deploy/ensure_ffprobe.py",
    # Used by the legacy frontend's release-link regression check; not packaged.
    "desktop/package.json",
}


class SourceValidationError(ValueError):
    """The pinned export cannot be verified safely."""


def _git(repository: Path, *arguments: str, input_bytes: bytes | None = None) -> bytes:
    result = subprocess.run(
        ["git", "--no-pager", "-C", str(repository), *arguments],
        input=input_bytes, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    )
    if result.returncode:
        # Do not print arbitrary git output, source contents, or local configuration.
        raise SourceValidationError("Pinned Git object is unavailable; fetch the complete repository history")
    return result.stdout


def _canonical(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=True) + "\n").encode()


def _safe_path(path: str) -> bool:
    relative = PurePosixPath(path)
    return (bool(path) and not relative.is_absolute() and "\\" not in path
            and "\x00" not in path and all(part not in ("", ".", "..", ".git") for part in relative.parts)
            and str(relative) == path)


def _secret_filename(path: str) -> bool:
    name = PurePosixPath(path).name.lower()
    return (name in {".env", "id_rsa", "id_ed25519", "credentials"}
            or (name.startswith(".env.") and name != ".env.example")
            or name.endswith((".pem", ".key", ".p12", ".pfx")))


def _validate_blob(path: str, content: bytes) -> None:
    if not _safe_path(path) or _secret_filename(path):
        raise SourceValidationError("Unsafe or secret-bearing source filename")
    if re.search(rb"-----BEGIN (?:[A-Z ]+ )?PRIVATE KEY-----", content):
        raise SourceValidationError("Private key material is prohibited in exported sources")
    if re.search(rb"\b(?:gsk_|gh[pousr]_|github_pat_|re_)[A-Za-z0-9_-]{24,}\b", content):
        raise SourceValidationError("Credential-shaped literal is prohibited in exported sources")


def _pinned_sources(repository: Path) -> list[dict[str, object]]:
    for commit in (LEGACY_CORE_SHA, ACCEPTED_DATABASE_SHA):
        if _git(repository, "cat-file", "-t", commit).strip() != b"commit":
            raise SourceValidationError("Pinned source must be a commit")
    entries: dict[str, dict[str, object]] = {}
    paths = ["backend/app", "frontend", *sorted(LEGACY_FILES)]
    tree = _git(repository, "ls-tree", "-r", "-z", "--full-tree", LEGACY_CORE_SHA, "--", *paths)
    for raw in tree.split(b"\0"):
        if not raw:
            continue
        header, encoded_path = raw.split(b"\t", 1)
        mode, kind, oid = header.decode("ascii").split()
        path = encoded_path.decode("utf-8")
        if mode not in ("100644", "100755") or kind != "blob" or not _safe_path(path):
            raise SourceValidationError("Only ordinary pinned source files are permitted")
        entries[path] = {"path": path, "mode": mode, "git_blob": oid, "origin_sha": LEGACY_CORE_SHA}
    if DATABASE_PATH not in entries or any(path not in entries for path in LEGACY_FILES):
        raise SourceValidationError("Required legacy core sources are missing")
    entries[DATABASE_PATH]["git_blob"] = _git(
        repository, "rev-parse", f"{ACCEPTED_DATABASE_SHA}:{DATABASE_PATH}",
    ).decode("ascii").strip()
    entries[DATABASE_PATH]["origin_sha"] = ACCEPTED_DATABASE_SHA
    ordered = [entries[path] for path in sorted(entries)]
    requested = ("\n".join(str(entry["git_blob"]) for entry in ordered) + "\n").encode("ascii")
    blobs = _git(repository, "cat-file", "--batch", input_bytes=requested)
    offset = 0
    for entry in ordered:
        boundary = blobs.index(b"\n", offset)
        oid, kind, size = blobs[offset:boundary].decode("ascii").split()
        if oid != entry["git_blob"] or kind != "blob":
            raise SourceValidationError("Pinned blob batch did not match the expected tree")
        offset = boundary + 1
        content = blobs[offset:offset + int(size)]
        offset += int(size)
        if blobs[offset:offset + 1] != b"\n":
            raise SourceValidationError("Pinned blob batch is truncated")
        offset += 1
        _validate_blob(str(entry["path"]), content)
        entry["content"] = content
        entry["sha256"] = sha256(content).hexdigest()
        entry["size"] = len(content)
    if offset != len(blobs):
        raise SourceValidationError("Unexpected data after the pinned blob batch")
    return ordered


def _manifest(sources: list[dict[str, object]]) -> dict[str, object]:
    files = [{key: value for key, value in entry.items() if key != "content"} for entry in sources]
    database = next(entry for entry in files if entry["path"] == DATABASE_PATH)
    return {
        "format_version": 1,
        "purpose": "temporary schema-0021 legacy core fallback; build-only, no migrations or deployment",
        "legacy_core_sha": LEGACY_CORE_SHA,
        "accepted_database_sha": ACCEPTED_DATABASE_SHA,
        "schema_revision": SCHEMA_REVISION,
        "database_sha256": database["sha256"],
        "sources_sha256": sha256(_canonical(files)).hexdigest(),
        "accepted_substitutions": [DATABASE_PATH],
        "files": files,
    }


def build_sources(repository: Path, output: Path) -> dict[str, object]:
    """Export verified blobs to a fresh directory and return the persisted manifest.

    Existing directories, files and symlinks are always refused. Only immutable
    Git blobs are read; dirty files, .env files and credentials in the checkout
    are not used. Manifest bytes and their standard sha256 sidecar are stable.
    """
    repository = repository.resolve(strict=True)
    output = output.absolute()
    if output.exists() or output.is_symlink() or ".git" in output.parts:
        raise SourceValidationError("Output must be a new directory outside Git metadata")
    if not output.parent.is_dir():
        raise SourceValidationError("Output parent must already exist")
    output = output.parent.resolve(strict=True) / output.name
    if ".git" in output.parts:
        raise SourceValidationError("Output must be outside resolved Git metadata")
    sources = _pinned_sources(repository)
    manifest = _manifest(sources)
    output.mkdir(mode=0o700)
    try:
        for entry in sources:
            destination = output.joinpath(str(entry["path"]))
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(entry["content"])  # type: ignore[arg-type]
            destination.chmod(0o755 if entry["mode"] == "100755" else 0o644)
        data = _canonical(manifest)
        (output / MANIFEST_NAME).write_bytes(data)
        (output / MANIFEST_HASH_NAME).write_text(f"{sha256(data).hexdigest()}  {MANIFEST_NAME}\n", encoding="ascii")
    except BaseException:
        # This directory was created exclusively by this invocation, never reused.
        shutil.rmtree(output)
        raise
    return manifest


def verify_sources(repository: Path, output: Path) -> dict[str, object]:
    """Verify every byte/mode against the two pinned commits; reject extras too."""
    if output.is_symlink() or not output.is_dir():
        raise SourceValidationError("Export must be an ordinary directory")
    sources = _pinned_sources(repository.resolve(strict=True))
    manifest = _manifest(sources)
    expected = {str(entry["path"]): entry for entry in sources}
    permitted = set(expected) | {MANIFEST_NAME, MANIFEST_HASH_NAME}
    discovered: set[str] = set()
    for directory, directories, files in os.walk(output, followlinks=False):
        for name in directories:
            if (Path(directory) / name).is_symlink():
                raise SourceValidationError("Export symlinks are prohibited")
        for name in files:
            path = Path(directory) / name
            relative = path.relative_to(output).as_posix()
            if path.is_symlink() or not path.is_file() or relative not in permitted:
                raise SourceValidationError("Unexpected export file")
            discovered.add(relative)
    if discovered != permitted:
        raise SourceValidationError("Export file inventory differs from the pinned manifest")
    for path, entry in expected.items():
        actual = output / path
        if actual.read_bytes() != entry["content"] or (actual.stat().st_mode & 0o777) != (0o755 if entry["mode"] == "100755" else 0o644):
            raise SourceValidationError("Export source bytes or permissions differ from the pinned commit")
    data = _canonical(manifest)
    if (output / MANIFEST_NAME).read_bytes() != data:
        raise SourceValidationError("Export manifest differs from pinned sources")
    digest = f"{sha256(data).hexdigest()}  {MANIFEST_NAME}\n".encode("ascii")
    if (output / MANIFEST_HASH_NAME).read_bytes() != digest:
        raise SourceValidationError("Export manifest checksum differs")
    return manifest


def self_test(repository: Path) -> None:
    """Focused standard-library checks; no dependencies, secrets, DB or cloud."""
    class PinnedSourceChecks(unittest.TestCase):
        def test_deterministic_export_and_exact_accepted_boundary(self):
            with tempfile.TemporaryDirectory(prefix="flare-schema21-export-check-") as temporary:
                first, second = Path(temporary) / "first", Path(temporary) / "second"
                a, b = build_sources(repository, first), build_sources(repository, second)
                self.assertEqual(a, b)
                self.assertEqual(verify_sources(repository, first), a)
                self.assertEqual((first / MANIFEST_NAME).read_bytes(), (second / MANIFEST_NAME).read_bytes())
                self.assertEqual((first / DATABASE_PATH).read_bytes(), _git(repository, "show", f"{ACCEPTED_DATABASE_SHA}:{DATABASE_PATH}"))
                self.assertEqual(a["accepted_substitutions"], [DATABASE_PATH])
                self.assertFalse((first / "backend/migrations").exists())
                self.assertFalse((first / "backend/app/api/billing.py").exists())

        def test_output_refused_and_tampering_detected(self):
            with tempfile.TemporaryDirectory(prefix="flare-schema21-tamper-check-") as temporary:
                output = Path(temporary) / "export"
                build_sources(repository, output)
                with self.assertRaises(SourceValidationError):
                    build_sources(repository, output)
                original = (output / DATABASE_PATH).read_bytes()
                (output / DATABASE_PATH).write_bytes(original + b"\n# tamper\n")
                with self.assertRaises(SourceValidationError):
                    verify_sources(repository, output)
                (output / DATABASE_PATH).write_bytes(original)
                (output / MANIFEST_NAME).write_text("{}\n")
                with self.assertRaises(SourceValidationError):
                    verify_sources(repository, output)
                (output / MANIFEST_NAME).write_bytes(_canonical(_manifest(_pinned_sources(repository))))
                (output / ".env").write_text("not-a-real-secret\n")
                with self.assertRaises(SourceValidationError):
                    verify_sources(repository, output)
                (output / ".env").unlink()
                (output / MANIFEST_HASH_NAME).write_text("0" * 64 + "  " + MANIFEST_NAME + "\n")
                with self.assertRaises(SourceValidationError):
                    verify_sources(repository, output)

        def test_secret_paths_and_symlinks_rejected(self):
            for path in ("../.env", "/tmp/file", "backend/.env", "frontend/.env.local", "private.pem"):
                with self.assertRaises(SourceValidationError):
                    _validate_blob(path, b"placeholder")
            with self.assertRaises(SourceValidationError):
                _validate_blob("frontend/src/key.txt", b"-----BEGIN PRIVATE KEY-----")
            with tempfile.TemporaryDirectory(prefix="flare-schema21-link-check-") as temporary:
                output = Path(temporary) / "link"
                output.symlink_to(Path(temporary), target_is_directory=True)
                with self.assertRaises(SourceValidationError):
                    build_sources(repository, output)

    suite = unittest.defaultTestLoader.loadTestsFromTestCase(PinnedSourceChecks)
    if not unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful():
        raise SourceValidationError("Pinned source checks failed")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", type=Path, default=Path.cwd())
    parser.add_argument("--output", type=Path)
    parser.add_argument("--verify", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    arguments = parser.parse_args()
    if arguments.self_test:
        self_test(arguments.repository)
        return
    if arguments.output is None:
        parser.error("--output is required unless --self-test is used")
    manifest = (verify_sources if arguments.verify else build_sources)(arguments.repository, arguments.output)
    print(json.dumps({key: manifest[key] for key in (
        "legacy_core_sha", "accepted_database_sha", "schema_revision", "database_sha256", "sources_sha256",
    )}, sort_keys=True))


if __name__ == "__main__":
    main()
