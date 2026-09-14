"""Persistence helpers for bounded, text-only import batches."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

from psycopg import Connection


ImportFormat = Literal["csv", "txt", "md"]


@dataclass(frozen=True)
class ImportBatchRecord:
    id: UUID
    workspace_id: UUID
    requested_by_user_id: str
    format: str
    file_name: str
    file_type: str | None
    file_size: int
    file_hash: str
    status: str
    document_id: UUID | None
    document_version_id: UUID | None
    row_count: int | None
    chunk_count: int
    analysis_jobs_queued: int
    created_at: datetime
    completed_at: datetime | None
    superseded_at: datetime | None


class ImportBatchRepository:
    """Keep import-batch SQL out of the HTTP layer.

    A ``processing`` row is intentionally created before the document.  The
    surrounding transaction makes that row invisible until its document and
    chunks have been committed. The active partial hash key makes concurrent
    retries return one canonical import while allowing reimport after a source
    is replaced or deleted.
    """

    _COLUMNS = """
        id, workspace_id, requested_by_user_id, format, file_name, file_type,
        file_size, file_hash, status, document_id, row_count, chunk_count,
        analysis_jobs_queued, created_at, completed_at, document_version_id,
        superseded_at
    """

    def __init__(self, connection: Connection):
        self._connection = connection

    def insert_pending(
        self,
        *,
        batch_id: UUID,
        workspace_id: UUID,
        requested_by_user_id: str,
        format: ImportFormat,
        file_name: str,
        file_type: str | None,
        file_size: int,
        file_hash: str,
    ) -> ImportBatchRecord | None:
        row = self._connection.execute(
            """INSERT INTO public.import_batches
                   (id, workspace_id, requested_by_user_id, format, file_name,
                    file_type, file_size, file_hash, status)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'processing')
               ON CONFLICT (workspace_id, format, file_hash)
                   WHERE superseded_at IS NULL
               DO NOTHING
               RETURNING """
            + self._COLUMNS,
            (
                batch_id,
                workspace_id,
                requested_by_user_id,
                format,
                file_name,
                file_type,
                file_size,
                file_hash,
            ),
        ).fetchone()
        return self._to_record(row) if row else None

    def get_by_hash(
        self,
        *,
        workspace_id: UUID,
        format: ImportFormat,
        file_hash: str,
    ) -> ImportBatchRecord | None:
        row = self._connection.execute(
            "SELECT " + self._COLUMNS + " FROM public.import_batches "
            "WHERE workspace_id = %s AND format = %s AND file_hash = %s "
            "AND superseded_at IS NULL",
            (workspace_id, format, file_hash),
        ).fetchone()
        return self._to_record(row) if row else None

    def get(self, batch_id: UUID) -> ImportBatchRecord | None:
        row = self._connection.execute(
            "SELECT " + self._COLUMNS + " FROM public.import_batches WHERE id = %s",
            (batch_id,),
        ).fetchone()
        return self._to_record(row) if row else None

    def mark_completed(
        self,
        *,
        batch_id: UUID,
        document_id: UUID,
        document_version_id: UUID,
        row_count: int | None,
        chunk_count: int,
        analysis_jobs_queued: int,
    ) -> ImportBatchRecord:
        row = self._connection.execute(
            """UPDATE public.import_batches
                   SET status = 'completed', document_id = %s,
                       document_version_id = %s, row_count = %s, chunk_count = %s,
                       analysis_jobs_queued = %s, completed_at = now()
                 WHERE id = %s AND status = 'processing'
               RETURNING """
            + self._COLUMNS,
            (
                document_id,
                document_version_id,
                row_count,
                chunk_count,
                analysis_jobs_queued,
                batch_id,
            ),
        ).fetchone()
        if row is None:
            raise RuntimeError("Import batch could not be completed")
        return self._to_record(row)

    def supersede_for_document(self, document_id: UUID) -> int:
        rows = self._connection.execute(
            """UPDATE public.import_batches
                  SET superseded_at = now()
                WHERE document_id = %s AND status = 'completed'
                  AND superseded_at IS NULL
                RETURNING id""",
            (document_id,),
        ).fetchall()
        return len(rows)

    @staticmethod
    def _to_record(row: dict) -> ImportBatchRecord:
        return ImportBatchRecord(**row)
