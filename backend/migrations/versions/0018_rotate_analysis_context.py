"""Rotate scheduled context using existing daily cycle source history."""

from alembic import op


revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Replace only the existing worker capability. PostgreSQL retains its owner
    # and EXECUTE grants; this migration creates no new tables or permissions.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.load_analysis_cycle_candidates(
            p_cycle uuid, p_token uuid, p_max_sources integer, p_max_bytes integer)
        RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER
        SET search_path=pg_catalog,public,pg_temp AS $$
        DECLARE cycle public.analysis_cycles; candidates jsonb;
        BEGIN
            IF p_max_sources IS NULL OR p_max_sources NOT BETWEEN 1 AND 100
                OR p_max_bytes IS NULL OR p_max_bytes<1 THEN
                RAISE EXCEPTION 'Invalid candidate bounds' USING ERRCODE='22023'; END IF;
            SELECT * INTO cycle FROM public.analysis_cycles c WHERE c.id=p_cycle
                AND c.refresh_status='refreshing' AND c.refresh_lease_token=p_token
                AND c.refresh_lease_expires_at>clock_timestamp();
            IF NOT FOUND THEN RETURN jsonb_build_object('error','lease_lost'); END IF;
            -- The worker calls through a fresh connection; restore the claimed
            -- cycle's tenant context before any RLS-protected read.
            PERFORM set_config('app.workspace_id',cycle.workspace_id::text,true);
            PERFORM set_config('app.user_id',cycle.requested_by_user_id,true);
            IF NOT EXISTS(SELECT 1 FROM public.auth_users u JOIN public.workspace_members m ON m.user_id=u.id
                WHERE u.id=cycle.requested_by_user_id AND NOT u.disabled
                  AND m.workspace_id=cycle.workspace_id AND m.role IN ('owner','editor')) THEN
                UPDATE public.analysis_schedules s SET enabled=false
                    WHERE s.workspace_id=cycle.workspace_id
                      AND s.updated_by_user_id=cycle.requested_by_user_id;
                RETURN jsonb_build_object('error','authorization_revoked'); END IF;

            WITH history AS MATERIALIZED (
                SELECT s.chunk_id,c.document_version_id,
                       max(coalesce(prior.refreshed_at,prior.created_at)) AS last_selected_at
                FROM public.analysis_cycle_sources s
                JOIN public.analysis_cycles prior
                  ON (prior.workspace_id,prior.id)=(s.workspace_id,s.cycle_id)
                JOIN public.chunks c ON (c.workspace_id,c.id)=(s.workspace_id,s.chunk_id)
                WHERE s.workspace_id=cycle.workspace_id
                GROUP BY s.chunk_id,c.document_version_id
            ), candidate_documents AS MATERIALIZED (
                SELECT d.workspace_id,d.id,d.current_version_id,d.updated_at,
                       max(history.last_selected_at) AS document_last_selected_at
                FROM public.documents d
                JOIN public.document_versions v
                  ON (v.workspace_id,v.id)=(d.workspace_id,d.current_version_id)
                LEFT JOIN history ON history.document_version_id=d.current_version_id
                WHERE d.workspace_id=cycle.workspace_id AND d.deleted_at IS NULL
                  AND d.source_type IN ('note','file','url','audio') AND v.state='ready'
                  AND EXISTS (
                      SELECT 1 FROM public.chunks available
                      WHERE (available.workspace_id,available.document_version_id)=(d.workspace_id,v.id)
                        AND octet_length(available.content)<=p_max_bytes
                  )
                GROUP BY d.workspace_id,d.id,d.current_version_id,d.updated_at
                ORDER BY document_last_selected_at ASC NULLS FIRST,d.updated_at DESC,d.id DESC
                LIMIT 200
            ), scored AS (
                SELECT d.id AS document_id,d.updated_at,d.document_last_selected_at,
                       chosen.id AS chunk_id,chosen.ordinal,chosen.last_selected_at
                FROM candidate_documents d
                CROSS JOIN LATERAL (
                    SELECT c.id,c.ordinal,history.last_selected_at
                    FROM public.chunks c
                    LEFT JOIN history ON history.chunk_id=c.id
                    WHERE (c.workspace_id,c.document_version_id)=(d.workspace_id,d.current_version_id)
                      AND octet_length(c.content)<=p_max_bytes
                    ORDER BY history.last_selected_at ASC NULLS FIRST,c.ordinal,c.id
                    LIMIT p_max_sources
                ) chosen
            ), ranked AS (
                SELECT scored.*,
                       row_number() OVER (PARTITION BY document_id
                           ORDER BY last_selected_at ASC NULLS FIRST,ordinal,chunk_id) AS document_round
                FROM scored
            )
            SELECT jsonb_agg(jsonb_build_object('id',q.id,'content',q.content) ORDER BY q.row_order)
            INTO candidates FROM (
                SELECT c.id,c.content,
                       row_number() OVER (
                           ORDER BY r.document_round,r.document_last_selected_at ASC NULLS FIRST,
                                    r.updated_at DESC,r.document_id DESC,
                                    r.last_selected_at ASC NULLS FIRST,r.ordinal,r.chunk_id
                       ) AS row_order
                FROM ranked r
                JOIN public.chunks c ON (c.workspace_id,c.id)=(cycle.workspace_id,r.chunk_id)
                ORDER BY r.document_round,r.document_last_selected_at ASC NULLS FIRST,
                         r.updated_at DESC,r.document_id DESC,
                         r.last_selected_at ASC NULLS FIRST,r.ordinal,r.chunk_id
                LIMIT LEAST(p_max_sources*4,400)
            ) q;
            RETURN jsonb_build_object('candidates',coalesce(candidates,'[]'::jsonb));
        END $$;
        """
    )


def downgrade() -> None:
    # Restore the exact 0015 candidate query. CREATE OR REPLACE preserves the
    # existing function identity, owner and restricted EXECUTE grants.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION public.load_analysis_cycle_candidates(p_cycle uuid,p_token uuid,
            p_max_sources integer,p_max_bytes integer)
        RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER
        SET search_path=pg_catalog,public,pg_temp AS $$
        DECLARE cycle public.analysis_cycles; candidates jsonb;
        BEGIN
            IF p_max_sources IS NULL OR p_max_sources NOT BETWEEN 1 AND 100
                OR p_max_bytes IS NULL OR p_max_bytes<1 THEN
                RAISE EXCEPTION 'Invalid candidate bounds' USING ERRCODE='22023'; END IF;
            SELECT * INTO cycle FROM public.analysis_cycles c WHERE c.id=p_cycle
                AND c.refresh_status='refreshing' AND c.refresh_lease_token=p_token
                AND c.refresh_lease_expires_at>clock_timestamp();
            IF NOT FOUND THEN RETURN jsonb_build_object('error','lease_lost'); END IF;
            -- Worker calls intentionally use a fresh connection.  Rebuild the
            -- transaction-local tenant context before any RLS-protected read.
            PERFORM set_config('app.workspace_id',cycle.workspace_id::text,true);
            PERFORM set_config('app.user_id',cycle.requested_by_user_id,true);
            IF NOT EXISTS(SELECT 1 FROM public.auth_users u JOIN public.workspace_members m ON m.user_id=u.id
                WHERE u.id=cycle.requested_by_user_id AND NOT u.disabled
                  AND m.workspace_id=cycle.workspace_id AND m.role IN ('owner','editor')) THEN
                -- Stop creating one doomed cycle per day.  Do not disable a
                -- schedule that a different active editor has since adopted.
                UPDATE public.analysis_schedules s SET enabled=false
                    WHERE s.workspace_id=cycle.workspace_id
                      AND s.updated_by_user_id=cycle.requested_by_user_id;
                RETURN jsonb_build_object('error','authorization_revoked'); END IF;
            SELECT jsonb_agg(jsonb_build_object('id',q.id,'content',q.content) ORDER BY q.row_order)
            INTO candidates FROM (
                SELECT c.id,c.content,row_number() OVER(ORDER BY d.updated_at DESC,d.id DESC,c.ordinal,c.id) row_order
                FROM (SELECT d.* FROM public.documents d
                    JOIN public.document_versions current_version
                      ON(current_version.workspace_id,current_version.id)=
                        (d.workspace_id,d.current_version_id)
                    WHERE d.workspace_id=cycle.workspace_id AND d.deleted_at IS NULL
                      AND d.source_type IN ('note','file','url','audio')
                      AND current_version.state='ready'
                      AND EXISTS(SELECT 1 FROM public.chunks available
                          WHERE (available.workspace_id,available.document_version_id)=
                            (d.workspace_id,current_version.id))
                    ORDER BY d.updated_at DESC,d.id DESC LIMIT 200) d
                JOIN public.document_versions v ON(v.workspace_id,v.id)=(d.workspace_id,d.current_version_id)
                CROSS JOIN LATERAL (
                    SELECT c.id,c.content,c.ordinal FROM public.chunks c
                    WHERE (c.workspace_id,c.document_version_id)=(v.workspace_id,v.id)
                      AND octet_length(c.content)<=p_max_bytes
                    ORDER BY c.ordinal,c.id LIMIT p_max_sources
                ) c
                WHERE v.state='ready'
                ORDER BY d.updated_at DESC,d.id DESC,c.ordinal,c.id
                LIMIT LEAST(p_max_sources * 4, 400)
            ) q;
            RETURN jsonb_build_object('candidates',coalesce(candidates,'[]'::jsonb));
        END $$;
        """
    )
