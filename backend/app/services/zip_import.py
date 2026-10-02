"""Bounded ZIP validation. Never extract archive paths or invoke content/providers."""
from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import PurePosixPath
import re
import stat
import struct
import time
import unicodedata
import zipfile
import zlib

from app.import_staging.policy import ImportPolicy
from app.services.import_service import ImportService, ImportValidationError


class ZipRejected(ValueError):
    """Only stable codes escape to status. Never expose archive text or decoder errors."""


def preflight(stream, policy: ImportPolicy):
    stream.seek(0, 2)
    size = stream.tell()
    if size > policy.compressed_bytes or size > policy.scratch_bytes:
        raise ZipRejected("compressed_bytes")
    stream.seek(max(0, size - 65_557))
    tail = stream.read(65_557)
    offset = tail.rfind(b"PK\x05\x06")
    if offset < 0 or offset + 22 > len(tail):
        raise ZipRejected("malformed_zip")
    _, disk, start_disk, disk_count, count, directory_size, directory_offset, comment = struct.unpack_from("<4s4H2LH", tail, offset)
    if offset + 22 + comment != len(tail) or disk or start_disk or disk_count != count:
        raise ZipRejected("malformed_zip")
    # ZIP64/multi-volume is explicitly unsupported by this bounded v1 adapter.
    # Refuse sentinel values BEFORE ZipFile allocates directory objects.
    if count == 65535 or directory_size == 0xffffffff or directory_offset == 0xffffffff:
        raise ZipRejected("unsupported_zip64")
    if count > policy.entries or directory_size > policy.directory_bytes:
        raise ZipRejected("manifest_bound")
    absolute_end = size - len(tail) + offset
    if directory_offset + directory_size != absolute_end:
        raise ZipRejected("malformed_zip")
    # Count actual central headers before ZipFile constructs its entry objects.
    # A dishonest EOCD count cannot bypass the allocation/entry bound.
    cursor=directory_offset
    actual=0
    while cursor<absolute_end:
        if cursor+46>absolute_end:
            raise ZipRejected('malformed_zip')
        stream.seek(cursor)
        header=stream.read(46)
        if len(header)!=46 or header[:4]!=b'PK\x01\x02':
            raise ZipRejected('malformed_zip')
        name_size,extra_size,comment_size=struct.unpack_from('<3H',header,28)
        cursor+=46+name_size+extra_size+comment_size
        actual+=1
        if actual>policy.entries:
            raise ZipRejected('manifest_bound')
    if cursor!=absolute_end or actual!=count:
        raise ZipRejected('malformed_zip')
    stream.seek(0)
    return count, directory_offset


def safe_path(info, policy: ImportPolicy):
    path = info.orig_filename
    if (not path or path.startswith("/") or "\\" in path or re.match(r"^[A-Za-z]:", path)
            or any(unicodedata.category(c) in {"Cc","Cf"} for c in path)):
        raise ZipRejected("unsafe_path")
    parts = (path[:-1] if info.is_dir() else path).split("/")
    if any(p in {"", ".", ".."} or any(c in p for c in '<>:"|?*') or p.endswith((".", " "))
            or re.fullmatch(r"(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?",p,re.I) for p in parts):
        raise ZipRejected("unsafe_path")
    if len(path.encode("utf-8")) > policy.path_bytes or len(parts) > policy.path_depth:
        raise ZipRejected("path_bound")
    if any(len(p.encode("utf-8")) > policy.segment_bytes for p in parts):
        raise ZipRejected("path_bound")
    mode = stat.S_IFMT(info.external_attr >> 16)
    if mode not in {0, stat.S_IFREG, stat.S_IFDIR}:
        raise ZipRejected("special_entry")
    if bool(mode == stat.S_IFDIR) and not info.is_dir():
        raise ZipRejected("special_entry")
    return path, unicodedata.normalize("NFC", path.rstrip("/")).casefold()


def skip_reason(path: str):
    parts = PurePosixPath(path).parts
    if any(p.casefold() in {".obsidian", ".git", "__macosx", ".trash", ".vscode"} for p in parts):
        return "application_configuration"
    if any(p.casefold() in {".ds_store", ".env", "desktop.ini", "thumbs.db"} for p in parts):
        return "application_configuration"
    suffix = PurePosixPath(path).suffix.lower()
    if suffix not in {".md", ".markdown", ".txt", ".csv"}:
        return "unsupported_format"
    return None


def manifest(stream, policy: ImportPolicy):
    started = time.monotonic()
    count, directory_offset = preflight(stream, policy)
    archive = zipfile.ZipFile(stream)
    try:
        infos = archive.infolist()
        if len(infos) != count:
            raise ZipRejected("malformed_zip")
        result, keys, expanded, output_size = [], {}, 0, 0
        for index, info in enumerate(infos):
            if time.monotonic() - started > policy.inspect_seconds:
                raise ZipRejected("inspect_deadline")
            path, key = safe_path(info, policy)
            if key in keys:
                raise ZipRejected("path_collision")
            keys[key] = info.is_dir()
            if info.flag_bits & (1 | 64):
                raise ZipRejected("encrypted_zip")
            if info.compress_type not in {zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED}:
                raise ZipRejected("compression_method")
            if info.file_size > policy.file_bytes:
                raise ZipRejected("file_bytes")
            expanded += info.file_size
            if expanded > policy.expanded_bytes:
                raise ZipRejected("expanded_bytes")
            if info.file_size / max(1, info.compress_size) > policy.expansion_ratio:
                raise ZipRejected("expansion_ratio")
            if info.header_offset < 0 or info.header_offset + 30 + info.compress_size > directory_offset:
                raise ZipRejected("malformed_zip")
            row = {"ordinal": index, "path": path, "canonicalPath": key,
                   "fileBytes": info.file_size, "skipReason": "directory" if info.is_dir() else skip_reason(path)}
            output_size += len(json.dumps(row, ensure_ascii=False).encode("utf-8"))
            if output_size > policy.manifest_bytes:
                raise ZipRejected("manifest_bound")
            result.append(row)
        for key in keys:
            parts = key.split("/")
            if any(keys.get("/".join(parts[:i])) is False for i in range(1, len(parts))):
                raise ZipRejected("path_collision")
        return result
    finally:
        archive.close()


def verified_bytes(stream, archive, info, policy: ImportPolicy, remaining: int):
    """Verify actual decompression/CRC including skipped files; dishonest file_size cannot truncate output.

    zipfile validates local headers/overlap; raw zlib additionally measures the full
    declared compressed stream instead of trusting ZipExtFile's output-size cap.
    """
    started = time.monotonic()
    _,directory_offset=preflight(stream,policy)
    boundary=min([directory_offset]+[entry.header_offset for entry in archive.infolist() if entry.header_offset>info.header_offset])
    with archive.open(info):
        pass
    stream.seek(info.header_offset)
    header = stream.read(30)
    if len(header) != 30 or header[:4] != b"PK\x03\x04":
        raise ZipRejected("malformed_zip")
    _, _, flags, method, _, _, crc, compressed, expanded, name_size, extra_size = struct.unpack("<4s5H3L2H", header)
    if flags & (1 | 64) or method != info.compress_type or flags != info.flag_bits:
        raise ZipRejected("malformed_zip")
    if not flags & 8 and (crc, compressed, expanded) != (info.CRC, info.compress_size, info.file_size):
        raise ZipRejected("dishonest_metadata")
    data_start = info.header_offset + 30 + name_size + extra_size
    if data_start+info.compress_size>boundary:
        raise ZipRejected('malformed_zip')
    stream.seek(data_start)
    decoder = zlib.decompressobj(-15) if method == zipfile.ZIP_DEFLATED else None
    count, actual_crc, digest, output = 0, 0, hashlib.sha256(), bytearray()
    left = info.compress_size
    while left:
        block = stream.read(min(left, 64 * 1024))
        if not block:
            raise ZipRejected("malformed_zip")
        left -= len(block)
        pending = block
        while pending:
            if time.monotonic() - started > policy.file_seconds:
                raise ZipRejected("file_deadline")
            value = decoder.decompress(pending, 64 * 1024) if decoder else pending
            pending = decoder.unconsumed_tail if decoder else b""
            count += len(value)
            if count > policy.file_bytes or count > remaining:
                raise ZipRejected("expanded_bytes")
            actual_crc = zlib.crc32(value, actual_crc)
            digest.update(value)
            # The process/file policy bounds this buffer, including skipped assets.
            output.extend(value)
            if decoder and decoder.unused_data:
                raise ZipRejected("malformed_zip")
    if flags & 8:
        descriptor_offset=data_start+info.compress_size
        stream.seek(descriptor_offset)
        descriptor=stream.read(min(16,boundary-descriptor_offset))
        signed=descriptor.startswith(b'PK\x07\x08')
        needed=16 if signed else 12
        if len(descriptor)<needed or struct.unpack_from('<3L',descriptor,4 if signed else 0)!=(info.CRC,info.compress_size,info.file_size):
            raise ZipRejected('integrity_failure')
    if decoder and not decoder.eof:
        raise ZipRejected("malformed_zip")
    if count != info.file_size or actual_crc != info.CRC:
        raise ZipRejected("integrity_failure")
    return bytes(output), digest.hexdigest()


def parse_entry(raw: bytes, row: dict, policy: ImportPolicy):
    reason = row["skipReason"]
    if reason:
        return {"status": "skipped", "reason": reason, "chunks": []}
    try:
        text = raw.decode("utf-8", errors="strict")
        suffix = PurePosixPath(row["path"]).suffix.lower()
        format = "md" if suffix in {".md", ".markdown"} else suffix[1:]
        prepared = ImportService.prepare_content(format=format, file_name=PurePosixPath(row["path"]).name,
                    file_type=None, file_size=len(raw), content=text, limits=policy)
    except (UnicodeError, ImportValidationError) as error:
        raise ZipRejected(error.code if isinstance(error, ImportValidationError) else "invalid_utf8") from None
    # The immutable source schema forbids whitespace-only chunks. Fold short
    # whitespace sections into a neighbour without changing a single character.
    # A gap too large to represent under chunk_bytes is a policy failure.
    chunks=list(prepared.chunks)
    index=0
    while index<len(chunks):
        chunk=chunks[index]
        if chunk.content.strip():
            index+=1
            continue
        neighbour=index-1 if index and len((chunks[index-1].content+chunk.content).encode('utf-8'))<=policy.chunk_bytes else index+1
        if neighbour>=len(chunks) or len((chunks[neighbour].content+chunk.content).encode('utf-8'))>policy.chunk_bytes:
            raise ZipRejected('chunk_bound')
        previous=chunks[neighbour]
        content=previous.content+chunk.content if neighbour<index else chunk.content+previous.content
        locator={**previous.locator,'lineStart':min(previous.locator.get('lineStart',1),chunk.locator.get('lineStart',1)),
                 'lineEnd':max(previous.locator.get('lineEnd',1),chunk.locator.get('lineEnd',1))}
        chunks[neighbour]=replace(previous,content=content,locator=locator)
        chunks.pop(index)
        index=max(0,index-1)
    return {"status": "prepared", "format": format, "contentHash": prepared.content_hash,
            "contentBytes": len(prepared.content.encode("utf-8")),
            "chunks": [{"content": c.content, "locator": {**c.locator, "relativePath": row["path"]}}
                       for c in chunks]}
