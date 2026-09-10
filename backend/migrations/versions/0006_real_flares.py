"""Durable Flare stage, atomic handoff and typed evidence-backed persistence."""
import os

from alembic import op

revision = '0006'
down_revision = '0005'
branch_labels = None
depends_on = None


def upgrade():
    yandex = os.getenv("FLARE_DATABASE_PROVIDER", "self-managed") == "yandex"
    executor_role = "flare_owner" if yandex else "flare_job_executor"
    op.execute(r"""
    CREATE TABLE public.flare_generation_runs (
        id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
        workspace_id uuid NOT NULL,
        analysis_job_id uuid NOT NULL,
        generation_revision text NOT NULL CHECK(length(generation_revision) BETWEEN 1 AND 160),
        status text NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','processing','completed','failed')),
        attempts integer NOT NULL DEFAULT 0,
        max_attempts integer NOT NULL CHECK(max_attempts BETWEEN 1 AND 10 AND attempts BETWEEN 0 AND max_attempts),
        available_at timestamptz NOT NULL DEFAULT now(),
        lease_owner uuid, lease_token uuid, lease_expires_at timestamptz,
        created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now(),
        completed_at timestamptz,
        last_error_code text CHECK(last_error_code IN ('configuration','provider_auth','invalid_request','invalid_output',
            'rate_limited','timeout','network','provider_transient','provider_server','provider_failure',
            'authorization_revoked','source_invalid','generation_mismatch','lease_expired','internal_error')),
        metadata jsonb CHECK(metadata IS NULL OR jsonb_typeof(metadata)='object'),
        flare_ids uuid[],
        UNIQUE(analysis_job_id,generation_revision),
        UNIQUE(workspace_id,id),
        FOREIGN KEY(workspace_id,analysis_job_id) REFERENCES public.analysis_jobs(workspace_id,id) ON DELETE CASCADE,
        CHECK((status='processing')=(lease_owner IS NOT NULL AND lease_token IS NOT NULL AND lease_expires_at IS NOT NULL)),
        CHECK(status='processing' OR (lease_owner IS NULL AND lease_token IS NULL AND lease_expires_at IS NULL)),
        CHECK((status IN ('completed','failed'))=(completed_at IS NOT NULL)),
        CHECK((status='completed')=(flare_ids IS NOT NULL)),
        CHECK(flare_ids IS NULL OR cardinality(flare_ids)<=3),
        CHECK(status<>'completed' OR last_error_code IS NULL),
        CHECK(status<>'failed' OR last_error_code IS NOT NULL)
    );
    CREATE INDEX flare_runs_pending_idx ON public.flare_generation_runs(available_at,created_at,id) WHERE status='pending';
    CREATE INDEX flare_runs_lease_idx ON public.flare_generation_runs(lease_expires_at,id) WHERE status='processing';
    ALTER TABLE public.flare_generation_runs ENABLE ROW LEVEL SECURITY;
    ALTER TABLE public.flare_generation_runs FORCE ROW LEVEL SECURITY;
    REVOKE ALL ON public.flare_generation_runs FROM PUBLIC;
    GRANT SELECT ON public.flare_generation_runs TO flare_app;
    GRANT SELECT,INSERT,UPDATE ON public.flare_generation_runs TO flare_job_executor;
    CREATE POLICY flare_run_executor ON public.flare_generation_runs TO flare_job_executor USING(true) WITH CHECK(true);
    CREATE POLICY flare_run_reader ON public.flare_generation_runs TO flare_app USING(
        workspace_id=nullif(current_setting('app.workspace_id',true),'')::uuid
        AND EXISTS(SELECT 1 FROM public.analysis_jobs j WHERE j.id=flare_generation_runs.analysis_job_id));

    ALTER TABLE public.insights
        ADD COLUMN flare_type text CHECK(flare_type IN ('Reminder','Warning','Recommendation')),
        ALTER COLUMN summary DROP NOT NULL,
        ADD COLUMN action text,
        ADD COLUMN reason text,
        ADD COLUMN source_analysis_job_id uuid,
        ADD COLUMN generation_revision text,
        ADD COLUMN detector_schema_version text,
        ADD COLUMN candidate_fingerprint text,
        ADD CONSTRAINT insight_parent_fk FOREIGN KEY(workspace_id,source_analysis_job_id)
            REFERENCES public.analysis_jobs(workspace_id,id),
        ADD CONSTRAINT insight_fingerprint_unique UNIQUE(workspace_id,candidate_fingerprint),
        ADD CONSTRAINT typed_flare CHECK(flare_type IS NULL OR (
            title IS NOT NULL AND length(btrim(title)) BETWEEN 1 AND 80
            AND length(body) BETWEEN 1 AND 180
            AND reason IS NOT NULL AND length(btrim(reason)) BETWEEN 1 AND 240
            AND (action IS NULL OR length(btrim(action)) BETWEEN 1 AND 160)
            AND (flare_type<>'Recommendation' OR action IS NOT NULL)
            AND source_analysis_job_id IS NOT NULL AND generation_revision IS NOT NULL
            AND detector_schema_version IS NOT NULL AND candidate_fingerprint IS NOT NULL
            AND candidate_fingerprint ~ '^[0-9a-f]{64}$'));
    CREATE INDEX flare_list_idx ON public.insights(workspace_id,created_at DESC,id DESC) WHERE flare_type IS NOT NULL;
    ALTER TABLE public.insight_sources ADD COLUMN ordinal integer CHECK(ordinal BETWEEN 0 AND 3),
        ADD CONSTRAINT typed_quote CHECK(ordinal IS NULL OR (quote IS NOT NULL AND length(btrim(quote)) BETWEEN 1 AND 240)),
        ADD CONSTRAINT insight_source_order UNIQUE(workspace_id,insight_id,ordinal);
    REVOKE INSERT,UPDATE,DELETE ON public.insights,public.insight_sources FROM flare_app;
    GRANT SELECT,INSERT ON public.insights,public.insight_sources TO flare_job_executor;
    CREATE POLICY flare_writer ON public.insights AS RESTRICTIVE TO flare_job_executor
        USING(EXISTS(SELECT 1 FROM public.workspace_members m WHERE m.workspace_id=insights.workspace_id
            AND m.user_id=nullif(current_setting('app.user_id',true),'') AND m.role IN ('owner','editor')));
    CREATE POLICY flare_writer ON public.insight_sources AS RESTRICTIVE TO flare_job_executor
        USING(EXISTS(SELECT 1 FROM public.workspace_members m WHERE m.workspace_id=insight_sources.workspace_id
            AND m.user_id=nullif(current_setting('app.user_id',true),'') AND m.role IN ('owner','editor')));

    -- Exactly Python str.split whitespace characters; never fuzzy matching.
    CREATE FUNCTION public.flare_normalize(value text) RETURNS text LANGUAGE sql IMMUTABLE
        SET search_path=pg_catalog,public,pg_temp AS $$
        SELECT btrim(regexp_replace(value,U&'[\0009-\000D\001C-\0020\0085\00A0\1680\2000-\200A\2028\2029\202F\205F\3000]+',' ','g'))
    $$;

    CREATE FUNCTION public.enqueue_flare_generation(p_parent uuid,p_revision text,p_attempts integer)
    RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
    DECLARE parent public.analysis_jobs; result_id uuid; failure text;
    BEGIN
        SELECT * INTO parent FROM public.analysis_jobs j WHERE j.id=p_parent AND j.status='completed';
        IF NOT FOUND THEN RAISE EXCEPTION 'Completed analysis unavailable' USING ERRCODE='42501'; END IF;
        failure:=public.analysis_job_check(parent);
        IF failure IS NOT NULL THEN RAISE EXCEPTION 'Analysis authorization unavailable' USING ERRCODE='42501'; END IF;
        INSERT INTO public.flare_generation_runs(workspace_id,analysis_job_id,generation_revision,max_attempts)
            VALUES(parent.workspace_id,parent.id,p_revision,p_attempts) ON CONFLICT(analysis_job_id,generation_revision) DO NOTHING;
        SELECT id INTO result_id FROM public.flare_generation_runs WHERE analysis_job_id=p_parent AND generation_revision=p_revision;
        RETURN result_id;
    END $$;

    CREATE FUNCTION public.handoff_flare_generation() RETURNS trigger
    LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
    BEGIN
        PERFORM public.enqueue_flare_generation(NEW.id,
            coalesce(nullif(current_setting('app.flare_generation_revision',true),''),'unconfigured'),NEW.max_attempts);
        RETURN NEW;
    END $$;
    CREATE TRIGGER completed_analysis_handoff AFTER UPDATE OF status ON public.analysis_jobs
        FOR EACH ROW WHEN(NEW.status='completed' AND OLD.status<>'completed')
        EXECUTE FUNCTION public.handoff_flare_generation();

    CREATE FUNCTION public.claim_flare_generation(p_owner uuid,p_seconds integer)
    RETURNS SETOF public.flare_generation_runs LANGUAGE plpgsql SECURITY DEFINER
        SET search_path=pg_catalog,public,pg_temp AS $$
    DECLARE selected public.flare_generation_runs;
    BEGIN
        IF p_owner IS NULL OR p_seconds IS NULL OR p_seconds NOT BETWEEN 1 AND 3600 THEN
            RAISE EXCEPTION 'Invalid lease' USING ERRCODE='22023'; END IF;
        WITH expired AS(SELECT id FROM public.flare_generation_runs WHERE status='processing'
            AND lease_expires_at<=clock_timestamp() AND attempts>=max_attempts
            ORDER BY lease_expires_at,id FOR UPDATE SKIP LOCKED LIMIT 100)
        UPDATE public.flare_generation_runs r SET status='failed',last_error_code='lease_expired',
            lease_owner=NULL,lease_token=NULL,lease_expires_at=NULL,completed_at=clock_timestamp(),updated_at=clock_timestamp()
            FROM expired e WHERE r.id=e.id;
        SELECT * INTO selected FROM public.flare_generation_runs r WHERE r.attempts<r.max_attempts AND
            ((r.status='pending' AND r.available_at<=clock_timestamp()) OR
             (r.status='processing' AND r.lease_expires_at<=clock_timestamp()))
            ORDER BY r.available_at,r.created_at,r.id FOR UPDATE SKIP LOCKED LIMIT 1;
        IF NOT FOUND THEN RETURN; END IF;
        RETURN QUERY UPDATE public.flare_generation_runs r SET status='processing',attempts=r.attempts+1,
            lease_owner=p_owner,lease_token=gen_random_uuid(),lease_expires_at=clock_timestamp()+make_interval(secs=>p_seconds),
            updated_at=clock_timestamp() WHERE r.id=selected.id RETURNING r.*;
    END $$;

    CREATE FUNCTION public.load_flare_generation(p_id uuid,p_token uuid,p_sources integer,p_bytes integer)
    RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
    DECLARE run public.flare_generation_runs; parent public.analysis_jobs; failure text; payload jsonb;
    BEGIN
        SELECT * INTO run FROM public.flare_generation_runs r WHERE r.id=p_id AND r.status='processing'
            AND r.lease_token=p_token AND r.lease_expires_at>clock_timestamp() FOR UPDATE;
        IF NOT FOUND THEN RETURN jsonb_build_object('error','lease_lost'); END IF;
        SELECT * INTO parent FROM public.analysis_jobs j WHERE j.id=run.analysis_job_id
            AND j.workspace_id=run.workspace_id AND j.status='completed';
        IF NOT FOUND THEN RETURN jsonb_build_object('error','source_invalid'); END IF;
        failure:=public.analysis_job_check(parent);
        IF failure IS NOT NULL THEN RETURN jsonb_build_object('error',failure); END IF;
        IF p_sources IS NULL OR p_bytes IS NULL OR p_sources<1 OR p_bytes<1 OR
            (SELECT count(*) FROM public.analysis_job_sources s WHERE s.job_id=parent.id)>p_sources OR
            (SELECT sum(octet_length(c.content)) FROM public.analysis_job_sources s JOIN public.chunks c
                ON(c.workspace_id,c.id)=(s.workspace_id,s.chunk_id) WHERE s.job_id=parent.id)>p_bytes THEN
            RETURN jsonb_build_object('error','invalid_request'); END IF;
        SELECT jsonb_build_object('analysis',parent.result,'evidence',jsonb_agg(
            jsonb_build_object('source_id',c.id::text,'content',c.content) ORDER BY s.ordinal)) INTO payload
            FROM public.analysis_job_sources s JOIN public.chunks c ON(c.workspace_id,c.id)=(s.workspace_id,s.chunk_id)
            WHERE s.job_id=parent.id;
        IF run.lease_expires_at<=clock_timestamp() THEN RETURN jsonb_build_object('error','lease_lost'); END IF;
        RETURN payload;
    END $$;

    CREATE FUNCTION public.finish_flare_generation(p_id uuid,p_token uuid,p_flares jsonb,p_metadata jsonb,
        p_error text,p_retry double precision) RETURNS text LANGUAGE plpgsql SECURITY DEFINER
        SET search_path=pg_catalog,public,pg_temp AS $$
    DECLARE run public.flare_generation_runs; parent public.analysis_jobs; failure text;
        next_status text; candidate jsonb; citation jsonb; canonical jsonb; fingerprint text; found_id uuid;
        ids uuid[]:='{}'::uuid[]; source_text text; n integer; position integer;
    BEGIN
        SELECT * INTO run FROM public.flare_generation_runs r WHERE r.id=p_id AND r.status='processing'
            AND r.lease_token=p_token AND r.lease_expires_at>clock_timestamp() FOR UPDATE;
        IF NOT FOUND THEN RETURN 'lease_lost'; END IF;
        SELECT * INTO parent FROM public.analysis_jobs j WHERE j.id=run.analysis_job_id
            AND j.workspace_id=run.workspace_id AND j.status='completed';
        IF NOT FOUND THEN failure:='source_invalid'; ELSE failure:=public.analysis_job_check(parent); END IF;
        IF failure IS NOT NULL THEN p_error:=failure;p_flares:=NULL;p_metadata:=NULL;p_retry:=NULL; END IF;
        IF p_error IS NULL THEN
            IF p_flares IS NULL OR jsonb_typeof(p_flares)<>'array' OR jsonb_array_length(p_flares)>3
                OR p_metadata IS NULL OR p_metadata->>'validation_outcome' IS DISTINCT FROM 'valid'
                OR p_metadata->>'finish_reason' IS DISTINCT FROM 'stop'
                OR p_metadata->>'configured_model' IS DISTINCT FROM p_metadata->>'returned_model'
                OR p_metadata->>'configured_model' IS NULL OR p_metadata->>'prompt_version' IS NULL
                OR p_metadata->>'schema_version' IS NULL THEN
                RAISE EXCEPTION 'Validated Flare result required' USING ERRCODE='22023'; END IF;
            FOR candidate IN SELECT value FROM jsonb_array_elements(p_flares) LOOP
                IF jsonb_typeof(candidate->'evidence') IS DISTINCT FROM 'array' THEN
                    RAISE EXCEPTION 'Invalid evidence' USING ERRCODE='22023'; END IF;
                n:=jsonb_array_length(candidate->'evidence');
                IF n NOT BETWEEN 1 AND 4 OR (SELECT count(DISTINCT e->>'source_id')
                    FROM jsonb_array_elements(candidate->'evidence') e)<>n THEN
                    RAISE EXCEPTION 'Invalid evidence count' USING ERRCODE='22023'; END IF;
                FOR citation IN SELECT value FROM jsonb_array_elements(candidate->'evidence') LOOP
                    SELECT c.content INTO source_text FROM public.analysis_job_sources s JOIN public.chunks c
                        ON(c.workspace_id,c.id)=(s.workspace_id,s.chunk_id)
                        WHERE s.job_id=parent.id AND c.id=(citation->>'source_id')::uuid;
                    IF NOT FOUND OR citation->>'quote' IS NULL OR length(citation->>'quote') NOT BETWEEN 1 AND 240
                        OR length(public.flare_normalize(citation->>'quote'))=0
                        OR strpos(public.flare_normalize(source_text),public.flare_normalize(citation->>'quote'))=0 THEN
                        RAISE EXCEPTION 'Invalid evidence quote' USING ERRCODE='22023'; END IF;
                END LOOP;
                SELECT jsonb_agg(jsonb_build_array((e->>'source_id')::uuid,public.flare_normalize(e->>'quote'))
                    ORDER BY (e->>'source_id')::uuid,public.flare_normalize(e->>'quote')) INTO canonical
                    FROM jsonb_array_elements(candidate->'evidence') e;
                fingerprint:=encode(sha256(convert_to(jsonb_build_array(run.workspace_id,run.generation_revision,
                    candidate->>'type',public.flare_normalize(candidate->>'title'),public.flare_normalize(candidate->>'statement'),
                    public.flare_normalize(candidate->>'action'),public.flare_normalize(candidate->>'reason'),canonical)::text,'UTF8')),'hex');
                INSERT INTO public.insights(workspace_id,flare_type,title,body,action,reason,source_analysis_job_id,
                    generation_revision,model,prompt_version,detector_schema_version,candidate_fingerprint)
                    VALUES(run.workspace_id,candidate->>'type',candidate->>'title',candidate->>'statement',candidate->>'action',
                        candidate->>'reason',parent.id,run.generation_revision,p_metadata->>'configured_model',
                        p_metadata->>'prompt_version',p_metadata->>'schema_version',fingerprint)
                    ON CONFLICT(workspace_id,candidate_fingerprint) DO NOTHING RETURNING id INTO found_id;
                IF found_id IS NOT NULL THEN
                    position:=0;
                    FOR citation IN SELECT value FROM jsonb_array_elements(candidate->'evidence') LOOP
                        INSERT INTO public.insight_sources(workspace_id,insight_id,chunk_id,quote,ordinal)
                            VALUES(run.workspace_id,found_id,(citation->>'source_id')::uuid,citation->>'quote',position);
                        position:=position+1;
                    END LOOP;
                ELSE
                    SELECT id INTO found_id FROM public.insights WHERE workspace_id=run.workspace_id AND candidate_fingerprint=fingerprint;
                END IF;
                IF NOT found_id=ANY(ids) THEN ids:=array_append(ids,found_id); END IF;
            END LOOP;
            next_status:='completed';
        ELSE
            next_status:='failed';
            IF p_error IN ('rate_limited','timeout','network','provider_transient','provider_server')
                AND run.attempts<run.max_attempts AND p_retry IS NOT NULL THEN
                IF p_retry<0 OR p_retry>='Infinity'::double precision THEN
                    RAISE EXCEPTION 'Invalid retry delay' USING ERRCODE='22023'; END IF;
                next_status:='pending';
            END IF;
        END IF;
        -- Roll back inserts as well if the lease expired during persistence.
        IF run.lease_expires_at<=clock_timestamp() THEN
            RAISE EXCEPTION 'Flare lease expired' USING ERRCODE='40001'; END IF;
        UPDATE public.flare_generation_runs SET status=next_status,last_error_code=p_error,metadata=p_metadata,
            flare_ids=CASE WHEN next_status='completed' THEN ids ELSE NULL END,
            available_at=CASE WHEN next_status='pending' THEN clock_timestamp()+make_interval(secs=>p_retry) ELSE available_at END,
            lease_owner=NULL,lease_token=NULL,lease_expires_at=NULL,updated_at=clock_timestamp(),
            completed_at=CASE WHEN next_status IN ('completed','failed') THEN clock_timestamp() ELSE NULL END WHERE id=run.id;
        RETURN next_status;
    END $$;
    """.replace("flare_job_executor", executor_role))
    signatures = {
        'flare_normalize(text)': None,
        'enqueue_flare_generation(uuid,text,integer)': 'flare_worker',
        'handoff_flare_generation()': None,
        'claim_flare_generation(uuid,integer)': 'flare_worker',
        'load_flare_generation(uuid,uuid,integer,integer)': 'flare_worker',
        'finish_flare_generation(uuid,uuid,jsonb,jsonb,text,double precision)': 'flare_worker',
    }
    for signature, role in signatures.items():
        op.execute(f'ALTER FUNCTION public.{signature} OWNER TO {executor_role}')
        op.execute(f'REVOKE ALL ON FUNCTION public.{signature} FROM PUBLIC')
        if role:
            op.execute(f'GRANT EXECUTE ON FUNCTION public.{signature} TO {role}')
    _replace_enqueue()


def _replace_enqueue():
    op.execute(r"""
        CREATE OR REPLACE FUNCTION public.enqueue_analysis_job(p_chunks uuid[], p_pipeline text, p_max_attempts integer)
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


def downgrade():
    raise RuntimeError("Flare persistence requires a reviewed restore plan")
