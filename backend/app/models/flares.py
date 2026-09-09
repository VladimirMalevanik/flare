"""Read-only Flare projection, with deletion filtering in the same SQL snapshot."""
from uuid import UUID

SELECT_FLARES = '''
SELECT i.id,i.flare_type AS type,i.title,i.body AS statement,i.action,i.reason,i.created_at,
       evidence.entries AS evidence
FROM public.insights i
JOIN LATERAL (
    SELECT jsonb_agg(jsonb_build_object('itemId',d.id,'sourceTitle',d.title,
        'sourceType',d.source_type,'excerpt',s.quote,'sourceUrl',d.source_url)
        ORDER BY s.ordinal,s.chunk_id) AS entries,
        count(*) AS total,
        count(*) FILTER(WHERE d.deleted_at IS NULL AND v.state='ready'
            AND s.quote IS NOT NULL AND s.ordinal IS NOT NULL) AS valid
    FROM public.insight_sources s
    JOIN public.chunks c ON(c.workspace_id,c.id)=(s.workspace_id,s.chunk_id)
    JOIN public.document_versions v ON(v.workspace_id,v.id)=(c.workspace_id,c.document_version_id)
    JOIN public.documents d ON(d.workspace_id,d.id)=(v.workspace_id,v.document_id)
    WHERE(s.workspace_id,s.insight_id)=(i.workspace_id,i.id)
) evidence ON evidence.total BETWEEN 1 AND 4 AND evidence.total=evidence.valid
WHERE i.flare_type IS NOT NULL
'''


class FlareRepository:
    def __init__(self, connection): self.connection=connection

    def list(self, limit: int):
        return self.connection.execute(SELECT_FLARES+' ORDER BY i.created_at DESC,i.id DESC LIMIT %s',(limit,)).fetchall()

    def get(self, flare_id: UUID):
        return self.connection.execute(SELECT_FLARES+' AND i.id=%s',(flare_id,)).fetchone()
