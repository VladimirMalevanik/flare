"""Daily workspace analysis schedules, immutable snapshots and DB-enforced quota."""

import os

from alembic import op


revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade():
    owner = "flare_owner" if os.getenv("FLARE_DATABASE_PROVIDER") == "yandex" else "flare_job_executor"
    op.execute(
        f"""
        CREATE TABLE public.analysis_schedules (
            workspace_id uuid PRIMARY KEY REFERENCES public.workspaces(id) ON DELETE CASCADE,
            enabled boolean NOT NULL DEFAULT false,
            timezone text NOT NULL DEFAULT 'UTC' CHECK (length(timezone) BETWEEN 1 AND 80),
            local_time time without time zone NOT NULL DEFAULT TIME '19:00',
            lead_minutes integer NOT NULL DEFAULT 30 CHECK (lead_minutes = 30),
            updated_by_user_id text NOT NULL REFERENCES public.auth_users(id),
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now()
        );

        CREATE TABLE public.analysis_cycles (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            workspace_id uuid NOT NULL REFERENCES public.workspaces(id) ON DELETE CASCADE,
            local_date date NOT NULL,
            mode text NOT NULL CHECK (mode IN ('manual','scheduled')),
            requested_by_user_id text NOT NULL REFERENCES public.auth_users(id),
            idempotency_key uuid NOT NULL,
            scheduled_for timestamptz NOT NULL,
            refresh_due_at timestamptz NOT NULL,
            refresh_status text NOT NULL DEFAULT 'scheduled'
                CHECK (refresh_status IN ('scheduled','refreshing','ready','failed')),
            refresh_attempts integer NOT NULL DEFAULT 0 CHECK (refresh_attempts BETWEEN 0 AND 3),
            refresh_lease_owner uuid,
            refresh_lease_token uuid,
            refresh_lease_expires_at timestamptz,
            snapshot_chunk_count integer NOT NULL DEFAULT 0 CHECK (snapshot_chunk_count BETWEEN 0 AND 100),
            analysis_run_id uuid UNIQUE REFERENCES public.analysis_runs(id) ON DELETE SET NULL,
            last_error_code text CHECK (last_error_code IN (
                'authorization_revoked','no_eligible_context','sync_failed','source_invalid','internal_error'
            )),
            created_at timestamptz NOT NULL DEFAULT now(),
            refreshed_at timestamptz,
            updated_at timestamptz NOT NULL DEFAULT now(),
            UNIQUE (workspace_id, id),
            CONSTRAINT analysis_cycles_workspace_local_date_key UNIQUE (workspace_id, local_date),
            CHECK ((refresh_status = 'refreshing') =
                (refresh_lease_owner IS NOT NULL AND refresh_lease_token IS NOT NULL
                 AND refresh_lease_expires_at IS NOT NULL)),
            CHECK (refresh_status = 'refreshing' OR
                (refresh_lease_owner IS NULL AND refresh_lease_token IS NULL
                 AND refresh_lease_expires_at IS NULL)),
            CHECK (refresh_status <> 'ready' OR
                (snapshot_chunk_count > 0 AND refreshed_at IS NOT NULL AND last_error_code IS NULL)),
            CHECK (refresh_status <> 'failed' OR last_error_code IS NOT NULL)
        );
        CREATE INDEX analysis_cycles_refresh_due_idx
            ON public.analysis_cycles(refresh_due_at, id)
            WHERE refresh_status IN ('scheduled','refreshing');
        CREATE INDEX analysis_cycles_run_due_idx
            ON public.analysis_cycles(scheduled_for, id)
            WHERE refresh_status = 'ready' AND analysis_run_id IS NULL;

        CREATE TABLE public.analysis_cycle_sources (
            workspace_id uuid NOT NULL,
            cycle_id uuid NOT NULL,
            chunk_id uuid NOT NULL,
            ordinal integer NOT NULL CHECK (ordinal >= 0),
            PRIMARY KEY (cycle_id, chunk_id),
            UNIQUE (cycle_id, ordinal),
            FOREIGN KEY (workspace_id, cycle_id)
                REFERENCES public.analysis_cycles(workspace_id, id) ON DELETE CASCADE,
            FOREIGN KEY (workspace_id, chunk_id)
                REFERENCES public.chunks(workspace_id, id)
        );

        ALTER TABLE public.analysis_schedules ENABLE ROW LEVEL SECURITY;
        ALTER TABLE public.analysis_schedules FORCE ROW LEVEL SECURITY;
        ALTER TABLE public.analysis_cycles ENABLE ROW LEVEL SECURITY;
        ALTER TABLE public.analysis_cycles FORCE ROW LEVEL SECURITY;
        ALTER TABLE public.analysis_cycle_sources ENABLE ROW LEVEL SECURITY;
        ALTER TABLE public.analysis_cycle_sources FORCE ROW LEVEL SECURITY;
        REVOKE ALL ON public.analysis_schedules, public.analysis_cycles,
            public.analysis_cycle_sources FROM PUBLIC;
        GRANT SELECT,INSERT,UPDATE ON public.analysis_schedules TO flare_app;
        GRANT SELECT ON public.analysis_cycles, public.analysis_cycle_sources TO flare_app;
        GRANT SELECT ON public.analysis_schedules TO {owner};
        GRANT SELECT,INSERT,UPDATE ON public.analysis_cycles TO {owner};
        GRANT SELECT,INSERT,DELETE ON public.analysis_cycle_sources TO {owner};
        GRANT INSERT ON public.activity_events TO {owner};

        CREATE POLICY schedule_member_access ON public.analysis_schedules TO flare_app
            USING (workspace_id = nullif(current_setting('app.workspace_id',true),'')::uuid
                AND EXISTS (SELECT 1 FROM public.workspace_members m
                    WHERE m.workspace_id=analysis_schedules.workspace_id
                      AND m.user_id=nullif(current_setting('app.user_id',true),'')))
            WITH CHECK (workspace_id = nullif(current_setting('app.workspace_id',true),'')::uuid
                AND updated_by_user_id=nullif(current_setting('app.user_id',true),'')
                AND EXISTS (SELECT 1 FROM public.workspace_members m
                    WHERE m.workspace_id=analysis_schedules.workspace_id
                      AND m.user_id=nullif(current_setting('app.user_id',true),'')
                      AND m.role IN ('owner','editor')));
        CREATE POLICY cycle_member_read ON public.analysis_cycles TO flare_app USING (
            workspace_id = nullif(current_setting('app.workspace_id',true),'')::uuid
            AND EXISTS (SELECT 1 FROM public.workspace_members m
                WHERE m.workspace_id=analysis_cycles.workspace_id
                  AND m.user_id=nullif(current_setting('app.user_id',true),'')));
        CREATE POLICY cycle_source_member_read ON public.analysis_cycle_sources TO flare_app USING (
            workspace_id = nullif(current_setting('app.workspace_id',true),'')::uuid
            AND EXISTS (SELECT 1 FROM public.workspace_members m
                WHERE m.workspace_id=analysis_cycle_sources.workspace_id
                  AND m.user_id=nullif(current_setting('app.user_id',true),'')));
        CREATE POLICY cycle_executor ON public.analysis_cycles TO {owner} USING(true) WITH CHECK(true);
        CREATE POLICY cycle_source_executor ON public.analysis_cycle_sources TO {owner} USING(true) WITH CHECK(true);
        CREATE POLICY schedule_executor ON public.analysis_schedules TO {owner} USING(true);
        CREATE POLICY activity_cycle_executor ON public.activity_events
            AS RESTRICTIVE FOR INSERT TO {owner} WITH CHECK (
                event_type IN ('analysis_refresh_started','analysis_refresh_completed','analysis_refresh_failed')
                AND target_type='analysis_cycle'
                AND EXISTS(SELECT 1 FROM public.analysis_cycles c
                    WHERE c.id=activity_events.target_id
                      AND c.workspace_id=activity_events.workspace_id
                      AND c.requested_by_user_id=activity_events.actor_id));

        CREATE FUNCTION public.guard_analysis_schedule() RETURNS trigger
        LANGUAGE plpgsql SET search_path=pg_catalog,public,pg_temp AS $$
        BEGIN
            IF NOT EXISTS(SELECT 1 FROM pg_timezone_names z WHERE z.name=NEW.timezone) THEN
                RAISE EXCEPTION 'Unknown IANA timezone' USING ERRCODE='22023';
            END IF;
            NEW.lead_minutes:=30;
            NEW.updated_at:=clock_timestamp();
            RETURN NEW;
        END $$;
        CREATE TRIGGER analysis_schedule_validate
            BEFORE INSERT OR UPDATE ON public.analysis_schedules
            FOR EACH ROW EXECUTE FUNCTION public.guard_analysis_schedule();
        """
    )
    op.execute(
        r"""
        CREATE FUNCTION public.start_daily_analysis_run(
            p_key uuid,p_chunks uuid[],p_selection text,p_pipeline text,p_generation text,
            p_attempts integer,p_sources integer,p_bytes integer)
        RETURNS uuid LANGUAGE plpgsql SECURITY DEFINER
        SET search_path=pg_catalog,public,pg_temp AS $$
        DECLARE wid uuid:=nullif(current_setting('app.workspace_id',true),'')::uuid;
            uid text:=nullif(current_setting('app.user_id',true),'');
            zone text; today date; result uuid; cycle_id uuid; job uuid; actual integer;
            now_at timestamptz:=clock_timestamp();
        BEGIN
            IF wid IS NULL OR uid IS NULL OR p_key IS NULL THEN
                RAISE EXCEPTION 'Authorization required' USING ERRCODE='42501'; END IF;
            SELECT r.id INTO result FROM public.analysis_runs r
             WHERE r.workspace_id=wid AND r.requested_by_user_id=uid AND r.idempotency_key=p_key;
            IF FOUND THEN RETURN result; END IF;
            PERFORM u.id FROM public.auth_users u WHERE u.id=uid AND NOT u.disabled FOR SHARE;
            IF NOT FOUND THEN RAISE EXCEPTION 'Authorization required' USING ERRCODE='42501'; END IF;
            PERFORM m.user_id FROM public.workspace_members m WHERE m.workspace_id=wid AND m.user_id=uid
                AND m.role IN ('owner','editor') FOR SHARE;
            IF NOT FOUND THEN RAISE EXCEPTION 'Write permission required' USING ERRCODE='42501'; END IF;
            SELECT coalesce(s.timezone,'UTC') INTO zone FROM (SELECT 1) seed
                LEFT JOIN public.analysis_schedules s ON s.workspace_id=wid;
            today := (now_at AT TIME ZONE zone)::date;
            PERFORM pg_advisory_xact_lock(hashtextextended(wid::text||today::text,0));
            SELECT c.analysis_run_id INTO result FROM public.analysis_cycles c
             WHERE c.workspace_id=wid AND c.local_date=today FOR UPDATE;
            IF FOUND THEN
                IF EXISTS(SELECT 1 FROM public.analysis_cycles c WHERE c.workspace_id=wid
                    AND c.local_date=today AND c.mode='manual' AND c.idempotency_key=p_key
                    AND c.analysis_run_id IS NOT NULL) THEN RETURN result; END IF;
                RAISE EXCEPTION 'Daily analysis limit reached'
                    USING ERRCODE='23505', CONSTRAINT='analysis_cycles_workspace_local_date_key';
            END IF;
            IF p_sources IS NULL OR p_sources NOT BETWEEN 1 AND 100 OR p_bytes IS NULL OR p_bytes<1
                OR p_chunks IS NULL OR cardinality(p_chunks) NOT BETWEEN 1 AND p_sources
                OR array_position(p_chunks,NULL) IS NOT NULL THEN
                RAISE EXCEPTION 'Invalid selection' USING ERRCODE='22023'; END IF;
            PERFORM d.id FROM public.documents d
                JOIN public.document_versions v ON(v.workspace_id,v.id)=(d.workspace_id,d.current_version_id)
                JOIN public.chunks c ON(c.workspace_id,c.document_version_id)=(v.workspace_id,v.id)
                WHERE c.id=ANY(p_chunks) AND d.workspace_id=wid ORDER BY d.id FOR SHARE OF d;
            SELECT count(*) INTO actual FROM public.documents d
                JOIN public.document_versions v ON(v.workspace_id,v.id)=(d.workspace_id,d.current_version_id)
                JOIN public.chunks c ON(c.workspace_id,c.document_version_id)=(v.workspace_id,v.id)
                WHERE c.id=ANY(p_chunks) AND d.workspace_id=wid AND d.deleted_at IS NULL
                  AND v.state='ready' AND d.source_type IN ('note','file','url','audio');
            IF actual<>cardinality(p_chunks) OR
                (SELECT sum(octet_length(content)) FROM public.chunks
                  WHERE workspace_id=wid AND id=ANY(p_chunks))>p_bytes THEN
                RAISE EXCEPTION 'Selection changed' USING ERRCODE='22023'; END IF;
            INSERT INTO public.analysis_cycles(workspace_id,local_date,mode,requested_by_user_id,
                idempotency_key,scheduled_for,refresh_due_at,refresh_status,snapshot_chunk_count,refreshed_at)
            VALUES(wid,today,'manual',uid,p_key,now_at,now_at,'ready',actual,now_at)
            RETURNING id INTO cycle_id;
            INSERT INTO public.analysis_cycle_sources(workspace_id,cycle_id,chunk_id,ordinal)
                SELECT wid,cycle_id,u.chunk_id,(u.ordinality-1)::integer
                FROM unnest(p_chunks) WITH ORDINALITY AS u(chunk_id,ordinality);
            job:=public.enqueue_analysis_job(p_chunks,p_pipeline,p_attempts,p_key);
            INSERT INTO public.analysis_runs(workspace_id,requested_by_user_id,idempotency_key,
                analysis_job_id,selection_revision,pipeline_revision,generation_revision,selected_chunk_count)
            VALUES(wid,uid,p_key,job,p_selection,p_pipeline,p_generation,actual) RETURNING id INTO result;
            UPDATE public.analysis_cycles SET analysis_run_id=result,updated_at=now_at WHERE id=cycle_id;
            RETURN result;
        END $$;

        -- Keep the legacy capability name safe as well: no caller holding the
        -- restricted API role can bypass the workspace/day uniqueness rule.
        CREATE OR REPLACE FUNCTION public.start_analysis_run(
            p_key uuid,p_chunks uuid[],p_selection text,p_pipeline text,p_generation text,
            p_attempts integer,p_sources integer,p_bytes integer)
        RETURNS uuid LANGUAGE sql SECURITY DEFINER
        SET search_path=pg_catalog,public,pg_temp AS $$
            SELECT public.start_daily_analysis_run(p_key,p_chunks,p_selection,p_pipeline,
                p_generation,p_attempts,p_sources,p_bytes)
        $$;

        CREATE FUNCTION public.materialize_analysis_cycles(p_now timestamptz,p_limit integer)
        RETURNS integer LANGUAGE plpgsql SECURITY DEFINER
        SET search_path=pg_catalog,public,pg_temp AS $$
        DECLARE inserted integer;
        BEGIN
            IF p_now IS NULL OR p_limit IS NULL OR p_limit NOT BETWEEN 1 AND 1000 THEN
                RAISE EXCEPTION 'Invalid scheduler request' USING ERRCODE='22023'; END IF;
            WITH candidates AS MATERIALIZED (
                SELECT s.workspace_id,s.updated_by_user_id,
                    dates.local_date,
                    ((dates.local_date+s.local_time) AT TIME ZONE s.timezone) AS scheduled_for
                FROM public.analysis_schedules s
                CROSS JOIN LATERAL (
                    VALUES ((p_now AT TIME ZONE s.timezone)::date),
                           (((p_now AT TIME ZONE s.timezone)::date+1)::date)
                ) dates(local_date)
                WHERE s.enabled
                  AND EXISTS(SELECT 1 FROM pg_timezone_names z WHERE z.name=s.timezone)
            ), due AS (
                SELECT * FROM candidates c
                WHERE c.scheduled_for-make_interval(mins=>30)<=p_now
                  AND c.scheduled_for-make_interval(mins=>30)>=(
                      SELECT s.updated_at FROM public.analysis_schedules s
                      WHERE s.workspace_id=c.workspace_id)
                  AND c.scheduled_for>=p_now-interval '1 day'
                ORDER BY c.scheduled_for,c.workspace_id LIMIT p_limit
            )
            INSERT INTO public.analysis_cycles(workspace_id,local_date,mode,requested_by_user_id,
                idempotency_key,scheduled_for,refresh_due_at)
            SELECT workspace_id,local_date,'scheduled',updated_by_user_id,gen_random_uuid(),
                scheduled_for,scheduled_for-make_interval(mins=>30) FROM due
            ON CONFLICT(workspace_id,local_date) DO NOTHING;
            GET DIAGNOSTICS inserted=ROW_COUNT;
            RETURN inserted;
        END $$;

        CREATE FUNCTION public.claim_analysis_cycle_refresh(p_owner uuid,p_lease_seconds integer)
        RETURNS TABLE(cycle_id uuid,workspace_id uuid,requested_by_user_id text,lease_token uuid,
            lease_expires_at timestamptz,attempts integer)
        LANGUAGE plpgsql SECURITY DEFINER SET search_path=pg_catalog,public,pg_temp AS $$
        DECLARE selected public.analysis_cycles; token uuid:=gen_random_uuid(); now_at timestamptz:=clock_timestamp();
        BEGIN
            IF p_owner IS NULL OR p_lease_seconds IS NULL OR p_lease_seconds NOT BETWEEN 60 AND 3600 THEN
                RAISE EXCEPTION 'Invalid lease' USING ERRCODE='22023'; END IF;
            UPDATE public.analysis_cycles c SET refresh_status='failed',last_error_code='sync_failed',
                refresh_lease_owner=NULL,refresh_lease_token=NULL,refresh_lease_expires_at=NULL,updated_at=now_at
             WHERE c.refresh_status='refreshing' AND c.refresh_lease_expires_at<=now_at
               AND c.refresh_attempts>=3;
            UPDATE public.analysis_cycles c SET refresh_status='scheduled',last_error_code=NULL,
                refresh_lease_owner=NULL,refresh_lease_token=NULL,refresh_lease_expires_at=NULL,updated_at=now_at
             WHERE c.refresh_status='refreshing' AND c.refresh_lease_expires_at<=now_at
               AND c.refresh_attempts<3;
            SELECT * INTO selected FROM public.analysis_cycles c
             WHERE c.refresh_status='scheduled' AND c.refresh_due_at<=now_at
               AND c.refresh_attempts<3
             ORDER BY c.refresh_due_at,c.id FOR UPDATE SKIP LOCKED LIMIT 1;
            IF NOT FOUND THEN RETURN; END IF;
            UPDATE public.analysis_cycles c SET refresh_status='refreshing',refresh_attempts=c.refresh_attempts+1,
                refresh_lease_owner=p_owner,refresh_lease_token=token,
                refresh_lease_expires_at=now_at+make_interval(secs=>p_lease_seconds),updated_at=now_at
             WHERE c.id=selected.id;
            PERFORM set_config('app.workspace_id',selected.workspace_id::text,true);
            PERFORM set_config('app.user_id',selected.requested_by_user_id,true);
            BEGIN
                INSERT INTO public.activity_events(workspace_id,actor_id,event_type,target_type,target_id,metadata)
                VALUES(selected.workspace_id,selected.requested_by_user_id,'analysis_refresh_started',
                    'analysis_cycle',selected.id,jsonb_build_object('attempt',selected.refresh_attempts+1));
            EXCEPTION WHEN OTHERS THEN NULL;
            END;
            RETURN QUERY SELECT selected.id,selected.workspace_id,selected.requested_by_user_id,token,
                now_at+make_interval(secs=>p_lease_seconds),selected.refresh_attempts+1;
        END $$;

        CREATE FUNCTION public.load_analysis_cycle_candidates(p_cycle uuid,p_token uuid,
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
            IF NOT EXISTS(SELECT 1 FROM public.auth_users u JOIN public.workspace_members m ON m.user_id=u.id
                WHERE u.id=cycle.requested_by_user_id AND NOT u.disabled
                  AND m.workspace_id=cycle.workspace_id AND m.role IN ('owner','editor')) THEN
                RETURN jsonb_build_object('error','authorization_revoked'); END IF;
            SELECT jsonb_agg(jsonb_build_object('id',q.id,'content',q.content) ORDER BY q.row_order)
            INTO candidates FROM (
                SELECT c.id,c.content,row_number() OVER(ORDER BY d.created_at DESC,d.id DESC,c.ordinal,c.id) row_order
                FROM (SELECT d.* FROM public.documents d
                    WHERE d.workspace_id=cycle.workspace_id AND d.deleted_at IS NULL
                      AND d.source_type IN ('note','file','url','audio')
                    ORDER BY d.created_at DESC,d.id DESC LIMIT 200) d
                JOIN public.document_versions v ON(v.workspace_id,v.id)=(d.workspace_id,d.current_version_id)
                CROSS JOIN LATERAL (
                    SELECT c.id,c.content,c.ordinal FROM public.chunks c
                    WHERE (c.workspace_id,c.document_version_id)=(v.workspace_id,v.id)
                      AND octet_length(c.content)<=p_max_bytes
                    ORDER BY c.ordinal,c.id LIMIT p_max_sources
                ) c
                WHERE v.state='ready'
            ) q;
            RETURN jsonb_build_object('candidates',coalesce(candidates,'[]'::jsonb));
        END $$;

        CREATE FUNCTION public.finish_analysis_cycle_refresh(p_cycle uuid,p_token uuid,p_chunks uuid[],
            p_error text,p_retry_seconds double precision)
        RETURNS text LANGUAGE plpgsql SECURITY DEFINER
        SET search_path=pg_catalog,public,pg_temp AS $$
        DECLARE cycle public.analysis_cycles; actual integer; next_status text; now_at timestamptz:=clock_timestamp();
        BEGIN
            SELECT * INTO cycle FROM public.analysis_cycles c WHERE c.id=p_cycle
                AND c.refresh_status='refreshing' AND c.refresh_lease_token=p_token
                AND c.refresh_lease_expires_at>now_at FOR UPDATE;
            IF NOT FOUND THEN RETURN 'lease_lost'; END IF;
            IF p_error IS NOT NULL THEN
                IF p_error NOT IN ('authorization_revoked','no_eligible_context','sync_failed','source_invalid','internal_error') THEN
                    RAISE EXCEPTION 'Invalid refresh error' USING ERRCODE='22023'; END IF;
                IF p_retry_seconds IS NOT NULL AND
                    (p_retry_seconds<0 OR p_retry_seconds>='Infinity'::double precision
                     OR p_retry_seconds='NaN'::double precision) THEN
                    RAISE EXCEPTION 'Invalid retry delay' USING ERRCODE='22023'; END IF;
                next_status:=CASE WHEN p_retry_seconds IS NOT NULL AND p_retry_seconds>=0
                    AND cycle.refresh_attempts<3 THEN 'scheduled' ELSE 'failed' END;
                UPDATE public.analysis_cycles SET refresh_status=next_status,last_error_code=p_error,
                    refresh_due_at=CASE WHEN next_status='scheduled' THEN now_at+make_interval(secs=>p_retry_seconds)
                        ELSE refresh_due_at END,
                    refresh_lease_owner=NULL,refresh_lease_token=NULL,refresh_lease_expires_at=NULL,updated_at=now_at
                    WHERE id=cycle.id;
                PERFORM set_config('app.workspace_id',cycle.workspace_id::text,true);
                PERFORM set_config('app.user_id',cycle.requested_by_user_id,true);
                BEGIN
                    INSERT INTO public.activity_events(workspace_id,actor_id,event_type,target_type,target_id,metadata)
                    VALUES(cycle.workspace_id,cycle.requested_by_user_id,'analysis_refresh_failed',
                        'analysis_cycle',cycle.id,jsonb_build_object('error_code',p_error,'attempt',cycle.refresh_attempts));
                EXCEPTION WHEN OTHERS THEN NULL;
                END;
                RETURN next_status;
            END IF;
            IF p_chunks IS NULL OR cardinality(p_chunks) NOT BETWEEN 1 AND 100
                OR array_position(p_chunks,NULL) IS NOT NULL
                OR cardinality(ARRAY(SELECT DISTINCT x.chunk_id
                    FROM unnest(p_chunks) AS x(chunk_id)))<>cardinality(p_chunks) THEN
                RAISE EXCEPTION 'Invalid snapshot' USING ERRCODE='22023'; END IF;
            PERFORM d.id FROM public.documents d
                JOIN public.document_versions v ON(v.workspace_id,v.id)=(d.workspace_id,d.current_version_id)
                JOIN public.chunks c ON(c.workspace_id,c.document_version_id)=(v.workspace_id,v.id)
                WHERE d.workspace_id=cycle.workspace_id AND d.deleted_at IS NULL AND v.state='ready'
                  AND c.id=ANY(p_chunks) ORDER BY d.id FOR SHARE OF d;
            SELECT count(*) INTO actual FROM public.documents d
                JOIN public.document_versions v ON(v.workspace_id,v.id)=(d.workspace_id,d.current_version_id)
                JOIN public.chunks c ON(c.workspace_id,c.document_version_id)=(v.workspace_id,v.id)
                WHERE d.workspace_id=cycle.workspace_id AND d.deleted_at IS NULL AND v.state='ready'
                  AND d.source_type IN ('note','file','url','audio') AND c.id=ANY(p_chunks);
            IF actual<>cardinality(p_chunks) THEN
                next_status:=CASE WHEN cycle.refresh_attempts<3 THEN 'scheduled' ELSE 'failed' END;
                UPDATE public.analysis_cycles SET refresh_status=next_status,last_error_code='source_invalid',
                    refresh_due_at=CASE WHEN next_status='scheduled' THEN now_at+interval '5 seconds'
                        ELSE refresh_due_at END,refresh_lease_owner=NULL,refresh_lease_token=NULL,
                    refresh_lease_expires_at=NULL,updated_at=now_at WHERE id=cycle.id;
                RETURN next_status;
            END IF;
            INSERT INTO public.analysis_cycle_sources(workspace_id,cycle_id,chunk_id,ordinal)
                SELECT cycle.workspace_id,cycle.id,u.chunk_id,(u.ordinality-1)::integer
                FROM unnest(p_chunks) WITH ORDINALITY AS u(chunk_id,ordinality);
            UPDATE public.analysis_cycles SET refresh_status='ready',snapshot_chunk_count=actual,
                refreshed_at=now_at,last_error_code=NULL,refresh_lease_owner=NULL,refresh_lease_token=NULL,
                refresh_lease_expires_at=NULL,updated_at=now_at WHERE id=cycle.id;
            PERFORM set_config('app.workspace_id',cycle.workspace_id::text,true);
            PERFORM set_config('app.user_id',cycle.requested_by_user_id,true);
            BEGIN
                INSERT INTO public.activity_events(workspace_id,actor_id,event_type,target_type,target_id,metadata)
                VALUES(cycle.workspace_id,cycle.requested_by_user_id,'analysis_refresh_completed',
                    'analysis_cycle',cycle.id,jsonb_build_object('source_count',actual));
            EXCEPTION WHEN OTHERS THEN NULL;
            END;
            RETURN 'ready';
        END $$;

        CREATE FUNCTION public.enqueue_due_analysis_cycles(p_pipeline text,p_generation text,
            p_attempts integer,p_now timestamptz,p_limit integer)
        RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER
        SET search_path=pg_catalog,public,pg_temp AS $$
        DECLARE cycle public.analysis_cycles; chunks uuid[]; job uuid; run_id uuid;
            result jsonb:='[]'::jsonb; processed integer:=0;
        BEGIN
            IF p_attempts IS NULL OR p_attempts NOT BETWEEN 1 AND 10 OR p_now IS NULL
                OR p_limit IS NULL OR p_limit NOT BETWEEN 1 AND 100
                OR p_pipeline IS NULL OR length(p_pipeline) NOT BETWEEN 1 AND 160
                OR p_generation IS NULL OR length(p_generation) NOT BETWEEN 1 AND 160 THEN
                RAISE EXCEPTION 'Invalid scheduler request' USING ERRCODE='22023'; END IF;
            FOR cycle IN SELECT * FROM public.analysis_cycles c
                WHERE c.refresh_status='ready' AND c.analysis_run_id IS NULL AND c.scheduled_for<=p_now
                ORDER BY c.scheduled_for,c.id FOR UPDATE SKIP LOCKED
            LOOP
                EXIT WHEN processed>=p_limit;
                IF NOT EXISTS(SELECT 1 FROM public.auth_users u JOIN public.workspace_members m ON m.user_id=u.id
                    WHERE u.id=cycle.requested_by_user_id AND NOT u.disabled
                      AND m.workspace_id=cycle.workspace_id AND m.role IN ('owner','editor')) THEN
                    UPDATE public.analysis_cycles SET refresh_status='failed',last_error_code='authorization_revoked',
                        updated_at=clock_timestamp() WHERE id=cycle.id;
                    CONTINUE;
                END IF;
                SELECT array_agg(s.chunk_id ORDER BY s.ordinal) INTO chunks
                  FROM public.analysis_cycle_sources s WHERE s.cycle_id=cycle.id;
                IF chunks IS NULL OR cardinality(chunks)<>cycle.snapshot_chunk_count THEN
                    UPDATE public.analysis_cycles SET refresh_status='failed',last_error_code='source_invalid',
                        updated_at=clock_timestamp() WHERE id=cycle.id;
                    CONTINUE;
                END IF;
                PERFORM set_config('app.workspace_id',cycle.workspace_id::text,true);
                PERFORM set_config('app.user_id',cycle.requested_by_user_id,true);
                BEGIN
                    job:=public.enqueue_analysis_job(chunks,p_pipeline,p_attempts,cycle.idempotency_key);
                    INSERT INTO public.analysis_runs(workspace_id,requested_by_user_id,idempotency_key,
                        analysis_job_id,selection_revision,pipeline_revision,generation_revision,selected_chunk_count)
                    VALUES(cycle.workspace_id,cycle.requested_by_user_id,cycle.idempotency_key,job,
                        'daily-snapshot-v1',p_pipeline,p_generation,cycle.snapshot_chunk_count)
                    RETURNING id INTO run_id;
                EXCEPTION
                    WHEN insufficient_privilege OR invalid_parameter_value THEN
                        UPDATE public.analysis_cycles SET refresh_status='failed',last_error_code='source_invalid',
                            updated_at=clock_timestamp() WHERE id=cycle.id;
                        CONTINUE;
                    WHEN OTHERS THEN
                        UPDATE public.analysis_cycles SET refresh_status='failed',last_error_code='internal_error',
                            updated_at=clock_timestamp() WHERE id=cycle.id;
                        CONTINUE;
                END;
                UPDATE public.analysis_cycles SET analysis_run_id=run_id,updated_at=clock_timestamp()
                    WHERE id=cycle.id;
                result:=result||jsonb_build_array(jsonb_build_object('cycle_id',cycle.id,'run_id',run_id));
                processed:=processed+1;
            END LOOP;
            RETURN result;
        END $$;
        """
    )
    signatures = {
        "start_daily_analysis_run(uuid,uuid[],text,text,text,integer,integer,integer)": "flare_app",
        "materialize_analysis_cycles(timestamp with time zone,integer)": "flare_worker",
        "claim_analysis_cycle_refresh(uuid,integer)": "flare_worker",
        "load_analysis_cycle_candidates(uuid,uuid,integer,integer)": "flare_worker",
        "finish_analysis_cycle_refresh(uuid,uuid,uuid[],text,double precision)": "flare_worker",
        "enqueue_due_analysis_cycles(text,text,integer,timestamp with time zone,integer)": "flare_worker",
    }
    for signature, runtime_role in signatures.items():
        op.execute(f"ALTER FUNCTION public.{signature} OWNER TO {owner}")
        op.execute(f"REVOKE ALL ON FUNCTION public.{signature} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION public.{signature} TO {runtime_role}")
    op.execute(
        """
        DO $$ DECLARE constraint_name text;
        BEGIN
            SELECT c.conname INTO constraint_name FROM pg_constraint c
            WHERE c.conrelid='public.activity_events'::regclass AND c.contype='c'
              AND pg_get_constraintdef(c.oid) LIKE '%event_type%' LIMIT 1;
            IF constraint_name IS NOT NULL THEN
                EXECUTE format('ALTER TABLE public.activity_events DROP CONSTRAINT %I',constraint_name);
            END IF;
            ALTER TABLE public.activity_events ADD CONSTRAINT activity_events_event_type_check CHECK (
                event_type IN ('capture_started','capture_submitted','capture_file_attached',
                'capture_voice_started','capture_voice_stopped','item_created','item_updated',
                'source_replaced','item_deleted','item_viewed',
                'flare_viewed','queue_health_requested','queue_maintenance_run','import_started',
                'import_completed','import_failed','analysis_requested','schedule_updated',
                'analysis_refresh_started','analysis_refresh_completed','analysis_refresh_failed'));
        END $$;
        """
    )


def downgrade():
    raise RuntimeError("Daily analysis snapshots contain customer evidence; restore from backup instead.")
