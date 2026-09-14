"""Use cases for workspace-scoped knowledge items."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from typing import Any, Literal
from uuid import UUID, uuid4

from app.models.database import Database, WorkspaceIdentity
from app.models.import_batches import ImportBatchRepository
from app.models.tables import ItemRecord, ItemRepository
from app.services.import_service import ChunkSpec, ImportService, ImportValidationError


class ItemNotFoundError(Exception):
    """An active item is unavailable inside the caller's workspace."""


class ItemConflictError(Exception):
    """The caller edited a version that is no longer current."""


class ItemValidationError(ValueError):
    """A type-specific item update is invalid without exposing source text."""


@dataclass(frozen=True)
class ItemUpdateResult:
    item: ItemRecord
    changed: bool
    source_replaced: bool


class ItemService:
    def __init__(
        self,
        database: Database,
        identity: WorkspaceIdentity,
    ):
        self._database = database
        self._identity = identity

    def create_note(self, *, title: str | None, content: str) -> ItemRecord:
        return self.create_item(
            item_type="note",
            title=title,
            content=content,
            source_url=None,
            file_name=None,
            file_size=None,
            file_type=None,
        )

    def create_item(
        self,
        *,
        item_type: Literal["note", "url", "file", "audio"],
        title: str | None,
        content: str,
        source_url: str | None = None,
        file_name: str | None = None,
        file_size: int | None = None,
        file_type: str | None = None,
    ) -> ItemRecord:
        item_id, version_id, chunk_id = uuid4(), uuid4(), uuid4()
        resolved_title = title or self._title_from_content(content)
        content_hash = sha256(content.encode("utf-8")).hexdigest()
        metadata = self._metadata(
            item_type=item_type,
            source_url=source_url,
            file_name=file_name,
            file_size=file_size,
            file_type=file_type,
        )

        with self._database.workspace_transaction(self._identity, write=True) as connection:
            repository = ItemRepository(connection)
            repository.insert_document(
                item_id=item_id,
                workspace_id=self._identity.workspace_id,
                title=resolved_title,
                item_type=item_type,
                source_url=source_url,
                metadata=metadata,
            )
            repository.insert_version(
                version_id=version_id,
                workspace_id=self._identity.workspace_id,
                document_id=item_id,
                content_hash=content_hash,
                parser_version=self._parser_version(item_type),
                snapshot_title=resolved_title,
                snapshot_source_url=source_url,
                snapshot_metadata=metadata,
            )
            repository.insert_chunk(
                chunk_id=chunk_id,
                workspace_id=self._identity.workspace_id,
                version_id=version_id,
                content=content,
                locator=self._chunk_locator(
                    item_type=item_type,
                    source_url=source_url,
                    file_name=file_name,
                    file_type=file_type,
                ),
            )
            repository.publish_version(document_id=item_id, version_id=version_id)
            item = repository.get_active(item_id)
            if item is None:
                raise RuntimeError("Created item could not be read back")
            return item

    @staticmethod
    def _metadata(
        *,
        item_type: Literal["note", "url", "file", "audio"],
        source_url: str | None,
        file_name: str | None,
        file_size: int | None,
        file_type: str | None,
    ) -> dict[str, object]:
        metadata: dict[str, object] = {"sourceType": item_type}
        if source_url:
            metadata["sourceUrl"] = source_url
        if file_name:
            metadata["fileName"] = file_name
        if file_size is not None:
            metadata["fileSize"] = file_size
        if file_type:
            metadata["fileType"] = file_type
        return metadata

    @staticmethod
    def _parser_version(item_type: str) -> str:
        return {
            "note": "manual-note-v1",
            "url": "ingest-url-v1",
            "file": "ingest-file-v1",
            "audio": "ingest-audio-v1",
        }[item_type]

    @staticmethod
    def _chunk_locator(
        *,
        item_type: str,
        source_url: str | None,
        file_name: str | None,
        file_type: str | None,
    ) -> dict[str, object]:
        locator: dict[str, object] = {"kind": item_type}
        if source_url:
            locator["sourceUrl"] = source_url
        if file_name:
            locator["fileName"] = file_name
        if file_type:
            locator["fileType"] = file_type
        return locator

    @staticmethod
    def _title_from_content(content: str) -> str:
        first_line = next(
            (line.strip() for line in content.splitlines() if line.strip()),
            "Untitled note",
        )
        return first_line[:80].rstrip()

    def list_items(
        self,
        *,
        query: str | None,
        item_type: str | None,
        limit: int,
        before_updated_at: datetime | None = None,
        before_id: UUID | None = None,
    ) -> list[ItemRecord]:
        with self._database.workspace_transaction(self._identity) as connection:
            return ItemRepository(connection).list_active(
                query=query,
                item_type=item_type,
                limit=limit,
                before_updated_at=before_updated_at,
                before_id=before_id,
            )

    def get_item(self, item_id: UUID) -> ItemRecord:
        with self._database.workspace_transaction(self._identity) as connection:
            item = ItemRepository(connection).get_active(item_id)
            if item is None:
                raise ItemNotFoundError
            return item

    def update_item(
        self,
        item_id: UUID,
        *,
        expected_current_version_id: UUID,
        changes: dict[str, Any],
    ) -> ItemUpdateResult:
        """Publish one immutable replacement using an optimistic version token."""
        if not changes:
            raise ItemValidationError("At least one editable field is required")

        with self._database.workspace_transaction(self._identity, write=True) as connection:
            repository = ItemRepository(connection)
            current = repository.get_active_for_update(item_id)
            if current is None:
                raise ItemNotFoundError
            if current.current_version_id != expected_current_version_id:
                raise ItemConflictError

            title, content, source_url, metadata, replacement_chunks = self._resolve_update(
                current,
                changes,
            )
            source_replaced = self._source_was_replaced(
                current=current,
                content=content,
                source_url=source_url,
                changes=changes,
            )
            if source_replaced:
                metadata.pop("extractedFacts", None)
                metadata.pop("relatedItemIds", None)
            changed = (
                title != current.title
                or content != current.content
                or source_url != current.source_url
                or metadata != current.metadata
            )
            if not changed:
                return ItemUpdateResult(item=current, changed=False, source_replaced=False)

            version_id = uuid4()
            repository.insert_version(
                version_id=version_id,
                workspace_id=self._identity.workspace_id,
                document_id=item_id,
                version_number=current.version_number + 1,
                content_hash=sha256(content.encode("utf-8")).hexdigest(),
                parser_version=current.parser_version,
                snapshot_title=title,
                snapshot_source_url=source_url,
                snapshot_metadata=metadata,
            )
            if replacement_chunks is None:
                if repository.copy_chunks(
                    source_version_id=current.current_version_id,
                    target_version_id=version_id,
                ) < 1:
                    raise RuntimeError("Current item has no chunks")
            else:
                for ordinal, chunk in enumerate(replacement_chunks):
                    repository.insert_chunk(
                        chunk_id=uuid4(),
                        workspace_id=self._identity.workspace_id,
                        version_id=version_id,
                        ordinal=ordinal,
                        content=chunk.content,
                        locator=chunk.locator,
                    )
            repository.mark_version_ready(version_id)
            if not repository.replace_current(
                document_id=item_id,
                expected_version_id=expected_current_version_id,
                version_id=version_id,
                title=title,
                source_url=source_url,
                metadata=metadata,
            ):
                raise ItemConflictError
            if source_replaced:
                ImportBatchRepository(connection).supersede_for_document(item_id)
            updated = repository.get_active(item_id)
            if updated is None:
                raise RuntimeError("Updated item could not be read back")
            return ItemUpdateResult(
                item=updated,
                changed=True,
                source_replaced=source_replaced,
            )

    def _resolve_update(
        self,
        current: ItemRecord,
        changes: dict[str, Any],
    ) -> tuple[
        str,
        str,
        str | None,
        dict[str, Any],
        tuple[ChunkSpec | _ReplacementChunk, ...] | None,
    ]:
        item_type = current.item_type
        allowed_by_type = {
            "note": {"title", "content"},
            "url": {"title", "content", "source_url"},
            "file": {"title", "content", "file_name", "file_size", "file_type"},
            "audio": {"title", "content", "file_name", "file_size", "file_type"},
        }
        unsupported = set(changes) - allowed_by_type[item_type]
        if unsupported:
            raise ItemValidationError("Fields are not valid for this item type")

        title = changes.get("title", current.title)
        source_url = changes.get("source_url", current.source_url)
        content = changes.get("content", current.content)
        metadata = dict(current.metadata or {})
        replacement_chunks = None

        if item_type == "url":
            if not source_url:
                raise ItemValidationError("sourceUrl is required for url items")
            if "source_url" in changes and "content" not in changes:
                content = source_url
        elif item_type in {"file", "audio"}:
            file_name = changes.get("file_name", metadata.get("fileName"))
            file_size = changes.get("file_size", metadata.get("fileSize"))
            file_type = changes.get("file_type", metadata.get("fileType"))
            if item_type == "file" and not file_name:
                raise ItemValidationError("fileName is required for file items")
            if file_name is None:
                metadata.pop("fileName", None)
            else:
                metadata["fileName"] = file_name
            if file_size is None:
                metadata.pop("fileSize", None)
            else:
                metadata["fileSize"] = file_size
            if file_type is None:
                metadata.pop("fileType", None)
            else:
                metadata["fileType"] = file_type

            import_format = metadata.get("importFormat")
            current_metadata = current.metadata or {}
            import_fields_changed = (
                ("content" in changes and content != current.content)
                or (
                    "file_name" in changes
                    and file_name != current_metadata.get("fileName")
                )
                or (
                    "file_size" in changes
                    and file_size != current_metadata.get("fileSize")
                )
                or (
                    "file_type" in changes
                    and file_type != current_metadata.get("fileType")
                )
            )
            if item_type == "file" and import_format in {"csv", "txt", "md"} and import_fields_changed:
                encoded_size = len(content.encode("utf-8"))
                supplied_size = changes.get("file_size", encoded_size)
                try:
                    prepared = ImportService.prepare_content(
                        format=import_format,
                        file_name=file_name,
                        file_type=file_type,
                        file_size=supplied_size,
                        content=content,
                    )
                except ImportValidationError as error:
                    raise ItemValidationError(error.detail) from None
                content = prepared.content
                replacement_chunks = prepared.chunks
                metadata.update(
                    {
                        "fileName": prepared.file_name,
                        "fileSize": prepared.file_size,
                        "importFormat": prepared.format,
                    }
                )
                if prepared.file_type:
                    metadata["fileType"] = prepared.file_type
                else:
                    metadata.pop("fileType", None)
                if prepared.row_count is None:
                    metadata.pop("rowCount", None)
                else:
                    metadata["rowCount"] = prepared.row_count
            elif (
                item_type == "file"
                and "content" in changes
                and content != current.content
            ):
                content_size = len(content.encode("utf-8"))
                if "file_size" in changes and changes["file_size"] != content_size:
                    raise ItemValidationError(
                        "fileSize must equal the UTF-8 byte length of content"
                    )
                metadata["fileSize"] = content_size

        if not isinstance(title, str) or not title.strip():
            raise ItemValidationError("title must contain text")
        title = title.strip()
        if not isinstance(content, str) or not content.strip():
            raise ItemValidationError("content must contain text")
        if item_type in {"note", "url"}:
            content = content.strip()
        metadata["sourceType"] = item_type
        if source_url:
            metadata["sourceUrl"] = source_url
        else:
            metadata.pop("sourceUrl", None)
        locator_changed = (
            source_url != current.source_url
            or metadata.get("fileName") != (current.metadata or {}).get("fileName")
            or metadata.get("fileType") != (current.metadata or {}).get("fileType")
        )
        if replacement_chunks is None and (content != current.content or locator_changed):
            replacement_chunks = (
                _ReplacementChunk(
                    content=content,
                    locator=self._chunk_locator(
                        item_type=item_type,
                        source_url=source_url,
                        file_name=metadata.get("fileName"),
                        file_type=metadata.get("fileType"),
                    ),
                ),
            )
        return title, content, source_url, metadata, replacement_chunks

    @staticmethod
    def _source_was_replaced(
        *,
        current: ItemRecord,
        content: str,
        source_url: str | None,
        changes: dict[str, Any],
    ) -> bool:
        if content != current.content or source_url != current.source_url:
            return True
        is_text_import = (current.metadata or {}).get("importFormat") in {"csv", "txt", "md"}
        current_metadata = current.metadata or {}
        file_metadata_changed = any(
            field in changes and changes[field] != current_metadata.get(metadata_key)
            for field, metadata_key in (
                ("file_name", "fileName"),
                ("file_size", "fileSize"),
                ("file_type", "fileType"),
            )
        )
        return (
            current.item_type in {"file", "audio"}
            and not is_text_import
            and file_metadata_changed
        )

    def delete_item(self, item_id: UUID) -> None:
        with self._database.workspace_transaction(self._identity, write=True) as connection:
            if not ItemRepository(connection).soft_delete(item_id):
                raise ItemNotFoundError
            ImportBatchRepository(connection).supersede_for_document(item_id)


@dataclass(frozen=True)
class _ReplacementChunk:
    content: str
    locator: dict[str, object]
