"""Queue operations for production observability and maintenance."""
import os

from alembic import op

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None


def upgrade():
    yandex = os.getenv("FLARE_DATABASE_PROVIDER", "self-managed") == "yandex"
    executor_role = "flare_owner" if yandex else "flare_job_executor"

    op.execute(
        r"""
        CREATE FUNCTION public.queue_maintenance(
            p_dry_run boolean,
            p_recover_stale boolean,
            p_analysis_completed_retention_days integer,
            p_analysis_failed_retention_days integer,
            p_flare_completed_retention_days integer,
            p_flare_failed_retention_days integer,
            p_max_rows integer
        ) RETURNS jsonb
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public, pg_temp AS $$
        DECLARE
            v_workspace uuid := nullif(current_setting('app.workspace_id', true), '')::uuid;
            v_user text := nullif(current_setting('app.user_id', true), '');
            v_stale_analysis integer := 0;
            v_stale_flare integer := 0;
            v_recovered_analysis integer := 0;
            v_recovered_flare integer := 0;
            v_analysis_candidates integer := 0;
            v_flare_candidates integer := 0;
            v_analysis_deleted integer := 0;
            v_flare_deleted integer := 0;
            v_now timestamptz := clock_timestamp();
        BEGIN
            IF v_workspace IS NULL OR v_user IS NULL THEN
                RAISE EXCEPTION 'Queue maintenance requires workspace and user context' USING ERRCODE='42501';
            END IF;
            PERFORM 1 FROM public.workspace_members m
            WHERE m.workspace_id = v_workspace
              AND m.user_id = v_user
              AND m.role = 'owner';
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Queue maintenance restricted to workspace owner' USING ERRCODE='42501';
            END IF;

            IF p_analysis_completed_retention_days IS NULL OR p_analysis_completed_retention_days < 1
               OR p_analysis_failed_retention_days IS NULL OR p_analysis_failed_retention_days < 1
               OR p_flare_completed_retention_days IS NULL OR p_flare_completed_retention_days < 1
               OR p_flare_failed_retention_days IS NULL OR p_flare_failed_retention_days < 1
               OR p_max_rows IS NULL OR p_max_rows < 1 OR p_max_rows > 100000 THEN
                RAISE EXCEPTION 'Invalid maintenance parameters' USING ERRCODE='22023';
            END IF;

            SELECT count(*) INTO v_stale_analysis FROM public.analysis_jobs j
                WHERE j.workspace_id = v_workspace
                  AND j.status = 'processing'
                  AND j.lease_expires_at <= v_now;
            SELECT count(*) INTO v_stale_flare FROM public.flare_generation_runs r
                WHERE r.workspace_id = v_workspace
                  AND r.status = 'processing'
                  AND r.lease_expires_at <= v_now;

            -- A dry run is observational: it must not fail expired jobs or
            -- otherwise change queue state while the owner is checking it.
            IF p_recover_stale AND NOT p_dry_run THEN
                WITH exhausted AS (
                    SELECT id FROM public.analysis_jobs j WHERE j.workspace_id = v_workspace
                        AND j.status = 'processing'
                        AND j.lease_expires_at <= v_now
                        AND j.attempts >= j.max_attempts
                    ORDER BY j.lease_expires_at, j.id FOR UPDATE SKIP LOCKED
                    LIMIT p_max_rows
                )
                UPDATE public.analysis_jobs j
                    SET status='failed',
                        last_error_code='lease_expired',
                        lease_owner = NULL,
                        lease_token = NULL,
                        lease_expires_at = NULL,
                        completed_at = v_now,
                        updated_at = v_now
                WHERE j.id IN (SELECT id FROM exhausted);
                GET DIAGNOSTICS v_recovered_analysis := ROW_COUNT;

                WITH exhausted AS (
                    SELECT id FROM public.flare_generation_runs r WHERE r.workspace_id = v_workspace
                        AND r.status = 'processing'
                        AND r.lease_expires_at <= v_now
                        AND r.attempts >= r.max_attempts
                    ORDER BY r.lease_expires_at, r.id FOR UPDATE SKIP LOCKED
                    LIMIT p_max_rows
                )
                UPDATE public.flare_generation_runs r
                    SET status='failed',
                        last_error_code='lease_expired',
                        lease_owner = NULL,
                        lease_token = NULL,
                        lease_expires_at = NULL,
                        completed_at = v_now,
                        updated_at = v_now
                WHERE r.id IN (SELECT id FROM exhausted);
                GET DIAGNOSTICS v_recovered_flare := ROW_COUNT;
            END IF;

            SELECT count(*) INTO v_analysis_candidates FROM (
                SELECT j.id FROM public.analysis_jobs j
                WHERE j.workspace_id = v_workspace
                  AND j.status IN ('completed', 'failed')
                  AND (
                    (j.status = 'completed' AND j.completed_at < v_now - make_interval(days => p_analysis_completed_retention_days))
                    OR
                    (j.status = 'failed' AND j.completed_at < v_now - make_interval(days => p_analysis_failed_retention_days))
                  )
                  AND NOT EXISTS (SELECT 1 FROM public.insights i WHERE i.source_analysis_job_id = j.id)
                  -- Deleting an analysis job cascades its flare run.  Retain
                  -- the parent until that downstream stage is explicitly
                  -- eligible for retention cleanup too.
                  AND NOT EXISTS (
                      SELECT 1 FROM public.flare_generation_runs r
                      WHERE r.workspace_id = j.workspace_id
                        AND r.analysis_job_id = j.id
                  )
            ) s;

            SELECT count(*) INTO v_flare_candidates FROM (
                SELECT r.id FROM public.flare_generation_runs r
                WHERE r.workspace_id = v_workspace
                  AND r.status IN ('completed', 'failed')
                  AND (
                    (r.status = 'completed' AND r.completed_at < v_now - make_interval(days => p_flare_completed_retention_days))
                    OR
                    (r.status = 'failed' AND r.completed_at < v_now - make_interval(days => p_flare_failed_retention_days))
                  )
                  AND NOT EXISTS (
                      SELECT 1 FROM unnest(coalesce(r.flare_ids, '{}'::uuid[])) fid
                      WHERE EXISTS (SELECT 1 FROM public.insights i WHERE i.id = fid AND i.workspace_id = v_workspace)
                  )
            ) s;

            IF p_dry_run THEN
                v_analysis_deleted := 0;
                v_flare_deleted := 0;
            ELSE
                WITH candidates AS (
                    SELECT j.id FROM public.analysis_jobs j
                    WHERE j.workspace_id = v_workspace
                      AND j.status IN ('completed', 'failed')
                      AND (
                        (j.status = 'completed' AND j.completed_at < v_now - make_interval(days => p_analysis_completed_retention_days))
                        OR
                        (j.status = 'failed' AND j.completed_at < v_now - make_interval(days => p_analysis_failed_retention_days))
                      )
                      AND NOT EXISTS (SELECT 1 FROM public.insights i WHERE i.source_analysis_job_id = j.id)
                      AND NOT EXISTS (
                          SELECT 1 FROM public.flare_generation_runs r
                          WHERE r.workspace_id = j.workspace_id
                            AND r.analysis_job_id = j.id
                      )
                    ORDER BY j.completed_at, j.id
                    LIMIT p_max_rows
                ), deleted AS (
                    DELETE FROM public.analysis_jobs j
                    USING candidates c
                    WHERE j.id = c.id
                    RETURNING j.id
                ) SELECT count(*) INTO v_analysis_deleted FROM deleted;

                WITH candidates AS (
                    SELECT r.id FROM public.flare_generation_runs r
                    WHERE r.workspace_id = v_workspace
                      AND r.status IN ('completed', 'failed')
                      AND (
                        (r.status = 'completed' AND r.completed_at < v_now - make_interval(days => p_flare_completed_retention_days))
                        OR
                        (r.status = 'failed' AND r.completed_at < v_now - make_interval(days => p_flare_failed_retention_days))
                      )
                      AND NOT EXISTS (
                          SELECT 1 FROM unnest(coalesce(r.flare_ids, '{}'::uuid[])) fid
                          WHERE EXISTS (SELECT 1 FROM public.insights i WHERE i.id = fid AND i.workspace_id = v_workspace)
                      )
                    ORDER BY r.completed_at, r.id
                    LIMIT p_max_rows
                ), deleted AS (
                    DELETE FROM public.flare_generation_runs r
                    USING candidates c
                    WHERE r.id = c.id
                    RETURNING r.id
                ) SELECT count(*) INTO v_flare_deleted FROM deleted;
            END IF;

            RETURN jsonb_build_object(
                'analysis_jobs', jsonb_build_object(
                    'candidates', v_analysis_candidates,
                    'deleted', v_analysis_deleted,
                    'retained_workspace_days', p_analysis_completed_retention_days,
                    'retained_failed_days', p_analysis_failed_retention_days
                ),
                'flare_generation_runs', jsonb_build_object(
                    'candidates', v_flare_candidates,
                    'deleted', v_flare_deleted,
                    'retained_workspace_days', p_flare_completed_retention_days,
                    'retained_failed_days', p_flare_failed_retention_days
                ),
                'recovered_stale_analysis_jobs', v_recovered_analysis,
                'recovered_stale_flare_runs', v_recovered_flare,
                'stale_processing', jsonb_build_object(
                    'analysis_jobs', v_stale_analysis,
                    'flare_generation_runs', v_stale_flare
                ),
                'max_rows', p_max_rows,
                'dry_run', p_dry_run
            );
        END;
        $$;
        """
    )

    signatures = {
        "queue_maintenance(boolean,boolean,integer,integer,integer,integer,integer)": "flare_app",
    }
    for signature, role in signatures.items():
        if not yandex:
            op.execute(f"ALTER FUNCTION public.{signature} OWNER TO {executor_role}")
        op.execute(f"REVOKE ALL ON FUNCTION public.{signature} FROM PUBLIC")
        if role:
            op.execute(f"GRANT EXECUTE ON FUNCTION public.{signature} TO {role}")
    # The SECURITY DEFINER owner performs retention deletes.  It is a NOLOGIN
    # role in self-managed PostgreSQL; API and worker roles do not inherit this
    # capability.  On managed PostgreSQL the selected owner already owns the
    # tables, and this explicit grant is harmless.
    op.execute(
        f"GRANT DELETE ON public.analysis_jobs, public.flare_generation_runs TO {executor_role}"
    )


def downgrade():
    raise RuntimeError("Queue maintenance contains production retention controls; review restore plan required.")
