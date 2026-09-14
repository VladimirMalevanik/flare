"""Bounded, transactional ingestion of CSV, TXT and Markdown text files."""

import csv
import io
import re
from dataclasses import dataclass, replace
from hashlib import sha256
from typing import Iterable, Literal
from uuid import UUID, uuid4

from app.models.database import Database, WorkspaceIdentity
from app.models.import_batches import ImportBatchRecord, ImportBatchRepository, ImportFormat
from app.models.tables import ItemRecord, ItemRepository


# The API accepts JSON text for its first version.  Keeping this bound modest
# makes the full transaction and database storage predictable until object
# storage and streamed uploads are introduced.
MAX_IMPORT_BYTES = 200_000
MAX_IMPORT_ROWS = 20_000
MAX_IMPORT_CHUNKS = 2_000
IMPORT_CHUNK_TARGET_BYTES = 4_000


class ImportValidationError(ValueError):
    """A client-safe validation failure.  Messages must never include file text."""

    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code = code
        self.detail = detail


class ImportNotFoundError(Exception):
    """The batch does not exist in the caller's workspace."""


class ImportUnavailableError(Exception):
    """A database invariant was broken without exposing source content."""


@dataclass(frozen=True)
class ChunkSpec:
    content: str
    locator: dict[str, object]


@dataclass(frozen=True)
class CsvRecord:
    content: str
    record_number: int
    line_start: int
    line_end: int


@dataclass(frozen=True)
class PreparedImport:
    format: ImportFormat
    file_name: str
    file_type: str | None
    file_size: int
    file_hash: str
    content_hash: str
    content: str
    row_count: int | None
    chunks: tuple[ChunkSpec, ...]


@dataclass(frozen=True)
class ImportResult:
    batch: ImportBatchRecord
    item: ItemRecord
    created: bool


_EXTENSIONS: dict[str, set[str]] = {
    "csv": {".csv"},
    "txt": {".txt"},
    "md": {".md", ".markdown"},
}
_MARKDOWN_HEADING = re.compile(r"^(#{1,6})[ \t]+(.+?)(?:[ \t]+#+)?[ \t]*$")


class ImportService:
    """Create exactly one file item and a durable batch record per import."""

    def __init__(self, database: Database, identity: WorkspaceIdentity):
        self._database = database
        self._identity = identity

    def create_import(
        self,
        *,
        format: ImportFormat,
        file_name: str,
        file_type: str | None,
        file_size: int,
        content: str,
    ) -> ImportResult:
        prepared = self.prepare_content(
            format=format,
            file_name=file_name,
            file_type=file_type,
            file_size=file_size,
            content=content,
        )
        with self._database.workspace_transaction(self._identity, write=True) as connection:
            batches = ImportBatchRepository(connection)
            batch_id = uuid4()
            inserted = batches.insert_pending(
                batch_id=batch_id,
                workspace_id=self._identity.workspace_id,
                requested_by_user_id=self._identity.user_id,
                format=prepared.format,
                file_name=prepared.file_name,
                file_type=prepared.file_type,
                file_size=prepared.file_size,
                file_hash=prepared.file_hash,
            )
            if inserted is None:
                existing = batches.get_by_hash(
                    workspace_id=self._identity.workspace_id,
                    format=prepared.format,
                    file_hash=prepared.file_hash,
                )
                if existing is None or existing.document_id is None or existing.status != "completed":
                    raise ImportUnavailableError("Import batch is unavailable")
                repository = ItemRepository(connection)
                current = repository.get_active(existing.document_id)
                if current is not None and current.content == prepared.content:
                    if existing.document_version_id is None:
                        raise ImportUnavailableError("Import batch is unavailable")
                    historical = repository.get_version(
                        existing.document_id,
                        existing.document_version_id,
                    )
                    if historical is None:
                        raise ImportUnavailableError("Import batch is unavailable")
                    return ImportResult(batch=existing, item=historical, created=False)

                # A deleted or replaced source no longer represents these bytes.
                # Retain its exact historical batch/version link, deactivate it
                # for deduplication, then create a new active import.
                batches.supersede_for_document(existing.document_id)
                inserted = batches.insert_pending(
                    batch_id=batch_id,
                    workspace_id=self._identity.workspace_id,
                    requested_by_user_id=self._identity.user_id,
                    format=prepared.format,
                    file_name=prepared.file_name,
                    file_type=prepared.file_type,
                    file_size=prepared.file_size,
                    file_hash=prepared.file_hash,
                )
                if inserted is None:
                    raise ImportUnavailableError("Import batch is unavailable")

            item_id, version_id = uuid4(), uuid4()
            repository = ItemRepository(connection)
            item_title = _title_from_file_name(prepared.file_name)
            item_metadata = _document_metadata(prepared, batch_id)
            repository.insert_document(
                item_id=item_id,
                workspace_id=self._identity.workspace_id,
                title=item_title,
                item_type="file",
                source_url=None,
                metadata=item_metadata,
            )
            repository.insert_version(
                version_id=version_id,
                workspace_id=self._identity.workspace_id,
                document_id=item_id,
                content_hash=prepared.content_hash,
                parser_version=f"import-{prepared.format}-v1",
                snapshot_title=item_title,
                snapshot_source_url=None,
                snapshot_metadata=item_metadata,
            )
            chunk_ids: list[UUID] = []
            for ordinal, chunk in enumerate(prepared.chunks):
                chunk_id = uuid4()
                chunk_ids.append(chunk_id)
                repository.insert_chunk(
                    chunk_id=chunk_id,
                    workspace_id=self._identity.workspace_id,
                    version_id=version_id,
                    ordinal=ordinal,
                    content=chunk.content,
                    locator=chunk.locator,
                )
            repository.publish_version(document_id=item_id, version_id=version_id)
            completed = batches.mark_completed(
                batch_id=batch_id,
                document_id=item_id,
                document_version_id=version_id,
                row_count=prepared.row_count,
                chunk_count=len(chunk_ids),
                analysis_jobs_queued=0,
            )
            item = repository.get_active(item_id)
            if item is None:
                raise ImportUnavailableError("Imported item could not be read back")
            return ImportResult(batch=completed, item=item, created=True)

    def get_import(self, batch_id: UUID) -> ImportResult:
        with self._database.workspace_transaction(self._identity) as connection:
            batch = ImportBatchRepository(connection).get(batch_id)
            if batch is None or batch.document_id is None or batch.status != "completed":
                raise ImportNotFoundError
            if batch.document_version_id is None:
                raise ImportNotFoundError
            item = ItemRepository(connection).get_version(
                batch.document_id,
                batch.document_version_id,
            )
            if item is None:
                raise ImportNotFoundError
            return ImportResult(batch=batch, item=item, created=False)

    @staticmethod
    def prepare_content(
        *,
        format: ImportFormat,
        file_name: str,
        file_type: str | None,
        file_size: int,
        content: str,
    ) -> PreparedImport:
        normalized_name = _validate_file_name(file_name, format)
        normalized_type = _validate_file_type(file_type, format)
        raw_bytes = _utf8_bytes(content)
        if len(raw_bytes) > MAX_IMPORT_BYTES:
            raise ImportValidationError(
                "payload_too_large",
                f"content exceeds the {MAX_IMPORT_BYTES:,}-byte import limit",
            )
        if not isinstance(file_size, int) or isinstance(file_size, bool) or file_size < 0:
            raise ImportValidationError("invalid_file_size", "fileSize must be a non-negative byte count")
        if file_size != len(raw_bytes):
            raise ImportValidationError(
                "file_size_mismatch",
                "fileSize must equal the UTF-8 byte length of content",
            )
        if file_size == 0:
            raise ImportValidationError("empty_file", "content must contain UTF-8 text")
        _reject_binary_text(content)

        # A leading UTF-8 BOM is transport metadata, not part of the textual
        # document. It is accepted and stripped before parsing/storage so CSV
        # headers and Markdown headings remain usable.
        text = content[1:] if content.startswith("\ufeff") else content
        if not text.strip():
            raise ImportValidationError("empty_file", "content must contain UTF-8 text")
        content_hash = sha256(text.encode("utf-8")).hexdigest()
        file_hash = sha256(raw_bytes).hexdigest()
        target_bytes = IMPORT_CHUNK_TARGET_BYTES

        if format == "csv":
            records = _parse_csv(text)
            chunks = _csv_chunks(records, target_bytes)
            row_count: int | None = len(records) - 1
        elif format == "md":
            chunks = _markdown_chunks(text, target_bytes)
            row_count = None
        else:
            chunks = _text_chunks(text, target_bytes, format="txt")
            row_count = None
        if not chunks or any(not chunk.content for chunk in chunks):
            raise ImportValidationError("empty_file", "content must contain UTF-8 text")
        if len(chunks) > MAX_IMPORT_CHUNKS:
            raise ImportValidationError(
                "too_many_chunks",
                "Import would exceed the 2000-chunk safety limit; split the file into smaller files",
            )
        if "".join(chunk.content for chunk in chunks) != text:
            raise RuntimeError("Import chunker did not preserve source text")
        return PreparedImport(
            format=format,
            file_name=normalized_name,
            file_type=normalized_type,
            file_size=file_size,
            file_hash=file_hash,
            content_hash=content_hash,
            content=text,
            row_count=row_count,
            chunks=tuple(chunks),
        )


def _utf8_bytes(content: str) -> bytes:
    try:
        return content.encode("utf-8")
    except UnicodeEncodeError:
        raise ImportValidationError("invalid_encoding", "content must be valid UTF-8 text") from None


def _validate_file_name(file_name: str, format: ImportFormat) -> str:
    if not isinstance(file_name, str):
        raise ImportValidationError("invalid_file_name", "fileName must be a file name")
    normalized = file_name.strip()
    if not normalized or len(normalized) > 300 or "/" in normalized or "\\" in normalized:
        raise ImportValidationError("invalid_file_name", "fileName must be a simple name up to 300 characters")
    extension = normalized[normalized.rfind(".") :].lower() if "." in normalized else ""
    if extension not in _EXTENSIONS[format]:
        expected = ", ".join(sorted(_EXTENSIONS[format]))
        raise ImportValidationError(
            "format_extension_mismatch",
            f"format '{format}' requires a fileName ending in {expected}",
        )
    return normalized


def _validate_file_type(file_type: str | None, format: ImportFormat) -> str | None:
    if file_type is None:
        return None
    if not isinstance(file_type, str):
        raise ImportValidationError("invalid_file_type", "fileType must be a MIME type")
    normalized = file_type.split(";", 1)[0].strip().lower()
    # Browser MIME detection is advisory: Safari and mobile browsers commonly
    # label perfectly valid text files as application/octet-stream. The suffix,
    # UTF-8 validation and parser establish what we actually accept. Keep a
    # well-formed advisory value for display, otherwise omit it from metadata.
    if not normalized or len(normalized) > 120 or any(ord(char) < 32 for char in normalized):
        return None
    return normalized


def _reject_binary_text(content: str) -> None:
    if "\x00" in content or any(ord(char) < 32 and char not in "\t\n\r" for char in content):
        raise ImportValidationError("binary_content", "content must be UTF-8 text, not binary data")


def _parse_csv(text: str) -> tuple[CsvRecord, ...]:
    physical_lines = text.splitlines(keepends=True)
    reader = csv.reader(io.StringIO(text, newline=""), strict=True)
    records: list[CsvRecord] = []
    rows: list[list[str]] = []
    previous_line = 0
    pending_prefix = ""
    pending_line_start: int | None = None
    try:
        for row in reader:
            end_line = reader.line_num
            start_line_index = previous_line
            raw = "".join(physical_lines[start_line_index:end_line])
            previous_line = end_line
            if not row and not raw.strip():
                if pending_line_start is None:
                    pending_line_start = start_line_index + 1
                pending_prefix += raw
                continue
            if not raw:
                raise ImportValidationError("invalid_csv", "CSV contains an invalid empty record")
            record_number = len(records) + 1
            if record_number > MAX_IMPORT_ROWS + 1:
                raise ImportValidationError(
                    "too_many_rows",
                    "CSV exceeds the 20000-row import safety limit",
                )
            records.append(
                CsvRecord(
                    content=pending_prefix + raw,
                    record_number=record_number,
                    line_start=pending_line_start or start_line_index + 1,
                    line_end=max(1, end_line),
                )
            )
            rows.append(row)
            pending_prefix = ""
            pending_line_start = None
    except csv.Error:
        raise ImportValidationError("invalid_csv", "CSV is not valid RFC-style CSV text") from None

    if not records:
        raise ImportValidationError("invalid_csv", "CSV must contain a header row")
    tail = pending_prefix + "".join(physical_lines[previous_line:])
    if tail:
        last = records[-1]
        records[-1] = replace(last, content=last.content + tail, line_end=len(physical_lines))
    header = rows[0]
    if not header or not any(cell.strip() for cell in header):
        raise ImportValidationError("invalid_csv", "CSV must contain a non-empty header row")
    expected_columns = len(header)
    if any(len(row) != expected_columns for row in rows[1:]):
        raise ImportValidationError("invalid_csv", "CSV rows must have the same number of columns as the header")
    return tuple(records)


def _csv_chunks(records: tuple[CsvRecord, ...], max_bytes: int) -> list[ChunkSpec]:
    chunks: list[ChunkSpec] = []
    buffered: list[CsvRecord] = []
    buffered_bytes = 0

    def flush() -> None:
        nonlocal buffered, buffered_bytes
        if not buffered:
            return
        first, last = buffered[0], buffered[-1]
        chunks.append(
            ChunkSpec(
                content="".join(record.content for record in buffered),
                locator={
                    "kind": "import",
                    "format": "csv",
                    "rowStart": first.record_number,
                    "rowEnd": last.record_number,
                    "lineStart": first.line_start,
                    "lineEnd": last.line_end,
                },
            )
        )
        buffered, buffered_bytes = [], 0

    for record in records:
        size = _byte_length(record.content)
        if size > max_bytes:
            flush()
            for part_number, part in enumerate(_split_exact(record.content, max_bytes), start=1):
                chunks.append(
                    ChunkSpec(
                        content=part,
                        locator={
                            "kind": "import",
                            "format": "csv",
                            "rowStart": record.record_number,
                            "rowEnd": record.record_number,
                            "lineStart": record.line_start,
                            "lineEnd": record.line_end,
                            "part": part_number,
                        },
                    )
                )
            continue
        if buffered and buffered_bytes + size > max_bytes:
            flush()
        buffered.append(record)
        buffered_bytes += size
    flush()
    return chunks


def _markdown_chunks(text: str, max_bytes: int) -> list[ChunkSpec]:
    lines = text.splitlines(keepends=True)
    starts = [0]
    headings: dict[int, str] = {}
    for index, line in enumerate(lines):
        match = _MARKDOWN_HEADING.match(line.rstrip("\r\n"))
        if match:
            headings[index] = match.group(2).strip()[:160]
            if index and index not in starts:
                starts.append(index)
    starts.sort()
    chunks: list[ChunkSpec] = []
    for position, start in enumerate(starts):
        end = starts[position + 1] if position + 1 < len(starts) else len(lines)
        section = "".join(lines[start:end])
        if not section:
            continue
        section_name = headings.get(start, "Preamble")
        line_start = start + 1
        offset = 0
        for part_number, part in enumerate(_split_exact(section, max_bytes), start=1):
            chunks.append(
                ChunkSpec(
                    content=part,
                    locator={
                        "kind": "import",
                        "format": "md",
                        "section": section_name,
                        "lineStart": line_start + section[:offset].count("\n"),
                        "lineEnd": line_start + section[: offset + len(part)].count("\n"),
                        "part": part_number,
                    },
                )
            )
            offset += len(part)
    return chunks


def _text_chunks(text: str, max_bytes: int, *, format: Literal["txt"]) -> list[ChunkSpec]:
    chunks: list[ChunkSpec] = []
    offset = 0
    for part_number, part in enumerate(_split_exact(text, max_bytes), start=1):
        chunks.append(
            ChunkSpec(
                content=part,
                locator={
                    "kind": "import",
                    "format": format,
                    "lineStart": text[:offset].count("\n") + 1,
                    "lineEnd": text[: offset + len(part)].count("\n") + 1,
                    "part": part_number,
                },
            )
        )
        offset += len(part)
    return chunks


def _split_exact(text: str, max_bytes: int) -> Iterable[str]:
    """Split without altering characters, preferring paragraph/line boundaries."""
    if max_bytes < 1:
        raise ImportValidationError("invalid_analysis_limit", "LLM input byte limit must be positive")
    start = 0
    length = len(text)
    while start < length:
        index = start
        used = 0
        preferred_end: int | None = None
        while index < length:
            character_size = _byte_length(text[index])
            if character_size > max_bytes and index == start:
                raise ImportValidationError(
                    "invalid_analysis_limit",
                    "LLM input byte limit is too small for this UTF-8 text",
                )
            if used + character_size > max_bytes:
                break
            used += character_size
            index += 1
            if text[index - 1] in "\n\r\t ":
                preferred_end = index
        if index == start:
            raise ImportValidationError("invalid_analysis_limit", "LLM input byte limit is too small")
        end = length if index == length else (preferred_end or index)
        if end <= start:
            end = index
        yield text[start:end]
        start = end


def _byte_length(value: str) -> int:
    return len(value.encode("utf-8"))


def _title_from_file_name(file_name: str) -> str:
    stem = file_name.rsplit(".", 1)[0].strip()
    return (stem or file_name)[:300].rstrip()


def _document_metadata(prepared: PreparedImport, batch_id: UUID) -> dict[str, object]:
    metadata: dict[str, object] = {
        "sourceType": "file",
        "fileName": prepared.file_name,
        "fileSize": prepared.file_size,
        "originImportBatchId": str(batch_id),
        "importFormat": prepared.format,
    }
    if prepared.file_type:
        metadata["fileType"] = prepared.file_type
    if prepared.row_count is not None:
        metadata["rowCount"] = prepared.row_count
    return metadata
