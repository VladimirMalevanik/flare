"""Typed persistence queries over the migration-owned PostgreSQL schema."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from psycopg import Connection
from psycopg.types.json import Jsonb


@dataclass(frozen=True)
class ItemRecord:
    id: UUID
    item_type: str
    title: str
    content: str
    source_url: str | None
    metadata: dict[str, Any]
    state: str
    parser_version: str
    current_version_id: UUID
    version_number: int
    created_at: datetime
    updated_at: datetime


class ItemRepository:
    """Keep SQL and schema-specific mappings outside HTTP and service layers."""

    _SELECT_ITEM = """
        SELECT d.id,
               d.source_type AS item_type,
               d.title,
               d.source_url,
               d.metadata,
               v.state,
               v.parser_version,
               v.id AS current_version_id,
               v.version_number,
               d.created_at,
               d.updated_at,
               COALESCE((
                   SELECT string_agg(c.content, '' ORDER BY c.ordinal)
                   FROM public.chunks c
                   WHERE c.workspace_id = d.workspace_id
                     AND c.document_version_id = v.id
               ), '') AS content
        FROM public.documents d
        JOIN public.document_versions v
          ON (v.workspace_id, v.document_id, v.id) =
             (d.workspace_id, d.id, d.current_version_id)
    """

    def __init__(self, connection: Connection):
        self._connection = connection

    def insert_document(
        self,
        *,
        item_id: UUID,
        workspace_id: UUID,
        title: str,
        item_type: str,
        source_url: str | None,
        metadata: dict[str, Any],
    ) -> datetime:
        row = self._connection.execute(
            """INSERT INTO public.documents
                   (id, workspace_id, title, source_type, source_url, metadata)
               VALUES (%s, %s, %s, %s, %s, %s)
               RETURNING created_at""",
            (item_id, workspace_id, title, item_type, source_url, Jsonb(metadata)),
        ).fetchone()
        return row["created_at"]

    def insert_version(
        self,
        *,
        version_id: UUID,
        workspace_id: UUID,
        document_id: UUID,
        content_hash: str,
        parser_version: str,
        version_number: int = 1,
    ) -> None:
        self._connection.execute(
            """INSERT INTO public.document_versions
                   (id, workspace_id, document_id, version_number, content_hash,
                    parser_version, state)
               VALUES (%s, %s, %s, %s, %s, %s, 'processing')""",
            (
                version_id,
                workspace_id,
                document_id,
                version_number,
                content_hash,
                parser_version,
            ),
        )

    def insert_chunk(
        self,
        *,
        chunk_id: UUID,
        workspace_id: UUID,
        version_id: UUID,
        content: str,
        locator: dict[str, object],
        ordinal: int = 0,
    ) -> None:
        self._connection.execute(
            """INSERT INTO public.chunks
                   (id, workspace_id, document_version_id, ordinal, content,
                    locator)
               VALUES (%s, %s, %s, %s, %s, %s::jsonb)""",
            (chunk_id, workspace_id, version_id, ordinal, content, Jsonb(locator)),
        )

    def publish_version(self, *, document_id: UUID, version_id: UUID) -> None:
        self._connection.execute(
            "UPDATE public.document_versions SET state = 'ready' WHERE id = %s",
            (version_id,),
        )
        self._connection.execute(
            "UPDATE public.documents SET current_version_id = %s WHERE id = %s",
            (version_id, document_id),
        )

    def mark_version_ready(self, version_id: UUID) -> None:
        self._connection.execute(
            "UPDATE public.document_versions SET state = 'ready' WHERE id = %s",
            (version_id,),
        )

    def get_active_for_update(self, item_id: UUID) -> ItemRecord | None:
        row = self._connection.execute(
            self._SELECT_ITEM
            + " WHERE d.id = %s AND d.deleted_at IS NULL FOR UPDATE OF d",
            (item_id,),
        ).fetchone()
        return self._to_record(row) if row else None

    def copy_chunks(self, *, source_version_id: UUID, target_version_id: UUID) -> int:
        rows = self._connection.execute(
            """INSERT INTO public.chunks
                   (id, workspace_id, document_version_id, ordinal, content, locator)
               SELECT gen_random_uuid(), workspace_id, %s, ordinal, content, locator
                 FROM public.chunks
                WHERE document_version_id = %s
                ORDER BY ordinal
               RETURNING id""",
            (target_version_id, source_version_id),
        ).fetchall()
        return len(rows)

    def replace_current(
        self,
        *,
        document_id: UUID,
        expected_version_id: UUID,
        version_id: UUID,
        title: str,
        source_url: str | None,
        metadata: dict[str, Any],
    ) -> bool:
        row = self._connection.execute(
            """UPDATE public.documents
                  SET title = %s, source_url = %s, metadata = %s,
                      current_version_id = %s
                WHERE id = %s AND deleted_at IS NULL AND current_version_id = %s
                RETURNING id""",
            (
                title,
                source_url,
                Jsonb(metadata),
                version_id,
                document_id,
                expected_version_id,
            ),
        ).fetchone()
        return row is not None

    def get_active(self, item_id: UUID) -> ItemRecord | None:
        row = self._connection.execute(
            self._SELECT_ITEM
            + " WHERE d.id = %s AND d.deleted_at IS NULL",
            (item_id,),
        ).fetchone()
        return self._to_record(row) if row else None

    def list_active(
        self,
        *,
        query: str | None,
        item_type: str | None,
        limit: int,
    ) -> list[ItemRecord]:
        clauses = ["d.deleted_at IS NULL"]
        parameters: list[object] = []
        if item_type:
            clauses.append("d.source_type = %s")
            parameters.append(item_type)
        if query:
            escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            pattern = f"%{escaped}%"
            clauses.append(
                """(d.title ILIKE %s ESCAPE '\\'
                    OR EXISTS (
                        SELECT 1 FROM public.chunks search_chunk
                        WHERE search_chunk.workspace_id = d.workspace_id
                          AND search_chunk.document_version_id = v.id
                          AND search_chunk.content ILIKE %s ESCAPE '\\'
                    ))"""
            )
            parameters.extend((pattern, pattern))
        parameters.append(limit)
        rows = self._connection.execute(
            self._SELECT_ITEM
            + " WHERE "
            + " AND ".join(clauses)
            + " ORDER BY d.created_at DESC, d.id DESC LIMIT %s",
            parameters,
        ).fetchall()
        return [self._to_record(row) for row in rows]

    def soft_delete(self, item_id: UUID) -> bool:
        row = self._connection.execute(
            """UPDATE public.documents SET deleted_at = now()
               WHERE id = %s AND deleted_at IS NULL RETURNING id""",
            (item_id,),
        ).fetchone()
        return row is not None

    @staticmethod
    def _to_record(row: dict[str, Any]) -> ItemRecord:
        return ItemRecord(**row)
