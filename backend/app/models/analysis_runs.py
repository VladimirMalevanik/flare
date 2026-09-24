"""Public run persistence on the existing workspace transaction."""
from uuid import UUID
from app.services.context_selection import SELECTION_REVISION, select_context


class NoEligibleContext(ValueError):
    CODES = {
        'no_context',
        'no_ready_context',
        'context_too_large',
        'request_budget_exceeded',
        'unsupported_context',
    }

    def __init__(self, code: str):
        if code not in self.CODES:
            raise ValueError('Invalid no-context reason')
        self.code = code
        super().__init__(code)


class DailyLimitReached(ValueError):
    pass


def no_eligible_reason(stats: dict) -> str:
    """Classify only states proven by the workspace-scoped selection query."""
    if stats['total_context'] == 0:
        return 'no_context'
    if stats['supported_context'] == 0:
        return 'unsupported_context'
    if stats['ready_context'] == 0:
        return 'no_ready_context'
    if stats['fitting_chunks'] == 0:
        return 'context_too_large'
    return 'request_budget_exceeded'


class AnalysisRuns:
    @staticmethod
    def read(connection, run_id):
        return connection.execute('SELECT public.read_analysis_run(%s) AS value', (run_id,)).fetchone()['value']

    @staticmethod
    def start(connection, identity, key, ai, pipeline, generation, attempts):
        # Serialize the same logical attempt before selection, including replay
        # after all original sources are deleted or configuration changes.
        connection.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
                           (str(identity.workspace_id) + identity.user_id + str(key),))
        prior = connection.execute('SELECT id FROM public.analysis_runs WHERE workspace_id=%s AND requested_by_user_id=%s AND idempotency_key=%s',
                                   (identity.workspace_id, identity.user_id, key)).fetchone()
        if prior:
            return AnalysisRuns.read(connection, prior['id'])
        occupied = connection.execute("""
            SELECT q.local_date
            FROM public.analysis_daily_quotas q
            WHERE q.workspace_id=%s AND (
                q.local_date=(clock_timestamp() AT TIME ZONE
                    coalesce((SELECT s.timezone FROM public.analysis_schedules s
                              WHERE s.workspace_id=%s),'UTC'))::date
                OR q.scheduled_for>clock_timestamp()-interval '20 hours'
            )
            ORDER BY q.scheduled_for DESC
            LIMIT 1
        """, (identity.workspace_id, identity.workspace_id)).fetchone()
        if occupied:
            raise DailyLimitReached('daily_limit')
        max_sources = min(ai.max_sources, 100)
        candidate_limit = min(max_sources * 4, 400)
        candidates = connection.execute("""
            WITH recent AS MATERIALIZED (
                SELECT d.id,d.current_version_id,d.updated_at FROM public.documents d
                JOIN public.document_versions v ON(v.workspace_id,v.id)=(d.workspace_id,d.current_version_id)
                WHERE d.source_type IN ('note','file','url','audio')
                  AND d.deleted_at IS NULL AND v.state='ready'
                  AND EXISTS(SELECT 1 FROM public.chunks c WHERE c.document_version_id=v.id AND c.workspace_id=d.workspace_id)
                ORDER BY d.updated_at DESC,d.id DESC LIMIT 200
            )
            SELECT c.id,c.content FROM recent d CROSS JOIN LATERAL (
                SELECT c.id,c.content,c.ordinal FROM public.chunks c
                WHERE c.document_version_id=d.current_version_id AND octet_length(c.content)<=%s
                ORDER BY c.ordinal,c.id LIMIT %s
            ) c ORDER BY d.updated_at DESC,d.id DESC,c.ordinal,c.id LIMIT %s
        """, (ai.max_input_bytes, max_sources, candidate_limit)).fetchall()
        selected = select_context(candidates, ai)
        if not selected:
            stats = connection.execute("""
                SELECT
                    count(DISTINCT d.id) AS total_context,
                    count(DISTINCT d.id) FILTER (
                        WHERE d.source_type IN ('note','file','url','audio')
                    ) AS supported_context,
                    count(DISTINCT d.id) FILTER (
                        WHERE d.source_type IN ('note','file','url','audio')
                          AND v.state='ready' AND c.id IS NOT NULL
                    ) AS ready_context,
                    count(DISTINCT c.id) FILTER (
                        WHERE d.source_type IN ('note','file','url','audio')
                          AND v.state='ready' AND octet_length(c.content)<=%s
                    ) AS fitting_chunks
                FROM public.documents d
                LEFT JOIN public.document_versions v
                  ON (v.workspace_id,v.id)=(d.workspace_id,d.current_version_id)
                LEFT JOIN public.chunks c
                  ON (c.workspace_id,c.document_version_id)=(d.workspace_id,v.id)
                WHERE d.deleted_at IS NULL
            """, (ai.max_input_bytes,)).fetchone()
            raise NoEligibleContext(no_eligible_reason(stats))
        run_id = connection.execute('SELECT public.start_daily_analysis_run(%s,%s,%s,%s,%s,%s,%s,%s) AS id',
            (key, [UUID(e.source_id) for e in selected], SELECTION_REVISION, pipeline, generation,
             attempts, max_sources, ai.max_input_bytes)).fetchone()['id']
        return AnalysisRuns.read(connection, run_id)
