"""Explicit owner maintenance of old manual notes. Never rewrites published evidence."""
from hashlib import sha256
import json
import time
from uuid import UUID, uuid4

from app.models.database import Database, WorkspaceIdentity, WritePermissionRequiredError
from app.models.tables import ItemRepository
from app.services.import_service import IMPORT_CHUNK_TARGET_BYTES, _split_exact
from app.ai_engine.analysis import Evidence
from app.ai_engine.text_analysis_prompts import build_bounded_request, request_size_bytes
from app.config import AISettings

MAX_NOTE_BYTES = 800_000  # Existing HTTP contract: at most200000 Unicode characters.


class NoteRepairError(Exception):
    """Safe maintenance failure; no source text or database details."""


class NoteRepair:
    def __init__(self, database: Database, identity: WorkspaceIdentity, ai: AISettings | None = None):
        self.database, self.identity = database, identity
        self.ai = ai or AISettings()
        # Real selection counts the full request, with content JSON-encoded
        # inside the user message and again inside the request. UUIDs have the
        # same serialized width. Match that exact existing bound without AI.
        sample = Evidence(source_id=str(UUID(int=0)), content='x')
        encoded = json.dumps(json.dumps('x', ensure_ascii=False), ensure_ascii=False)
        self.overhead = request_size_bytes(build_bounded_request((sample,), self.ai)) - len(encoded.encode('utf-8'))
        build_bounded_request((Evidence(source_id=sample.source_id, content='x'*IMPORT_CHUNK_TARGET_BYTES),), self.ai)

    def _ineligible(self, bounds):
        return (bounds['maximum'] > self.ai.max_input_bytes
                or bounds['encoded'] + self.overhead > self.ai.max_input_bytes)

    def _owner(self, connection):
        row = connection.execute('SELECT role FROM public.workspace_members WHERE workspace_id=%s AND user_id=%s',
                                 (self.identity.workspace_id, self.identity.user_id)).fetchone()
        if not row or row['role'] != 'owner':
            raise WritePermissionRequiredError

    def plan(self, *, limit=25):
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError('Repair limit must be between1 and100')
        with self.database.workspace_transaction(self.identity, snapshot=True, timeout=3,
                statement_timeout_ms=5000, lock_timeout_ms=500) as connection:
            self._owner(connection)
            rows = connection.execute('''SELECT d.id,v.id AS version_id,v.version_number,
                    bounds.maximum,bounds.bytes,bounds.count
                FROM public.documents d JOIN public.document_versions v
                  ON(v.workspace_id,v.document_id,v.id)=(d.workspace_id,d.id,d.current_version_id)
                JOIN LATERAL (SELECT max(octet_length(content)) AS maximum,
                    sum(octet_length(content)) AS bytes,count(*) AS count,
                    max(octet_length(to_json(to_json(content)::text)::text)) AS encoded FROM public.chunks
                    WHERE workspace_id=d.workspace_id AND document_version_id=v.id) bounds ON true
                WHERE d.workspace_id=%s AND d.deleted_at IS NULL AND d.source_type='note'
                  AND v.state='ready' AND v.parser_version='manual-note-v1'
                  AND bounds.maximum>%s AND bounds.bytes<=%s
                  AND (bounds.maximum>%s OR bounds.encoded+%s>%s)
                ORDER BY d.id LIMIT %s''', (self.identity.workspace_id, IMPORT_CHUNK_TARGET_BYTES,
                                           MAX_NOTE_BYTES, self.ai.max_input_bytes,self.overhead,
                                           self.ai.max_input_bytes,limit)).fetchall()
            return [dict(itemId=str(row['id']),versionId=str(row['version_id']),
                         versionNumber=row['version_number'],contentBytes=row['bytes'],
                         maxChunkBytes=row['maximum'],chunkCount=row['count']) for row in rows]

    def apply(self, plan):
        if not isinstance(plan, list) or len(plan)>100:
            raise ValueError('Use a bounded repair plan')
        repaired = 0
        for entry in plan:
            repaired += self._one(UUID(entry['itemId']), UUID(entry['versionId']))
        return {'repaired':repaired, 'skipped':len(plan)-repaired}

    def _one(self, item_id, expected):
        started = time.monotonic()
        with self.database.workspace_transaction(self.identity, write=True, timeout=3,
                statement_timeout_ms=5000, lock_timeout_ms=500) as connection:
            self._owner(connection)
            row = connection.execute('''SELECT current_version_id,source_type FROM public.documents
                WHERE id=%s AND workspace_id=%s AND deleted_at IS NULL FOR UPDATE''',
                (item_id, self.identity.workspace_id)).fetchone()
            if not row or row['current_version_id'] != expected or row['source_type'] != 'note':
                return False
            bounds = connection.execute('''SELECT v.parser_version,v.state,
                    max(octet_length(c.content)) AS maximum,sum(octet_length(c.content)) AS bytes,
                    max(octet_length(to_json(to_json(c.content)::text)::text)) AS encoded
                FROM public.document_versions v JOIN public.chunks c
                  ON(c.workspace_id,c.document_version_id)=(v.workspace_id,v.id)
                WHERE v.id=%s AND v.document_id=%s GROUP BY v.id''', (expected,item_id)).fetchone()
            if not bounds or bounds['state']!='ready' or bounds['parser_version']!='manual-note-v1' or not (
                    IMPORT_CHUNK_TARGET_BYTES < bounds['maximum'] <= bounds['bytes'] <= MAX_NOTE_BYTES) or not self._ineligible(bounds):
                return False
            repository = ItemRepository(connection)
            current = repository.get_active(item_id)
            version_id = uuid4()
            repository.insert_version(version_id=version_id,workspace_id=self.identity.workspace_id,
                document_id=item_id,version_number=current.version_number+1,
                content_hash=sha256(current.content.encode('utf-8')).hexdigest(),parser_version=current.parser_version,
                snapshot_title=current.title,snapshot_source_url=current.source_url,snapshot_metadata=current.metadata)
            for ordinal, content in enumerate(_split_exact(current.content, IMPORT_CHUNK_TARGET_BYTES)):
                if time.monotonic()-started>30:
                    raise NoteRepairError('Repair deadline reached')
                chunk_id=uuid4()
                build_bounded_request((Evidence(source_id=str(chunk_id),content=content),),self.ai)
                repository.insert_chunk(chunk_id=chunk_id,workspace_id=self.identity.workspace_id,
                    version_id=version_id,ordinal=ordinal,content=content,locator={'kind':'note'})
            repository.mark_version_ready(version_id)
            if not repository.replace_current(document_id=item_id,expected_version_id=expected,version_id=version_id,
                    title=current.title,source_url=current.source_url,metadata=current.metadata):
                raise NoteRepairError('Source changed during repair')
            return True
