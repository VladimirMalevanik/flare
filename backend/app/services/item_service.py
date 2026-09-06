"""Use cases for workspace-scoped knowledge items."""

from hashlib import sha256
from uuid import UUID, uuid4

from app.models.database import Database, WorkspaceIdentity
from app.models.tables import ItemRecord, ItemRepository


class ItemNotFoundError(Exception):
    """An active item is unavailable inside the caller's workspace."""


class ItemService:
    def __init__(self, database: Database, identity: WorkspaceIdentity):
        self._database = database
        self._identity = identity

    def create_note(self, *, title: str | None, content: str) -> ItemRecord:
        item_id, version_id, chunk_id = uuid4(), uuid4(), uuid4()
        resolved_title = title or self._title_from_content(content)
        content_hash = sha256(content.encode("utf-8")).hexdigest()

        with self._database.workspace_transaction(self._identity, write=True) as connection:
            repository = ItemRepository(connection)
            repository.insert_document(
                item_id=item_id,
                workspace_id=self._identity.workspace_id,
                title=resolved_title,
            )
            repository.insert_version(
                version_id=version_id,
                workspace_id=self._identity.workspace_id,
                document_id=item_id,
                content_hash=content_hash,
            )
            repository.insert_chunk(
                chunk_id=chunk_id,
                workspace_id=self._identity.workspace_id,
                version_id=version_id,
                content=content,
            )
            repository.publish_version(document_id=item_id, version_id=version_id)
            item = repository.get_active(item_id)
            if item is None:  # The transaction either returns a complete item or rolls back.
                raise RuntimeError("Created note could not be read back")
            return item

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
