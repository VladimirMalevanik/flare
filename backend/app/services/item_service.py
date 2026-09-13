"""Use cases for workspace-scoped knowledge items."""

from hashlib import sha256
from typing import Literal
from uuid import UUID, uuid4

from app.config import load_ai_settings
from app.models.database import Database, WorkspaceIdentity
from app.models.tables import ItemRecord, ItemRepository
from app.workers.config import load_worker_settings, pipeline_revision


class ItemNotFoundError(Exception):
    """An active item is unavailable inside the caller's workspace."""


class ItemService:
    def __init__(
        self,
        database: Database,
        identity: WorkspaceIdentity,
        *,
        enqueue_analysis: bool = True,
    ):
        self._database = database
        self._identity = identity
        self._enqueue_analysis = enqueue_analysis

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
            if self._enqueue_analysis:
                self._enqueue_item_analysis(connection, (chunk_id,))
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

    def _enqueue_item_analysis(self, connection, chunks: tuple[UUID, ...]) -> None:
        """Enqueue valid work without making capture depend on AI configuration."""
        try:
            ai = load_ai_settings()
            worker = load_worker_settings()
            worker.validate(ai)
        except ValueError:
            # Capture remains durable when the separately operated AI worker is
            # absent or misconfigured. No provider is constructed in this path.
            return
        connection.execute(
            "SELECT public.enqueue_analysis_job(%s, %s, %s)",
            (list(chunks), pipeline_revision(ai), worker.max_attempts),
        )

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
    ) -> list[ItemRecord]:
        with self._database.workspace_transaction(self._identity) as connection:
            return ItemRepository(connection).list_active(
                query=query,
                item_type=item_type,
                limit=limit,
            )

    def get_item(self, item_id: UUID) -> ItemRecord:
        with self._database.workspace_transaction(self._identity) as connection:
            item = ItemRepository(connection).get_active(item_id)
            if item is None:
                raise ItemNotFoundError
            return item

    def delete_item(self, item_id: UUID) -> None:
        with self._database.workspace_transaction(self._identity, write=True) as connection:
            if not ItemRepository(connection).soft_delete(item_id):
                raise ItemNotFoundError
