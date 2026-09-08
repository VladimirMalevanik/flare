"""Durable analysis jobs and an EXECUTE-only worker capability."""
from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(r"""
        CREATE ROLE flare_job_executor NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;
        CREATE ROLE flare_worker LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;
        GRANT USAGE ON SCHEMA public TO flare_job_executor, flare_worker;

        CREATE TABLE public.analysis_jobs (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            workspace_id uuid NOT NULL REFERENCES public.workspaces(id),
            requested_by_user_id text NOT NULL REFERENCES public.auth_users(id),
            task_type text NOT NULL DEFAULT 'text_analysis' CHECK (task_type = 'text_analysis'),
            pipeline_revision text NOT NULL CHECK (length(pipeline_revision) BETWEEN 1 AND 160),
            dedupe_key text NOT NULL CHECK (dedupe_key ~ '^[0-9a-f]{64}$'),
            status text NOT NULL DEFAULT 'pending' CHECK (status IN ('pending','processing','completed','failed')),
            attempts integer NOT NULL DEFAULT 0,
            max_attempts integer NOT NULL CHECK (max_attempts BETWEEN 1 AND 10 AND attempts BETWEEN 0 AND max_attempts),
            available_at timestamptz NOT NULL DEFAULT now(),
            lease_owner uuid,
            lease_token uuid,
            lease_expires_at timestamptz,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            completed_at timestamptz,
            last_error_code text CHECK (last_error_code IN (
                'configuration','provider_auth','invalid_request','rate_limited','timeout','network',
                'provider_server','provider_transient','provider_failure','invalid_output',
                'authorization_revoked','source_invalid','pipeline_mismatch','lease_expired','internal_error'
            )),
            result jsonb,
            metadata jsonb,
            UNIQUE (workspace_id, id),
            UNIQUE (workspace_id, requested_by_user_id, task_type, dedupe_key),
            CHECK ((status = 'processing') = (lease_owner IS NOT NULL AND lease_token IS NOT NULL AND lease_expires_at IS NOT NULL)),
            CHECK (status = 'processing' OR (lease_owner IS NULL AND lease_token IS NULL AND lease_expires_at IS NULL)),
            CHECK ((status IN ('completed','failed')) = (completed_at IS NOT NULL)),
            CHECK ((status = 'completed') = (result IS NOT NULL)),
            CHECK (result IS NULL OR (jsonb_typeof(result) = 'object' AND jsonb_typeof(result->'observations') = 'array') IS TRUE),
            CHECK (metadata IS NULL OR jsonb_typeof(metadata) = 'object'),
            CHECK (status <> 'completed' OR (metadata IS NOT NULL AND last_error_code IS NULL)),
            CHECK (status <> 'failed' OR last_error_code IS NOT NULL)
        );
        CREATE INDEX analysis_jobs_pending_idx ON public.analysis_jobs(available_at, created_at, id) WHERE status = 'pending';
        CREATE INDEX analysis_jobs_lease_idx ON public.analysis_jobs(lease_expires_at, id) WHERE status = 'processing';
        CREATE TABLE public.analysis_job_sources (
            workspace_id uuid NOT NULL,
            job_id uuid NOT NULL,
            chunk_id uuid NOT NULL,
            ordinal integer NOT NULL CHECK (ordinal >= 0),
            PRIMARY KEY (job_id, chunk_id),
            UNIQUE (job_id, ordinal),
            FOREIGN KEY (workspace_id, job_id) REFERENCES public.analysis_jobs(workspace_id, id) ON DELETE CASCADE,
            FOREIGN KEY (workspace_id, chunk_id) REFERENCES public.chunks(workspace_id, id)
        );
        ALTER TABLE public.analysis_jobs ENABLE ROW LEVEL SECURITY;
        ALTER TABLE public.analysis_jobs FORCE ROW LEVEL SECURITY;
        ALTER TABLE public.analysis_job_sources ENABLE ROW LEVEL SECURITY;
        ALTER TABLE public.analysis_job_sources FORCE ROW LEVEL SECURITY;
        REVOKE ALL ON public.analysis_jobs, public.analysis_job_sources FROM PUBLIC;
        GRANT SELECT ON public.analysis_jobs, public.analysis_job_sources TO flare_app;
        GRANT SELECT, INSERT, UPDATE ON public.analysis_jobs TO flare_job_executor;
        GRANT SELECT, INSERT ON public.analysis_job_sources TO flare_job_executor;
        CREATE POLICY job_executor ON public.analysis_jobs TO flare_job_executor USING (true) WITH CHECK (true);
        CREATE POLICY job_executor ON public.analysis_job_sources TO flare_job_executor USING (true) WITH CHECK (true);
        CREATE POLICY job_reader ON public.analysis_jobs TO flare_app USING (
            workspace_id = nullif(current_setting('app.workspace_id', true),'')::uuid
            AND requested_by_user_id = nullif(current_setting('app.user_id', true),'')
            AND EXISTS (SELECT 1 FROM public.workspace_members m WHERE m.workspace_id = analysis_jobs.workspace_id
                        AND m.user_id = analysis_jobs.requested_by_user_id)
            AND EXISTS (SELECT 1 FROM public.auth_users u WHERE u.id = analysis_jobs.requested_by_user_id AND NOT u.disabled)
        );
        CREATE POLICY job_source_reader ON public.analysis_job_sources TO flare_app USING (
            EXISTS (SELECT 1 FROM public.analysis_jobs j WHERE j.id = analysis_job_sources.job_id)
        );
        -- Row locking needs UPDATE on at least one column; only the non-login
        -- function owner receives it, never the API or worker role.
        GRANT SELECT (id, disabled), UPDATE (disabled) ON public.auth_users TO flare_job_executor;
        GRANT SELECT, UPDATE (role) ON public.workspace_members TO flare_job_executor;
        GRANT SELECT, UPDATE (deleted_at) ON public.documents TO flare_job_executor;
        GRANT SELECT ON public.document_versions, public.chunks TO flare_job_executor;
        CREATE POLICY executor_identity ON public.workspace_members AS RESTRICTIVE TO flare_job_executor
            USING (user_id = nullif(current_setting('app.user_id', true),''));
    """)
    for table in ("documents", "document_versions", "chunks"):
        op.execute(f"""CREATE POLICY executor_member ON public.{table} AS RESTRICTIVE TO flare_job_executor
            USING (EXISTS (SELECT 1 FROM public.workspace_members m
                WHERE m.workspace_id = {table}.workspace_id
                AND m.user_id = nullif(current_setting('app.user_id', true),'')
                AND m.role IN ('owner','editor')))""")
    op.execute(r"""
        -- Private helper: locks only the requester, membership and referenced
        -- documents, then validates pinned snapshots. Not callable by runtime roles.
        CREATE FUNCTION public.analysis_job_check(p_job public.analysis_jobs) RETURNS text
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
                WHERE s.job_id = p_job.id AND d.deleted_at IS NULL AND d.source_type = 'note' AND v.state = 'ready'
                ORDER BY d.id FOR SHARE OF d;
            SELECT count(*) INTO expected FROM public.analysis_job_sources s WHERE s.job_id = p_job.id;
            SELECT count(*) INTO actual FROM public.analysis_job_sources s
                JOIN public.chunks c ON (c.workspace_id,c.id) = (s.workspace_id,s.chunk_id)
                JOIN public.document_versions v ON (v.workspace_id,v.id) = (c.workspace_id,c.document_version_id)
                JOIN public.documents d ON (d.workspace_id,d.id) = (v.workspace_id,v.document_id)
                WHERE s.job_id = p_job.id AND d.deleted_at IS NULL AND d.source_type = 'note' AND v.state = 'ready';
            IF expected = 0 OR actual <> expected THEN RETURN 'source_invalid'; END IF;
            RETURN NULL;
        END;
        $$;

        CREATE FUNCTION public.enqueue_analysis_job(p_chunks uuid[], p_pipeline text, p_max_attempts integer)
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
            fingerprint := encode(sha256(convert_to(jsonb_build_array(wid,uid,'text_analysis',canonical,p_pipeline)::text,'UTF8')),'hex');
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
                    SELECT wid,job.id,c.id,(c.ord-1)::integer FROM unnest(canonical) WITH ORDINALITY c(id,ord);
            END IF;
            failure := public.analysis_job_check(job);
            IF failure IS NOT NULL THEN RAISE EXCEPTION 'Job sources unavailable' USING ERRCODE='42501'; END IF;
            RETURN job.id;
        END;
        $$;

        CREATE FUNCTION public.claim_analysis_job(p_owner uuid, p_lease_seconds integer)
        RETURNS TABLE(job_id uuid, workspace_id uuid, requested_by_user_id text, pipeline_revision text,
                      lease_token uuid, lease_expires_at timestamptz, attempts integer, max_attempts integer)
        LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public, pg_temp AS $$
        DECLARE job public.analysis_jobs; token uuid; expiry timestamptz;
        BEGIN
            IF p_owner IS NULL OR p_lease_seconds IS NULL OR p_lease_seconds NOT BETWEEN 1 AND 3600 THEN
                RAISE EXCEPTION 'Invalid lease' USING ERRCODE='22023'; END IF;
            -- Bounded recovery cleanup: a crash on the final attempt cannot leave
            -- processing forever. No table/workspace locks or raw content reads.
            WITH exhausted AS (
                SELECT j.id FROM public.analysis_jobs j WHERE j.status='processing'
                    AND j.lease_expires_at <= clock_timestamp() AND j.attempts >= j.max_attempts
                ORDER BY j.lease_expires_at,j.id FOR UPDATE SKIP LOCKED LIMIT 100
            ) UPDATE public.analysis_jobs j SET status='failed', last_error_code='lease_expired',
                lease_owner=NULL,lease_token=NULL,lease_expires_at=NULL,
                completed_at=clock_timestamp(),updated_at=clock_timestamp()
                FROM exhausted e WHERE j.id=e.id;
            SELECT j.* INTO job FROM public.analysis_jobs j
                WHERE j.attempts < j.max_attempts AND (
                    (j.status='pending' AND j.available_at <= clock_timestamp()) OR
                    (j.status='processing' AND j.lease_expires_at <= clock_timestamp()))
                ORDER BY j.available_at,j.created_at,j.id FOR UPDATE SKIP LOCKED LIMIT 1;
            IF NOT FOUND THEN RETURN; END IF;
            token := gen_random_uuid(); expiry := clock_timestamp() + make_interval(secs=>p_lease_seconds);
            UPDATE public.analysis_jobs j SET status='processing',attempts=j.attempts+1,
                lease_owner=p_owner,lease_token=token,lease_expires_at=expiry,updated_at=clock_timestamp()
                WHERE j.id=job.id;
            RETURN QUERY SELECT job.id,job.workspace_id,job.requested_by_user_id,job.pipeline_revision,
                token,expiry,job.attempts+1,job.max_attempts;
        END;
        $$;

        CREATE FUNCTION public.load_analysis_evidence(p_job_id uuid, p_token uuid, p_max_sources integer, p_max_bytes integer)
        RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public, pg_temp AS $$
        DECLARE job public.analysis_jobs; failure text; source_count integer; source_bytes bigint; evidence jsonb;
        BEGIN
            SELECT * INTO job FROM public.analysis_jobs j WHERE j.id=p_job_id AND j.status='processing'
                AND j.lease_token=p_token AND j.lease_expires_at>clock_timestamp() FOR UPDATE;
            IF NOT FOUND THEN RETURN jsonb_build_object('error','lease_lost'); END IF;
            failure := public.analysis_job_check(job);
            IF failure IS NOT NULL THEN RETURN jsonb_build_object('error',failure); END IF;
            SELECT count(*),sum(octet_length(c.content)) INTO source_count,source_bytes
                FROM public.analysis_job_sources s JOIN public.chunks c ON (c.workspace_id,c.id)=(s.workspace_id,s.chunk_id)
                WHERE s.job_id=job.id;
            IF p_max_sources IS NULL OR p_max_bytes IS NULL OR p_max_sources<1 OR p_max_bytes<1
                OR source_count>p_max_sources OR source_bytes>p_max_bytes THEN
                RETURN jsonb_build_object('error','invalid_request'); END IF;
            SELECT jsonb_agg(jsonb_build_object('source_id',c.id::text,'content',c.content) ORDER BY s.ordinal)
                INTO evidence FROM public.analysis_job_sources s JOIN public.chunks c
                ON (c.workspace_id,c.id)=(s.workspace_id,s.chunk_id) WHERE s.job_id=job.id;
            IF job.lease_expires_at <= clock_timestamp() THEN RETURN jsonb_build_object('error','lease_lost'); END IF;
            RETURN jsonb_build_object('evidence',evidence);
        END;
        $$;

        CREATE FUNCTION public.finish_analysis_job(p_job_id uuid, p_token uuid, p_result jsonb,
                p_metadata jsonb, p_error text, p_retry_seconds double precision)
        RETURNS text LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public, pg_temp AS $$
        DECLARE job public.analysis_jobs; failure text; next_status text; delay double precision;
        BEGIN
            SELECT * INTO job FROM public.analysis_jobs j WHERE j.id=p_job_id AND j.status='processing'
                AND j.lease_token=p_token AND j.lease_expires_at>clock_timestamp() FOR UPDATE;
            IF NOT FOUND THEN RETURN 'lease_lost'; END IF;
            failure := public.analysis_job_check(job);
            IF failure IS NOT NULL THEN
                p_error:=failure; p_result:=NULL; p_metadata:=NULL; p_retry_seconds:=NULL;
            END IF;
            IF p_error IS NULL THEN
                IF p_result IS NULL OR p_metadata IS NULL THEN
                    RAISE EXCEPTION 'Validated result required' USING ERRCODE='22023'; END IF;
                next_status:='completed';
            ELSE
                p_result:=NULL;
                next_status:='failed';
                IF p_error IN ('rate_limited','timeout','network','provider_transient','provider_server')
                    AND p_retry_seconds IS NOT NULL AND job.attempts<job.max_attempts THEN
                    IF p_retry_seconds < 0 OR p_retry_seconds >= 'Infinity'::double precision THEN
                        RAISE EXCEPTION 'Invalid retry delay' USING ERRCODE='22023'; END IF;
                    next_status:='pending'; delay:=p_retry_seconds;
                END IF;
            END IF;
            -- Recheck the clock after potentially waiting for authorization locks.
            IF job.lease_expires_at <= clock_timestamp() THEN RETURN 'lease_lost'; END IF;
            UPDATE public.analysis_jobs j SET status=next_status,result=p_result,metadata=p_metadata,
                last_error_code=p_error,available_at=CASE WHEN next_status='pending' THEN clock_timestamp()+make_interval(secs=>delay) ELSE j.available_at END,
                lease_owner=NULL,lease_token=NULL,lease_expires_at=NULL,updated_at=clock_timestamp(),
                completed_at=CASE WHEN next_status IN ('completed','failed') THEN clock_timestamp() ELSE NULL END
                WHERE j.id=job.id;
            RETURN next_status;
        END;
        $$;
    """)
    signatures = {
        "analysis_job_check(public.analysis_jobs)": None,
        "enqueue_analysis_job(uuid[],text,integer)": "flare_app",
        "claim_analysis_job(uuid,integer)": "flare_worker",
        "load_analysis_evidence(uuid,uuid,integer,integer)": "flare_worker",
        "finish_analysis_job(uuid,uuid,jsonb,jsonb,text,double precision)": "flare_worker",
    }
    for signature, role in signatures.items():
        op.execute(f"ALTER FUNCTION public.{signature} OWNER TO flare_job_executor")
        op.execute(f"REVOKE ALL ON FUNCTION public.{signature} FROM PUBLIC")
        if role:
            op.execute(f"GRANT EXECUTE ON FUNCTION public.{signature} TO {role}")


def downgrade():
    raise RuntimeError("Durable jobs contain customer results; use a reviewed restore plan.")
