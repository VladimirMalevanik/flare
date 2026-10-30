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


@dataclass(frozen=True)
class ItemVersionRecord:
    item: ItemRecord
    saved_at: datetime
    is_current: bool


class ItemRepository:
    """Keep SQL and schema-specific mappings outside HTTP and service layers."""

    _CREATOR_COLUMNS = """
               d.workspace_id AS _creator_workspace_id,
               d.import_package_id AS _creator_package_id,
               CASE WHEN nullif(v.snapshot_metadata->>'createdBy', '') IS NULL
                          OR nullif(v.snapshot_metadata->>'createdByName', '') IS NULL THEN (
                   SELECT jsonb_build_object('parser', first.parser_version, 'metadata', first.snapshot_metadata)
                     FROM public.document_versions first
                    WHERE first.workspace_id=d.workspace_id AND first.document_id=d.id AND first.version_number=1
               ) END AS _creator_origin,
    """

    _SELECT_ITEM = """
        SELECT """ + _CREATOR_COLUMNS + """ d.id,
               d.source_type AS item_type,
               v.snapshot_title AS title,
               v.snapshot_source_url AS source_url,
               v.snapshot_metadata AS metadata,
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
        snapshot_title: str,
        snapshot_source_url: str | None,
        snapshot_metadata: dict[str, Any],
        version_number: int = 1,
    ) -> None:
        self._connection.execute(
            """INSERT INTO public.document_versions
                   (id, workspace_id, document_id, version_number, content_hash,
                    parser_version, snapshot_title, snapshot_source_url,
                    snapshot_metadata, state)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'processing')""",
            (
                version_id,
                workspace_id,
                document_id,
                version_number,
                content_hash,
                parser_version,
                snapshot_title,
                snapshot_source_url,
                Jsonb(snapshot_metadata),
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

    def get_version(self, item_id: UUID, version_id: UUID) -> ItemRecord | None:
        """Read one exact published version while preserving soft-delete hiding."""
        snapshot = self.get_version_snapshot(item_id, version_id)
        return snapshot.item if snapshot else None

    def get_version_snapshot(self, item_id: UUID, version_id: UUID) -> ItemVersionRecord | None:
        row = self._connection.execute(
            """
            SELECT """ + self._CREATOR_COLUMNS + """ d.id,
                   d.source_type AS item_type,
                   v.snapshot_title AS title,
                   v.snapshot_source_url AS source_url,
                   v.snapshot_metadata AS metadata,
                   v.state,
                   v.parser_version,
                   v.id AS current_version_id,
                   v.version_number,
                   v.created_at AS version_created_at,
                   d.current_version_id = v.id AS is_current,
                   d.created_at,
                   CASE
                       WHEN d.current_version_id = v.id THEN d.updated_at
                       ELSE v.created_at
                   END AS updated_at,
                   COALESCE((
                       SELECT string_agg(c.content, '' ORDER BY c.ordinal)
                       FROM public.chunks c
                       WHERE c.workspace_id = d.workspace_id
                         AND c.document_version_id = v.id
                   ), '') AS content
              FROM public.documents d
              JOIN public.document_versions v
                ON (v.workspace_id, v.document_id) = (d.workspace_id, d.id)
             WHERE d.id = %s
               AND v.id = %s
               AND v.state = 'ready'
               AND d.deleted_at IS NULL
            """,
            (item_id, version_id),
        ).fetchone()
        if row is None:
            return None
        saved_at, is_current = row.pop('version_created_at'), row.pop('is_current')
        return ItemVersionRecord(self._to_record(row), saved_at, is_current)

    def list_active(
        self,
        *,
        query: str | None,
        item_type: str | None,
        limit: int,
        before_updated_at: datetime | None = None,
        before_id: UUID | None = None,
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
                """(v.snapshot_title ILIKE %s ESCAPE '\\'
                    OR EXISTS (
                        SELECT 1 FROM public.chunks search_chunk
                        WHERE search_chunk.workspace_id = d.workspace_id
                          AND search_chunk.document_version_id = v.id
                          AND search_chunk.content ILIKE %s ESCAPE '\\'
                    ))"""
            )
            parameters.extend((pattern, pattern))
        if before_updated_at is not None and before_id is not None:
            clauses.append("(d.updated_at, d.id) < (%s, %s)")
            parameters.extend((before_updated_at, before_id))
        parameters.append(limit)
        rows = self._connection.execute(
            self._SELECT_ITEM
            + " WHERE "
            + " AND ".join(clauses)
            + " ORDER BY d.updated_at DESC, d.id DESC LIMIT %s",
            parameters,
        ).fetchall()
        return self._to_records(rows)

    def soft_delete(self, item_id: UUID) -> bool:
        row = self._connection.execute(
            """UPDATE public.documents SET deleted_at = now()
               WHERE id = %s AND deleted_at IS NULL RETURNING id""",
            (item_id,),
        ).fetchone()
        return row is not None

    def _to_record(self, row: dict[str, Any]) -> ItemRecord:
        return self._to_records([row])[0]

    def _to_records(self, rows: list[dict[str, Any]]) -> list[ItemRecord]:
        """Enrich missing display authors, without changing immutable snapshots.

        Only server-owned package pointers or first source-version provenance can
        select a creator. Caller metadata/current viewer never supplies one.
        Lookups are batched, scoped to the selected workspace and uncached.
        """
        records, packages, sources = [], {}, {}
        for raw in rows:
            row = dict(raw)
            workspace = row.pop('_creator_workspace_id', None)
            package = row.pop('_creator_package_id', None)
            origin = row.pop('_creator_origin', None) or {}
            metadata = dict(row['metadata'])
            original = origin.get('metadata', {})
            self._fill_creator(metadata, original)
            row['metadata'] = metadata
            records.append(row)
            if metadata.get('createdBy') and metadata.get('createdByName'):
                continue
            if package is not None:
                packages.setdefault(workspace, []).append((package, metadata))
            elif origin.get('parser') == 'source-text-v1':
                try:
                    connection = UUID(original.get('sourceConnectionId', ''))
                except (ValueError, TypeError, AttributeError):
                    continue
                sources.setdefault(connection, []).append(metadata)
        for workspace, items in packages.items():
            result = self._connection.execute(
                """SELECT p.id, p.requested_by_user_id AS "createdBy", a.name AS "createdByName"
                     FROM public.import_packages p JOIN public.auth_users a ON a.id=p.requested_by_user_id
                    WHERE p.workspace_id=%s AND p.id=ANY(%s)
                      AND p.status IN ('completed','completed_with_skips')""",
                (workspace, list({package for package, _ in items})),
            ).fetchall()
            creators = {row['id']: row for row in result}
            for package, metadata in items:
                self._fill_creator(metadata, creators.get(package, {}))
        ids = list(sources)
        for offset in range(0, len(ids), 100):
            result = self._connection.execute(
                "SELECT public.source_api('creators',NULL,%s) AS creators",
                (Jsonb({'connectionIds': [str(id) for id in ids[offset:offset + 100]]}),),
            ).fetchone()['creators']
            if isinstance(result, list):
                for creator in result:
                    for metadata in sources.get(UUID(creator['id']), []):
                        self._fill_creator(metadata, creator)
        return [ItemRecord(**row) for row in records]

    @staticmethod
    def _fill_creator(metadata: dict[str, Any], creator: dict[str, Any]) -> None:
        id = creator.get('createdBy')
        if not isinstance(id, str) or not id:
            return
        if not isinstance(metadata.get('createdBy'), str) or not metadata.get('createdBy'):
            metadata['createdBy'] = id
            metadata.pop('createdByName', None)
        if metadata.get('createdBy') == id and not metadata.get('createdByName'):
            name = creator.get('createdByName')
            if isinstance(name, str) and name:
                metadata['createdByName'] = name
