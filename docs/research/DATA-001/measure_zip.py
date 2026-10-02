"""Bounded synthetic ZIP research, not a production parser or product limits.

Run with Python 3.11+: python measure_zip.py --output measurements.json
Only temporary synthetic files are read/written; there is no network or DB access.
"""
from __future__ import annotations

import argparse
import codecs
import hashlib
import io
import json
import os
import platform
import random
import re
import resource
import stat
import subprocess
import sys
import tempfile
import time
import tracemalloc
import unicodedata
import warnings
import zipfile
from dataclasses import dataclass, replace
from pathlib import Path


@dataclass(frozen=True)
class FixtureBounds:
    # These exercise rejection paths. They are NOT proposed Flare settings.
    compressed: int = 2 * 1024 * 1024
    expanded: int = 2 * 1024 * 1024
    per_file: int = 1024 * 1024
    entries: int = 10
    depth: int = 8
    ratio: int = 200


def guard_metadata(entries: list[zipfile.ZipInfo], bounds: FixtureBounds) -> None:
    """Illustrate policy checks only, AFTER zipfile has allocated its directory.

    A real worker also needs a preallocation directory bound and process limits.
    """
    if len(entries) > bounds.entries:
        raise ValueError("entry_count")
    names: set[str] = set()
    total = 0
    for entry in entries:
        path = entry.orig_filename
        if (not path or any(ord(c) < 32 for c in path) or "\\" in path
                or path.startswith("/") or re.match(r"^[A-Za-z]:", path)):
            raise ValueError("unsafe_path")
        parts = path.rstrip("/").split("/")
        if any(p in {"", ".", ".."} for p in parts):
            raise ValueError("unsafe_path")
        if len(parts) > bounds.depth:
            raise ValueError("path_depth")
        canonical = unicodedata.normalize("NFC", path.rstrip("/")).casefold()
        if canonical in names:
            raise ValueError("path_collision")
        names.add(canonical)
        mode = (entry.external_attr >> 16) & 0xFFFF
        kind = stat.S_IFMT(mode)
        if kind not in {0, stat.S_IFREG, stat.S_IFDIR}:
            raise ValueError("special_entry")
        if entry.flag_bits & (1 | 64):
            raise ValueError("encrypted")
        if entry.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}:
            raise ValueError("compression_method")
        total += entry.file_size
        if entry.file_size > bounds.per_file:
            raise ValueError("file_bytes")
        if total > bounds.expanded:
            raise ValueError("expanded_bytes")
        if entry.file_size / max(1, entry.compress_size) > bounds.ratio:
            raise ValueError("compression_ratio")


def inspect_fixture(raw: bytes, bounds: FixtureBounds) -> str:
    if len(raw) > bounds.compressed:
        return "compressed_bytes"
    try:
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            guard_metadata(archive.infolist(), bounds)
            actual = 0
            for entry in archive.infolist():
                if entry.is_dir():
                    continue
                count = 0
                with archive.open(entry) as stream:
                    while block := stream.read(16 * 1024):
                        count += len(block)
                        actual += len(block)
                        if count > bounds.per_file or actual > bounds.expanded:
                            return "actual_bytes"
                if count != entry.file_size:
                    return "size_mismatch"
        return "accepted"
    except ValueError as exc:
        return str(exc)
    except zipfile.BadZipFile:
        return "bad_zip_or_crc"


def make_fixture(paths: list[str], content: bytes = b"# synthetic note\n",
                 special_mode: int | None = None, compression: int = zipfile.ZIP_DEFLATED) -> bytes:
    output = io.BytesIO()
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)
        with zipfile.ZipFile(output, "w") as archive:
            for path in paths:
                info = zipfile.ZipInfo(path)
                info.compress_type = compression
                if special_mode is not None:
                    info.create_system = 3
                    info.external_attr = special_mode << 16
                archive.writestr(info, content)
    return output.getvalue()


def security_fixtures() -> list[dict]:
    b = FixtureBounds()
    good = make_fixture(["Vault/notes/one.md"])
    encrypted = bytearray(good)
    # Change both local and central flags; no real password material is used.
    for marker, offset in [(b"PK\x03\x04", 6), (b"PK\x01\x02", 8)]:
        start = encrypted.index(marker) + offset
        encrypted[start] |= 1
    corrupt = bytearray(make_fixture(["one.md"], b"integrity", compression=zipfile.ZIP_STORED))
    corrupt[corrupt.index(b"integrity")] ^= 1
    cases = [
        ("valid_relative", good, b, "accepted"),
        ("parent_traversal", make_fixture(["../outside.md"]), b, "unsafe_path"),
        ("absolute", make_fixture(["/outside.md"]), b, "unsafe_path"),
        ("windows_drive", make_fixture(["C:/outside.md"]), b, "unsafe_path"),
        ("backslash", make_fixture(["..\\outside.md"]), b, "unsafe_path"),
        ("duplicate", make_fixture(["a.md", "a.md"]), b, "path_collision"),
        ("case_collision", make_fixture(["A.md", "a.md"]), b, "path_collision"),
        ("unicode_collision", make_fixture(["caf\u00e9.md", "cafe\u0301.md"]), b, "path_collision"),
        ("symlink", make_fixture(["link.md"], special_mode=stat.S_IFLNK | 0o777), b, "special_entry"),
        ("encrypted_flags", bytes(encrypted), b, "encrypted"),
        ("too_many_entries", make_fixture([f"{i}.md" for i in range(11)]), b, "entry_count"),
        ("too_deep", make_fixture(["/".join(["a"] * 9) + ".md"]), b, "path_depth"),
        ("per_file_bytes", make_fixture(["big.md"], b"x" * 2048), replace(b, per_file=1024), "file_bytes"),
        ("aggregate_bytes", make_fixture(["a.md", "b.md"], b"x" * 800), replace(b, expanded=1000), "expanded_bytes"),
        ("compressed_bytes", good, replace(b, compressed=32), "compressed_bytes"),
        ("high_ratio", make_fixture(["repeat.md"], b"x" * 128_000), b, "compression_ratio"),
        ("bad_crc", bytes(corrupt), b, "bad_zip_or_crc"),
        ("invalid_zip", b"not a ZIP", b, "bad_zip_or_crc"),
    ]
    results = []
    for name, raw, bounds, expected in cases:
        actual = inspect_fixture(raw, bounds)
        results.append({"name": name, "compressed_bytes": len(raw), "expected": expected,
                        "actual": actual, "passed": actual == expected})
    assert all(r["passed"] for r in results), results
    return results


def measure(path: str) -> dict:
    tracemalloc.start()
    started = time.perf_counter()
    total = 0
    digest = hashlib.sha256()
    with zipfile.ZipFile(path) as archive:
        entries = archive.infolist()
        directory_seconds = time.perf_counter() - started
        declared_bytes = sum(e.file_size for e in entries)
        for entry in entries:
            decoder = codecs.getincrementaldecoder("utf-8")("strict")
            with archive.open(entry) as stream:
                while block := stream.read(64 * 1024):
                    total += len(block)
                    digest.update(block)
                    decoder.decode(block)
                decoder.decode(b"", final=True)
    seconds = time.perf_counter() - started
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    rss_bytes = rss if sys.platform == "darwin" else rss * 1024
    assert total == declared_bytes
    return {"entry_count": len(entries), "compressed_bytes": os.path.getsize(path),
            "expanded_bytes": total, "directory_seconds": directory_seconds,
            "total_seconds": seconds, "python_peak_allocated_bytes": peak,
            "process_peak_rss_bytes": rss_bytes, "content_sha256": digest.hexdigest()}


def run() -> dict:
    cases = [("100_notes_4KiB", 100, 4096), ("1000_notes_4KiB", 1000, 4096),
             ("1000_notes_64KiB", 1000, 65536), ("8MiB_repeated", 1, 8 * 1024 * 1024)]
    result = {"environment": {"python": sys.version, "platform": platform.platform(),
                              "machine": platform.machine(), "cpu_count": os.cpu_count()},
              "method": "Deflate level 6. Three fresh subprocess reads per case. Timed central-directory parse, streaming decompression, SHA-256, strict UTF-8 decode; no extraction, DB, chunking, network or AI. 64KiB read buffer. Generation excluded; local cache may be warm.",
              "security_fixtures": security_fixtures(), "cases": []}
    alphabet = b"abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 \n#_:-"
    rng = random.Random(1001)
    with tempfile.TemporaryDirectory(prefix="flare-data001-synthetic-") as folder:
        for name, count, size in cases:
            path = Path(folder) / f"{name}.zip"
            with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
                for index in range(count):
                    data = b"x" * size if name == "8MiB_repeated" else bytes(rng.choices(alphabet, k=size))
                    archive.writestr(f"Synthetic/section{index // 100}/note{index:05d}.md", data)
            samples = []
            for _ in range(3):
                completed = subprocess.run([sys.executable, __file__, "--child", str(path)],
                                           check=True, capture_output=True, text=True)
                samples.append(json.loads(completed.stdout))
            result["cases"].append({"name": name, "samples": samples})
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--child")
    parser.add_argument("--output", default=str(Path(__file__).with_name("measurements.json")))
    args = parser.parse_args()
    if args.child:
        print(json.dumps(measure(args.child)))
    else:
        evidence = run()
        Path(args.output).write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"output": args.output, "fixtures_passed": len(evidence["security_fixtures"]),
                          "cases": len(evidence["cases"]), "samples": 12}))
