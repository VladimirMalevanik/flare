"""Public idempotent analysis runs using the existing durable queue."""
import os
from alembic import op

revision = '0007'
down_revision = '0006'
branch_labels = None
depends_on = None


def upgrade():
    owner = 'flare_owner' if os.getenv('FLARE_DATABASE_PROVIDER') == 'yandex' else 'flare_job_executor'
    op.execute(f"""
        CREATE TABLE public.analysis_runs (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            workspace_id uuid NOT NULL REFERENCES public.workspaces(id),
            requested_by_user_id text NOT NULL REFERENCES public.auth_users(id),
            idempotency_key uuid NOT NULL,
            analysis_job_id uuid NOT NULL UNIQUE,
            selection_revision text NOT NULL CHECK(length(selection_revision) BETWEEN 1 AND 160),
            pipeline_revision text NOT NULL CHECK(length(pipeline_revision) BETWEEN 1 AND 160),
            generation_revision text NOT NULL CHECK(length(generation_revision) BETWEEN 1 AND 160),
            selected_chunk_count integer NOT NULL CHECK(selected_chunk_count BETWEEN 1 AND 100),
            created_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE(workspace_id,requested_by_user_id,idempotency_key),
            FOREIGN KEY(workspace_id,analysis_job_id) REFERENCES public.analysis_jobs(workspace_id,id) ON DELETE CASCADE
        );
        ALTER TABLE public.analysis_runs ENABLE ROW LEVEL SECURITY;
        ALTER TABLE public.analysis_runs FORCE ROW LEVEL SECURITY;
        REVOKE ALL ON public.analysis_runs FROM PUBLIC;
        GRANT SELECT ON public.analysis_runs TO flare_app;
        GRANT SELECT,INSERT ON public.analysis_runs TO {owner};
        CREATE POLICY run_executor ON public.analysis_runs TO {owner} USING(true) WITH CHECK(true);
        CREATE POLICY run_reader ON public.analysis_runs TO flare_app USING(
            workspace_id=nullif(current_setting('app.workspace_id',true),'')::uuid
            AND EXISTS(SELECT 1 FROM public.workspace_members m WHERE m.workspace_id=analysis_runs.workspace_id
                AND m.user_id=nullif(current_setting('app.user_id',true),'')));
    """)
    # Shared enqueue implementation: a public request key creates a fresh logical
    # attempt; the legacy three-argument API retains its exact dedupe semantics.
    op.execute(r"""
        CREATE OR REPLACE FUNCTION public.enqueue_analysis_job(p_chunks uuid[], p_pipeline text, p_max_attempts integer, p_request_key uuid)
        RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public, pg_temp AS $$
        DECLARE wid uuid := nullif(current_setting('app.workspace_id',true),'')::uuid;
            uid text := nullif(current_setting('app.user_id',true),'');
            canonical uuid[]; fingerprint text; job public.analysis_jobs; failure text; new_id uuid;
        BEGIN
            IF wid IS NULL OR uid IS NULL THEN RAISE EXCEPTION 'Job authorization required' USING ERRCODE='42501'; END IF;
            IF p_chunks IS NULL OR cardinality(p_chunks) NOT BETWEEN 1 AND 100
                OR array_position(p_chunks,NULL) IS NOT NULL THEN
                RAISE EXCEPTION 'Invalid job sources' USING ERRCODE='22023'; END IF;
            SELECT array_agg(x ORDER BY x) INTO canonical FROM (SELECT DISTINCT unnest(p_chunks) x) t;
            IF cardinality(canonical) <> cardinality(p_chunks) THEN
                RAISE EXCEPTION 'Duplicate job sources' USING ERRCODE='22023'; END IF;
            fingerprint := encode(sha256(convert_to(
                CASE WHEN p_request_key IS NULL THEN jsonb_build_array(wid,uid,'text_analysis',canonical,p_pipeline)
                     ELSE jsonb_build_array(wid,uid,'public_analysis',p_request_key) END::text,'UTF8')),'hex');
            -- Even duplicate enqueues must still be currently authorized.
            PERFORM u.id FROM public.auth_users u WHERE u.id=uid AND NOT u.disabled FOR SHARE;
            IF NOT FOUND THEN RAISE EXCEPTION 'Job authorization required' USING ERRCODE='42501'; END IF;
            PERFORM m.user_id FROM public.workspace_members m WHERE m.workspace_id=wid AND m.user_id=uid
                AND m.role IN ('owner','editor') FOR SHARE;
            IF NOT FOUND THEN RAISE EXCEPTION 'Job authorization required' USING ERRCODE='42501'; END IF;
            INSERT INTO public.analysis_jobs(workspace_id,requested_by_user_id,pipeline_revision,dedupe_key,max_attempts)
                VALUES (wid,uid,p_pipeline,fingerprint,p_max_attempts)
                ON CONFLICT (workspace_id,requested_by_user_id,task_type,dedupe_key) DO NOTHING RETURNING id INTO new_id;
            SELECT * INTO job FROM public.analysis_jobs j WHERE j.workspace_id=wid AND j.requested_by_user_id=uid
                AND j.task_type='text_analysis' AND j.dedupe_key=fingerprint;
            IF new_id IS NOT NULL THEN
                INSERT INTO public.analysis_job_sources(workspace_id,job_id,chunk_id,ordinal)
                    SELECT wid,job.id,ids.id,(row_number() OVER(ORDER BY d.created_at,d.id,v.version_number,c.ordinal,c.id)-1)::integer
                    FROM unnest(canonical) ids(id)
                    LEFT JOIN public.chunks c ON c.id=ids.id AND c.workspace_id=wid
                    LEFT JOIN public.document_versions v ON(v.workspace_id,v.id)=(c.workspace_id,c.document_version_id)
                    LEFT JOIN public.documents d ON(d.workspace_id,d.id)=(v.workspace_id,v.document_id);
            END IF;
            failure := public.analysis_job_check(job);
            IF failure IS NOT NULL THEN RAISE EXCEPTION 'Job sources unavailable' USING ERRCODE='42501'; END IF;
            RETURN job.id;
        END;
        $$;
    """)
    op.execute(r"""
        CREATE OR REPLACE FUNCTION public.enqueue_analysis_job(p_chunks uuid[],p_pipeline text,p_max_attempts integer)
        RETURNS uuid LANGUAGE sql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
            SELECT public.enqueue_analysis_job(p_chunks,p_pipeline,p_max_attempts,NULL::uuid)
        $$;

        CREATE FUNCTION public.start_analysis_run(p_key uuid,p_chunks uuid[],p_selection text,
            p_pipeline text,p_generation text,p_attempts integer,p_sources integer,p_bytes integer)
        RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
        DECLARE wid uuid:=nullif(current_setting('app.workspace_id',true),'')::uuid;
            uid text:=nullif(current_setting('app.user_id',true),'');
            result uuid; job uuid; actual integer;
        BEGIN
            IF wid IS NULL OR uid IS NULL OR p_key IS NULL THEN
                RAISE EXCEPTION 'Authorization required' USING ERRCODE='42501'; END IF;
            PERFORM id FROM public.auth_users WHERE id=uid AND NOT disabled FOR SHARE;
            IF NOT FOUND THEN RAISE EXCEPTION 'Authorization required' USING ERRCODE='42501'; END IF;
            PERFORM user_id FROM public.workspace_members WHERE workspace_id=wid AND user_id=uid
                AND role IN ('owner','editor') FOR SHARE;
            IF NOT FOUND THEN RAISE EXCEPTION 'Write permission required' USING ERRCODE='42501'; END IF;
            PERFORM pg_advisory_xact_lock(hashtextextended(wid::text||uid||p_key::text,0));
            SELECT id INTO result FROM public.analysis_runs WHERE workspace_id=wid
                AND requested_by_user_id=uid AND idempotency_key=p_key;
            IF FOUND THEN RETURN result; END IF;
            IF p_sources IS NULL OR p_sources NOT BETWEEN 1 AND 100 OR p_bytes IS NULL OR p_bytes<1
                OR p_chunks IS NULL OR cardinality(p_chunks) NOT BETWEEN 1 AND p_sources THEN
                RAISE EXCEPTION 'Invalid selection' USING ERRCODE='22023'; END IF;
            -- Lock documents before checking their current version. Updates/deletes
            -- cannot race the durable snapshot boundary.
            PERFORM d.id FROM public.documents d JOIN public.document_versions v
                ON(v.workspace_id,v.document_id)=(d.workspace_id,d.id)
                JOIN public.chunks c ON(c.workspace_id,c.document_version_id)=(v.workspace_id,v.id)
                WHERE c.id=ANY(p_chunks) AND d.workspace_id=wid ORDER BY d.id FOR SHARE OF d;
            SELECT count(*) INTO actual FROM public.documents d JOIN public.document_versions v
                ON(v.workspace_id,v.id)=(d.workspace_id,d.current_version_id)
                JOIN public.chunks c ON(c.workspace_id,c.document_version_id)=(v.workspace_id,v.id)
                WHERE c.id=ANY(p_chunks) AND d.workspace_id=wid AND d.source_type='note'
                  AND d.deleted_at IS NULL AND v.state='ready';
            IF actual<>cardinality(p_chunks) OR
                (SELECT sum(octet_length(content)) FROM public.chunks WHERE workspace_id=wid AND id=ANY(p_chunks))>p_bytes THEN
                RAISE EXCEPTION 'Selection changed' USING ERRCODE='22023'; END IF;
            job:=public.enqueue_analysis_job(p_chunks,p_pipeline,p_attempts,p_key);
            INSERT INTO public.analysis_runs(workspace_id,requested_by_user_id,idempotency_key,analysis_job_id,
                selection_revision,pipeline_revision,generation_revision,selected_chunk_count)
                VALUES(wid,uid,p_key,job,p_selection,p_pipeline,p_generation,actual) RETURNING id INTO result;
            RETURN result;
        END $$;

        CREATE FUNCTION public.read_analysis_run(p_id uuid) RETURNS jsonb
        LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
        DECLARE wid uuid:=nullif(current_setting('app.workspace_id',true),'')::uuid;
            uid text:=nullif(current_setting('app.user_id',true),'');
            value jsonb;
        BEGIN
            IF NOT EXISTS(SELECT 1 FROM public.workspace_members m JOIN public.auth_users u ON u.id=m.user_id
                WHERE m.workspace_id=wid AND m.user_id=uid AND NOT u.disabled) THEN RETURN NULL; END IF;
            SELECT jsonb_build_object('id',r.id,'selectedChunkCount',r.selected_chunk_count,
                'status',CASE WHEN j.status='failed' THEN 'failed' WHEN j.status<>'completed' THEN j.status
                    WHEN g.status IS NULL THEN 'failed' ELSE g.status END,
                'stage',CASE WHEN j.status='failed' THEN 'failed' WHEN j.status<>'completed' THEN 'analysis'
                    WHEN g.status IS NULL THEN 'failed' WHEN g.status IN ('completed','failed') THEN g.status ELSE 'flare_generation' END,
                'flareIds',CASE WHEN g.status='completed' AND j.status='completed' THEN to_jsonb(g.flare_ids) ELSE '[]'::jsonb END,
                'error',CASE WHEN j.status='failed' THEN j.last_error_code
                    WHEN j.status='completed' AND g.status IS NULL THEN 'generation_mismatch'
                    WHEN g.status='failed' THEN g.last_error_code ELSE NULL END)
            INTO value FROM public.analysis_runs r JOIN public.analysis_jobs j ON(j.workspace_id,j.id)=(r.workspace_id,r.analysis_job_id)
            LEFT JOIN public.flare_generation_runs g ON g.analysis_job_id=j.id AND g.generation_revision=r.generation_revision
            WHERE r.id=p_id AND r.workspace_id=wid;
            RETURN value;
        END $$;

        CREATE OR REPLACE FUNCTION public.handoff_flare_generation() RETURNS trigger
        LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
        DECLARE revision text;
        BEGIN
            SELECT generation_revision INTO revision FROM public.analysis_runs WHERE analysis_job_id=NEW.id;
            PERFORM public.enqueue_flare_generation(NEW.id,coalesce(revision,
                nullif(current_setting('app.flare_generation_revision',true),''),'unconfigured'),NEW.max_attempts);
            RETURN NEW;
        END $$;
    """)
    for signature, role in {
        'enqueue_analysis_job(uuid[],text,integer,uuid)': None,
        'enqueue_analysis_job(uuid[],text,integer)': 'flare_app',
        'start_analysis_run(uuid,uuid[],text,text,text,integer,integer,integer)': 'flare_app',
        'read_analysis_run(uuid)': 'flare_app',
        'handoff_flare_generation()': None,
    }.items():
        op.execute(f'ALTER FUNCTION public.{signature} OWNER TO {owner}')
        op.execute(f'REVOKE ALL ON FUNCTION public.{signature} FROM PUBLIC')
        if role:
            op.execute(f'GRANT EXECUTE ON FUNCTION public.{signature} TO {role}')


def downgrade():
    raise RuntimeError('Analysis runs require a reviewed restore plan')
