"""Allow durable analysis jobs for all supported source kinds."""

from alembic import op

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.analysis_job_check(p_job public.analysis_jobs) RETURNS text
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public, pg_temp AS $$
        DECLARE expected integer; actual integer;
        BEGIN
            PERFORM set_config('app.workspace_id', p_job.workspace_id::text, true);
            PERFORM set_config('app.user_id', p_job.requested_by_user_id, true);
            PERFORM u.id FROM public.auth_users u WHERE u.id = p_job.requested_by_user_id AND NOT u.disabled FOR SHARE;
            IF NOT FOUND THEN RETURN 'authorization_revoked'; END IF;
            PERFORM m.user_id FROM public.workspace_members m WHERE m.workspace_id = p_job.workspace_id
                AND m.user_id = p_job.requested_by_user_id AND m.role IN ('owner','editor') FOR SHARE;
            IF NOT FOUND THEN RETURN 'authorization_revoked'; END IF;
            PERFORM d.id FROM public.documents d
                JOIN public.document_versions v ON (v.workspace_id,v.document_id) = (d.workspace_id,d.id)
                JOIN public.chunks c ON (c.workspace_id,c.document_version_id) = (v.workspace_id,v.id)
                JOIN public.analysis_job_sources s ON (s.workspace_id,s.chunk_id) = (c.workspace_id,c.id)
                WHERE s.job_id = p_job.id AND d.deleted_at IS NULL AND v.state = 'ready'
                ORDER BY d.id FOR SHARE OF d;
            SELECT count(*) INTO expected FROM public.analysis_job_sources s WHERE s.job_id = p_job.id;
            SELECT count(*) INTO actual FROM public.analysis_job_sources s
                JOIN public.chunks c ON (c.workspace_id,c.id) = (s.workspace_id,s.chunk_id)
                JOIN public.document_versions v ON (v.workspace_id,v.id) = (c.workspace_id,c.document_version_id)
                JOIN public.documents d ON (d.workspace_id,d.id) = (v.workspace_id,v.document_id)
                WHERE s.job_id = p_job.id AND d.deleted_at IS NULL AND v.state = 'ready';
            IF expected = 0 OR actual <> expected THEN RETURN 'source_invalid'; END IF;
            RETURN NULL;
        END;
        $$;
        """
    )


def downgrade():
    raise RuntimeError("Downgrades for source-type relaxation are not supported automatically.")
