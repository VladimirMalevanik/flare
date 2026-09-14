"""Public run persistence on the existing workspace transaction."""
from uuid import UUID
from app.services.context_selection import SELECTION_REVISION, select_context


class NoEligibleContext(ValueError):
    pass


class DailyLimitReached(ValueError):
    pass


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
            SELECT c.id,c.idempotency_key,c.analysis_run_id
            FROM public.analysis_cycles c
            WHERE c.workspace_id=%s AND c.local_date=(clock_timestamp() AT TIME ZONE
                coalesce((SELECT s.timezone FROM public.analysis_schedules s
                          WHERE s.workspace_id=%s),'UTC'))::date
        """, (identity.workspace_id, identity.workspace_id)).fetchone()
        if occupied:
            if occupied['idempotency_key'] == key and occupied['analysis_run_id'] is not None:
                return AnalysisRuns.read(connection, occupied['analysis_run_id'])
            raise DailyLimitReached('daily_limit')
        candidates = connection.execute("""
            WITH recent AS MATERIALIZED (
                SELECT d.id,d.current_version_id,d.created_at FROM public.documents d
                JOIN public.document_versions v ON(v.workspace_id,v.id)=(d.workspace_id,d.current_version_id)
                WHERE d.source_type IN ('note','file','url','audio')
                  AND d.deleted_at IS NULL AND v.state='ready'
                  AND EXISTS(SELECT 1 FROM public.chunks c WHERE c.document_version_id=v.id AND c.workspace_id=d.workspace_id)
                ORDER BY d.created_at DESC,d.id DESC LIMIT 200
            )
            SELECT c.id,c.content FROM recent d CROSS JOIN LATERAL (
                SELECT c.id,c.content,c.ordinal FROM public.chunks c
                WHERE c.document_version_id=d.current_version_id AND octet_length(c.content)<=%s
                ORDER BY c.ordinal,c.id LIMIT %s
            ) c ORDER BY d.created_at DESC,d.id DESC,c.ordinal,c.id
        """, (ai.max_input_bytes, min(ai.max_sources, 100))).fetchall()
        selected = select_context(candidates, ai)
        if not selected:
            raise NoEligibleContext('no_eligible_context')
        run_id = connection.execute('SELECT public.start_daily_analysis_run(%s,%s,%s,%s,%s,%s,%s,%s) AS id',
            (key, [UUID(e.source_id) for e in selected], SELECTION_REVISION, pipeline, generation,
             attempts, min(ai.max_sources, 100), ai.max_input_bytes)).fetchone()['id']
        return AnalysisRuns.read(connection, run_id)
