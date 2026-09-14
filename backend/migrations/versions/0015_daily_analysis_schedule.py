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

        -- Queue/run retention may remove the detailed cycle, but it must never
        -- reopen a consumed local day (including a 25-hour DST fall-back day).
        -- This compact tombstone is intentionally independent of job/run FKs.
        CREATE TABLE public.analysis_daily_quotas (
            workspace_id uuid NOT NULL REFERENCES public.workspaces(id) ON DELETE CASCADE,
            local_date date NOT NULL,
            mode text NOT NULL CHECK (mode IN ('manual','scheduled')),
            scheduled_for timestamptz NOT NULL,
            created_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (workspace_id, local_date)
        );
        CREATE INDEX analysis_daily_quotas_scheduled_idx
            ON public.analysis_daily_quotas(workspace_id, scheduled_for DESC);

        -- Deployments upgrading from 0014 may already have analysis runs.  At
        -- that point schedules did not exist, so UTC is the only stable day
        -- boundary we can apply.  Preserve one consumed slot per historical
        -- workspace/day before the new quota enforcement becomes reachable.
        INSERT INTO public.analysis_daily_quotas(
            workspace_id, local_date, mode, scheduled_for, created_at
        )
        SELECT DISTINCT ON (
                   r.workspace_id, (r.created_at AT TIME ZONE 'UTC')::date
               )
               r.workspace_id,
               (r.created_at AT TIME ZONE 'UTC')::date,
               'manual',
               r.created_at,
               r.created_at
          FROM public.analysis_runs r
         ORDER BY r.workspace_id,
                  (r.created_at AT TIME ZONE 'UTC')::date,
                  r.created_at DESC,
                  r.id DESC
        ON CONFLICT (workspace_id, local_date) DO NOTHING;

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
            -- Detailed cycle/snapshot rows follow queue retention; the
            -- independent daily quota tombstone above preserves consumption.
            analysis_run_id uuid UNIQUE REFERENCES public.analysis_runs(id) ON DELETE CASCADE,
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
        CREATE INDEX analysis_cycles_workspace_scheduled_idx
            ON public.analysis_cycles(workspace_id, scheduled_for DESC, id DESC);

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
        ALTER TABLE public.analysis_daily_quotas ENABLE ROW LEVEL SECURITY;
        ALTER TABLE public.analysis_daily_quotas FORCE ROW LEVEL SECURITY;
        ALTER TABLE public.analysis_cycles ENABLE ROW LEVEL SECURITY;
        ALTER TABLE public.analysis_cycles FORCE ROW LEVEL SECURITY;
        ALTER TABLE public.analysis_cycle_sources ENABLE ROW LEVEL SECURITY;
        ALTER TABLE public.analysis_cycle_sources FORCE ROW LEVEL SECURITY;
        REVOKE ALL ON public.analysis_schedules, public.analysis_daily_quotas,
            public.analysis_cycles,
            public.analysis_cycle_sources FROM PUBLIC;
        -- Runtime writes go through set_analysis_schedule(); direct writes
        -- would bypass reconciliation with already materialized cycles.
        GRANT SELECT ON public.analysis_schedules TO flare_app;
        GRANT SELECT ON public.analysis_daily_quotas TO flare_app;
        GRANT SELECT ON public.analysis_cycles, public.analysis_cycle_sources TO flare_app;
        GRANT SELECT,INSERT,UPDATE ON public.analysis_schedules TO {owner};
        GRANT SELECT,INSERT,DELETE ON public.analysis_daily_quotas TO {owner};
        GRANT SELECT,INSERT,UPDATE,DELETE ON public.analysis_cycles TO {owner};
        GRANT SELECT,INSERT,DELETE ON public.analysis_cycle_sources TO {owner};
        GRANT SELECT,INSERT,DELETE ON public.activity_events TO {owner};
        CREATE INDEX activity_events_workspace_actor_created_idx
            ON public.activity_events(workspace_id,actor_id,created_at DESC);

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
        CREATE POLICY quota_member_read ON public.analysis_daily_quotas TO flare_app USING (
            workspace_id = nullif(current_setting('app.workspace_id',true),'')::uuid
            AND EXISTS (SELECT 1 FROM public.workspace_members m
                WHERE m.workspace_id=analysis_daily_quotas.workspace_id
                  AND m.user_id=nullif(current_setting('app.user_id',true),'')));
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
        CREATE POLICY quota_executor ON public.analysis_daily_quotas TO {owner}
            USING(true) WITH CHECK(true);
        CREATE POLICY cycle_source_executor ON public.analysis_cycle_sources TO {owner} USING(true) WITH CHECK(true);
        CREATE POLICY schedule_executor ON public.analysis_schedules TO {owner} USING(true);
        CREATE POLICY activity_cycle_executor ON public.activity_events
            AS RESTRICTIVE FOR INSERT TO {owner} WITH CHECK (
                (
                    event_type IN ('analysis_refresh_started','analysis_refresh_completed','analysis_refresh_failed')
                    AND target_type='analysis_cycle'
                    AND EXISTS(SELECT 1 FROM public.analysis_cycles c
                        WHERE c.id=activity_events.target_id
                          AND c.workspace_id=activity_events.workspace_id
                          AND c.requested_by_user_id=activity_events.actor_id)
                ) OR (
                    event_type='analysis_requested'
                    AND target_type='analysis_run'
                    AND EXISTS(SELECT 1 FROM public.analysis_cycles c
                        WHERE c.analysis_run_id=activity_events.target_id
                          AND c.workspace_id=activity_events.workspace_id
                          AND c.requested_by_user_id=activity_events.actor_id
                          AND activity_events.metadata=jsonb_build_object('mode',c.mode))
                ));

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

        CREATE FUNCTION public.guard_analysis_cycle_quota() RETURNS trigger
        LANGUAGE plpgsql SET search_path=pg_catalog,public,pg_temp AS $$
        BEGIN
            INSERT INTO public.analysis_daily_quotas(
                workspace_id,local_date,mode,scheduled_for)
            VALUES(NEW.workspace_id,NEW.local_date,NEW.mode,NEW.scheduled_for)
            ON CONFLICT(workspace_id,local_date) DO NOTHING;
            IF NOT EXISTS(SELECT 1 FROM public.analysis_daily_quotas q
                WHERE q.workspace_id=NEW.workspace_id AND q.local_date=NEW.local_date
                  AND q.mode=NEW.mode AND q.scheduled_for=NEW.scheduled_for) THEN
                RAISE EXCEPTION 'Daily quota conflicts with analysis cycle'
                    USING ERRCODE='23505',
                          CONSTRAINT='analysis_daily_quotas_pkey';
            END IF;
            RETURN NEW;
        END $$;
        CREATE TRIGGER analysis_cycle_quota_guard
            BEFORE INSERT ON public.analysis_cycles
            FOR EACH ROW EXECUTE FUNCTION public.guard_analysis_cycle_quota();
        """
    )
    op.execute(
        r"""
        CREATE FUNCTION public.set_analysis_schedule(
            p_enabled boolean,p_timezone text,p_local_time time without time zone)
        RETURNS TABLE(enabled boolean,timezone text,local_time time without time zone,
            lead_minutes integer,updated_at timestamptz)
        LANGUAGE plpgsql SECURITY DEFINER
        SET search_path=pg_catalog,public,pg_temp AS $$
        DECLARE wid uuid:=nullif(current_setting('app.workspace_id',true),'')::uuid;
            uid text:=nullif(current_setting('app.user_id',true),'');
            previous public.analysis_schedules; had_previous boolean:=false;
        BEGIN
            IF wid IS NULL OR uid IS NULL OR p_enabled IS NULL OR p_timezone IS NULL
                OR p_local_time IS NULL OR extract(second FROM p_local_time)<>0 THEN
                RAISE EXCEPTION 'Invalid schedule request' USING ERRCODE='22023'; END IF;
            PERFORM u.id FROM public.auth_users u WHERE u.id=uid AND NOT u.disabled FOR SHARE;
            IF NOT FOUND THEN RAISE EXCEPTION 'Authorization required' USING ERRCODE='42501'; END IF;
            PERFORM m.user_id FROM public.workspace_members m
                WHERE m.workspace_id=wid AND m.user_id=uid AND m.role IN ('owner','editor') FOR SHARE;
            IF NOT FOUND THEN RAISE EXCEPTION 'Write permission required' USING ERRCODE='42501'; END IF;
            IF length(p_timezone) NOT BETWEEN 1 AND 80
                OR NOT EXISTS(SELECT 1 FROM pg_timezone_names z WHERE z.name=p_timezone) THEN
                RAISE EXCEPTION 'Unknown IANA timezone' USING ERRCODE='22023'; END IF;

            -- One workspace lock serializes schedule changes with both manual
            -- requests and automatic cycle materialization, including timezone
            -- changes that cross a calendar boundary.
            PERFORM pg_advisory_xact_lock(hashtextextended(wid::text,0));
            SELECT * INTO previous FROM public.analysis_schedules s
                WHERE s.workspace_id=wid FOR UPDATE;
            had_previous:=FOUND;

            INSERT INTO public.analysis_schedules(
                workspace_id,enabled,timezone,local_time,lead_minutes,updated_by_user_id)
            VALUES(wid,p_enabled,p_timezone,p_local_time,30,uid)
            ON CONFLICT(workspace_id) DO UPDATE SET enabled=excluded.enabled,
                timezone=excluded.timezone,local_time=excluded.local_time,lead_minutes=30,
                updated_by_user_id=excluded.updated_by_user_id;

            -- A change inside the preparation window cancels only automatic
            -- work that has not produced a durable analysis run.  Completed,
            -- failed and already-enqueued daily slots remain immutable.
            IF had_previous AND (
                previous.enabled IS DISTINCT FROM p_enabled
                OR previous.timezone IS DISTINCT FROM p_timezone
                OR previous.local_time IS DISTINCT FROM p_local_time) THEN
                WITH cancelled AS (
                    DELETE FROM public.analysis_cycles c
                     WHERE c.workspace_id=wid AND c.mode='scheduled'
                       AND c.analysis_run_id IS NULL
                       AND c.refresh_status IN ('scheduled','refreshing','ready')
                     RETURNING c.workspace_id,c.local_date
                )
                DELETE FROM public.analysis_daily_quotas q USING cancelled c
                 WHERE (q.workspace_id,q.local_date)=(c.workspace_id,c.local_date);
            END IF;

            RETURN QUERY SELECT s.enabled,s.timezone,s.local_time,s.lead_minutes,s.updated_at
                FROM public.analysis_schedules s WHERE s.workspace_id=wid;
        END $$;

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
            PERFORM u.id FROM public.auth_users u WHERE u.id=uid AND NOT u.disabled FOR SHARE;
            IF NOT FOUND THEN RAISE EXCEPTION 'Authorization required' USING ERRCODE='42501'; END IF;
            PERFORM m.user_id FROM public.workspace_members m WHERE m.workspace_id=wid AND m.user_id=uid
                AND m.role IN ('owner','editor') FOR SHARE;
            IF NOT FOUND THEN RAISE EXCEPTION 'Write permission required' USING ERRCODE='42501'; END IF;
            PERFORM pg_advisory_xact_lock(hashtextextended(wid::text,0));
            SELECT r.id INTO result FROM public.analysis_runs r
             WHERE r.workspace_id=wid AND r.requested_by_user_id=uid AND r.idempotency_key=p_key;
            IF FOUND THEN RETURN result; END IF;
            SELECT coalesce(s.timezone,'UTC') INTO zone FROM (SELECT 1) seed
                LEFT JOIN public.analysis_schedules s ON s.workspace_id=wid;
            today := (now_at AT TIME ZONE zone)::date;
            SELECT c.analysis_run_id INTO result FROM public.analysis_cycles c
             WHERE c.workspace_id=wid AND c.local_date=today FOR UPDATE;
            IF FOUND THEN
                IF EXISTS(SELECT 1 FROM public.analysis_cycles c WHERE c.workspace_id=wid
                    AND c.local_date=today AND c.mode='manual' AND c.idempotency_key=p_key
                    AND c.analysis_run_id IS NOT NULL) THEN RETURN result; END IF;
                RAISE EXCEPTION 'Daily analysis limit reached'
                    USING ERRCODE='23505', CONSTRAINT='analysis_cycles_workspace_local_date_key';
            END IF;
            IF EXISTS(SELECT 1 FROM public.analysis_daily_quotas q
                WHERE q.workspace_id=wid AND q.local_date=today) THEN
                RAISE EXCEPTION 'Daily analysis limit reached'
                    USING ERRCODE='23505', CONSTRAINT='analysis_cycles_workspace_local_date_key';
            END IF;
            -- Keep the user-selected local-calendar rule while closing the
            -- immediate timezone-flip bypass.  Twenty hours is below the
            -- shortest normal DST daily cadence (23h), yet blocks a second
            -- run moments after the prior cycle's promised run instant.
            IF EXISTS(SELECT 1 FROM public.analysis_daily_quotas q
                WHERE q.workspace_id=wid AND q.scheduled_for>now_at-interval '20 hours') THEN
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
            INSERT INTO public.analysis_daily_quotas(workspace_id,local_date,mode,scheduled_for)
                VALUES(wid,today,'manual',now_at);
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
            INSERT INTO public.activity_events(
                workspace_id,actor_id,event_type,target_type,target_id,metadata)
            VALUES(wid,uid,'analysis_requested','analysis_run',result,
                jsonb_build_object('mode','manual'));
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
        DECLARE candidate record; inserted integer:=0;
            server_now timestamptz:=clock_timestamp();
        BEGIN
            IF p_now IS NULL OR p_limit IS NULL OR p_limit NOT BETWEEN 1 AND 1000 THEN
                RAISE EXCEPTION 'Invalid scheduler request' USING ERRCODE='22023'; END IF;
            IF abs(extract(epoch FROM (p_now-server_now)))>300 THEN
                RAISE EXCEPTION 'Scheduler clock is outside tolerance' USING ERRCODE='22023'; END IF;
            FOR candidate IN
                WITH candidates AS MATERIALIZED (
                    SELECT s.workspace_id,s.updated_by_user_id,s.timezone,s.local_time,
                        s.updated_at AS schedule_updated_at,dates.local_date,
                        ((dates.local_date+s.local_time) AT TIME ZONE s.timezone) AS scheduled_for
                    FROM public.analysis_schedules s
                    CROSS JOIN LATERAL (
                        VALUES ((p_now AT TIME ZONE s.timezone)::date),
                               (((p_now AT TIME ZONE s.timezone)::date+1)::date)
                    ) dates(local_date)
                    WHERE s.enabled
                      AND EXISTS(SELECT 1 FROM pg_timezone_names z WHERE z.name=s.timezone)
                )
                SELECT * FROM candidates c
                 WHERE c.scheduled_for-make_interval(mins=>30)<=p_now
                   AND c.scheduled_for-make_interval(mins=>30)>c.schedule_updated_at
                   -- A long worker outage misses the slot instead of running an
                   -- old and a current daily insight back-to-back.
                   AND c.scheduled_for>=p_now-interval '1 hour'
                   -- Exclude conflicts before LIMIT; otherwise the same early
                   -- rows can starve every later workspace forever.
                   AND NOT EXISTS(SELECT 1 FROM public.analysis_daily_quotas existing
                       WHERE existing.workspace_id=c.workspace_id
                         AND existing.local_date=c.local_date)
                   AND NOT EXISTS(SELECT 1 FROM public.analysis_daily_quotas recent
                       WHERE recent.workspace_id=c.workspace_id
                         AND recent.scheduled_for>c.scheduled_for-interval '20 hours')
                 ORDER BY c.scheduled_for,c.workspace_id LIMIT p_limit
            LOOP
                PERFORM pg_advisory_xact_lock(hashtextextended(candidate.workspace_id::text,0));
                -- The candidate query can predate a concurrent schedule PUT.
                -- Revalidate after the workspace lock before creating work.
                IF NOT EXISTS(SELECT 1 FROM public.analysis_schedules s
                    WHERE s.workspace_id=candidate.workspace_id AND s.enabled
                      AND s.timezone=candidate.timezone AND s.local_time=candidate.local_time
                      AND s.updated_at=candidate.schedule_updated_at) THEN CONTINUE; END IF;
                IF EXISTS(SELECT 1 FROM public.analysis_daily_quotas existing
                    WHERE existing.workspace_id=candidate.workspace_id
                      AND (existing.local_date=candidate.local_date
                           OR existing.scheduled_for>candidate.scheduled_for-interval '20 hours')) THEN CONTINUE; END IF;
                INSERT INTO public.analysis_daily_quotas(
                    workspace_id,local_date,mode,scheduled_for)
                VALUES(candidate.workspace_id,candidate.local_date,'scheduled',candidate.scheduled_for);
                INSERT INTO public.analysis_cycles(workspace_id,local_date,mode,requested_by_user_id,
                    idempotency_key,scheduled_for,refresh_due_at)
                VALUES(candidate.workspace_id,candidate.local_date,'scheduled',
                    candidate.updated_by_user_id,gen_random_uuid(),candidate.scheduled_for,
                    candidate.scheduled_for-make_interval(mins=>30));
                inserted:=inserted+1;
            END LOOP;
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
            WITH stale AS (
                SELECT c.id FROM public.analysis_cycles c
                 WHERE c.analysis_run_id IS NULL AND c.refresh_status IN ('scheduled','refreshing','ready')
                   AND c.scheduled_for<now_at-interval '1 hour'
                 ORDER BY c.scheduled_for,c.id FOR UPDATE SKIP LOCKED LIMIT 100
            ) UPDATE public.analysis_cycles c SET refresh_status='failed',last_error_code='sync_failed',
                refresh_lease_owner=NULL,refresh_lease_token=NULL,refresh_lease_expires_at=NULL,updated_at=now_at
                FROM stale WHERE c.id=stale.id;
            WITH exhausted AS (
                SELECT c.id FROM public.analysis_cycles c
                 WHERE c.refresh_status='refreshing' AND c.refresh_lease_expires_at<=now_at
                   AND c.refresh_attempts>=3
                 ORDER BY c.refresh_lease_expires_at,c.id FOR UPDATE SKIP LOCKED LIMIT 100
            ) UPDATE public.analysis_cycles c SET refresh_status='failed',last_error_code='sync_failed',
                refresh_lease_owner=NULL,refresh_lease_token=NULL,refresh_lease_expires_at=NULL,updated_at=now_at
                FROM exhausted WHERE c.id=exhausted.id;
            WITH recoverable AS (
                SELECT c.id FROM public.analysis_cycles c
                 WHERE c.refresh_status='refreshing' AND c.refresh_lease_expires_at<=now_at
                   AND c.refresh_attempts<3 AND c.scheduled_for>=now_at-interval '1 hour'
                 ORDER BY c.refresh_lease_expires_at,c.id FOR UPDATE SKIP LOCKED LIMIT 100
            ) UPDATE public.analysis_cycles c SET refresh_status='scheduled',last_error_code=NULL,
                refresh_lease_owner=NULL,refresh_lease_token=NULL,refresh_lease_expires_at=NULL,updated_at=now_at
                FROM recoverable WHERE c.id=recoverable.id;
            SELECT * INTO selected FROM public.analysis_cycles c
             WHERE c.refresh_status='scheduled' AND c.refresh_due_at<=now_at
               AND c.refresh_attempts<3 AND c.scheduled_for>=now_at-interval '1 hour'
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
            PERFORM set_config('app.workspace_id',cycle.workspace_id::text,true);
            PERFORM set_config('app.user_id',cycle.requested_by_user_id,true);
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
                BEGIN
                    INSERT INTO public.activity_events(workspace_id,actor_id,event_type,target_type,target_id,metadata)
                    VALUES(cycle.workspace_id,cycle.requested_by_user_id,'analysis_refresh_failed',
                        'analysis_cycle',cycle.id,jsonb_build_object(
                            'error_code','source_invalid','attempt',cycle.refresh_attempts));
                EXCEPTION WHEN OTHERS THEN NULL;
                END;
                RETURN next_status;
            END IF;
            INSERT INTO public.analysis_cycle_sources(workspace_id,cycle_id,chunk_id,ordinal)
                SELECT cycle.workspace_id,cycle.id,u.chunk_id,(u.ordinality-1)::integer
                FROM unnest(p_chunks) WITH ORDINALITY AS u(chunk_id,ordinality);
            UPDATE public.analysis_cycles SET refresh_status='ready',snapshot_chunk_count=actual,
                refreshed_at=now_at,last_error_code=NULL,refresh_lease_owner=NULL,refresh_lease_token=NULL,
                refresh_lease_expires_at=NULL,updated_at=now_at WHERE id=cycle.id;
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
            result jsonb:='[]'::jsonb; server_now timestamptz:=clock_timestamp();
        BEGIN
            IF p_attempts IS NULL OR p_attempts NOT BETWEEN 1 AND 10 OR p_now IS NULL
                OR p_limit IS NULL OR p_limit NOT BETWEEN 1 AND 100
                OR p_pipeline IS NULL OR length(p_pipeline) NOT BETWEEN 1 AND 160
                OR p_generation IS NULL OR length(p_generation) NOT BETWEEN 1 AND 160 THEN
                RAISE EXCEPTION 'Invalid scheduler request' USING ERRCODE='22023'; END IF;
            IF abs(extract(epoch FROM (p_now-server_now)))>300 THEN
                RAISE EXCEPTION 'Scheduler clock is outside tolerance' USING ERRCODE='22023'; END IF;
            FOR cycle IN SELECT * FROM public.analysis_cycles c
                WHERE c.refresh_status='ready' AND c.analysis_run_id IS NULL AND c.scheduled_for<=p_now
                ORDER BY c.scheduled_for,c.id FOR UPDATE SKIP LOCKED LIMIT p_limit
            LOOP
                PERFORM set_config('app.workspace_id',cycle.workspace_id::text,true);
                PERFORM set_config('app.user_id',cycle.requested_by_user_id,true);
                IF cycle.scheduled_for<p_now-interval '1 hour' THEN
                    UPDATE public.analysis_cycles SET refresh_status='failed',last_error_code='sync_failed',
                        updated_at=clock_timestamp() WHERE id=cycle.id;
                    result:=result||jsonb_build_array(jsonb_build_object(
                        'cycle_id',cycle.id,'status','failed','error_code','overdue'));
                    CONTINUE;
                END IF;
                IF NOT EXISTS(SELECT 1 FROM public.auth_users u JOIN public.workspace_members m ON m.user_id=u.id
                    WHERE u.id=cycle.requested_by_user_id AND NOT u.disabled
                      AND m.workspace_id=cycle.workspace_id AND m.role IN ('owner','editor')) THEN
                    UPDATE public.analysis_schedules s SET enabled=false
                        WHERE s.workspace_id=cycle.workspace_id
                          AND s.updated_by_user_id=cycle.requested_by_user_id;
                    UPDATE public.analysis_cycles SET refresh_status='failed',last_error_code='authorization_revoked',
                        updated_at=clock_timestamp() WHERE id=cycle.id;
                    result:=result||jsonb_build_array(jsonb_build_object(
                        'cycle_id',cycle.id,'status','failed','error_code','authorization_revoked'));
                    CONTINUE;
                END IF;
                SELECT array_agg(s.chunk_id ORDER BY s.ordinal) INTO chunks
                  FROM public.analysis_cycle_sources s WHERE s.cycle_id=cycle.id;
                IF chunks IS NULL OR cardinality(chunks)<>cycle.snapshot_chunk_count THEN
                    UPDATE public.analysis_cycles SET refresh_status='failed',last_error_code='source_invalid',
                        updated_at=clock_timestamp() WHERE id=cycle.id;
                    result:=result||jsonb_build_array(jsonb_build_object(
                        'cycle_id',cycle.id,'status','failed','error_code','source_invalid'));
                    CONTINUE;
                END IF;
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
                        result:=result||jsonb_build_array(jsonb_build_object(
                            'cycle_id',cycle.id,'status','failed','error_code','source_invalid'));
                        CONTINUE;
                    WHEN OTHERS THEN
                        UPDATE public.analysis_cycles SET refresh_status='failed',last_error_code='internal_error',
                            updated_at=clock_timestamp() WHERE id=cycle.id;
                        result:=result||jsonb_build_array(jsonb_build_object(
                            'cycle_id',cycle.id,'status','failed','error_code','internal_error'));
                        CONTINUE;
                END;
                UPDATE public.analysis_cycles SET analysis_run_id=run_id,updated_at=clock_timestamp()
                    WHERE id=cycle.id;
                INSERT INTO public.activity_events(
                    workspace_id,actor_id,event_type,target_type,target_id,metadata)
                VALUES(cycle.workspace_id,cycle.requested_by_user_id,'analysis_requested',
                    'analysis_run',run_id,jsonb_build_object('mode','scheduled'));
                result:=result||jsonb_build_array(jsonb_build_object(
                    'cycle_id',cycle.id,'status','queued','run_id',run_id));
            END LOOP;
            RETURN result;
        END $$;

        CREATE FUNCTION public.analysis_cycle_maintenance(
            p_dry_run boolean,p_recover_stale boolean,p_failed_retention_days integer,p_max_rows integer)
        RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER
        SET search_path=pg_catalog,public,pg_temp AS $$
        DECLARE wid uuid:=nullif(current_setting('app.workspace_id',true),'')::uuid;
            uid text:=nullif(current_setting('app.user_id',true),'');
            now_at timestamptz:=clock_timestamp(); stale_refreshing integer:=0;
            overdue integer:=0; recovered integer:=0; failed_stale integer:=0;
            retention_candidates integer:=0; deleted integer:=0;
        BEGIN
            IF wid IS NULL OR uid IS NULL THEN
                RAISE EXCEPTION 'Cycle maintenance requires workspace and user context'
                    USING ERRCODE='42501'; END IF;
            PERFORM m.user_id FROM public.workspace_members m
                JOIN public.auth_users u ON u.id=m.user_id
                WHERE m.workspace_id=wid AND m.user_id=uid AND m.role='owner'
                  AND NOT u.disabled FOR SHARE OF m,u;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Cycle maintenance restricted to workspace owner'
                    USING ERRCODE='42501'; END IF;
            IF p_dry_run IS NULL OR p_recover_stale IS NULL
                OR p_failed_retention_days IS NULL OR p_failed_retention_days NOT BETWEEN 1 AND 3650
                OR p_max_rows IS NULL OR p_max_rows NOT BETWEEN 1 AND 50000 THEN
                RAISE EXCEPTION 'Invalid cycle maintenance parameters' USING ERRCODE='22023'; END IF;

            SELECT count(*) INTO stale_refreshing FROM public.analysis_cycles c
                WHERE c.workspace_id=wid AND c.refresh_status='refreshing'
                  AND c.refresh_lease_expires_at<=now_at;
            SELECT count(*) INTO overdue FROM public.analysis_cycles c
                WHERE c.workspace_id=wid AND c.analysis_run_id IS NULL
                  AND c.refresh_status<>'failed' AND c.scheduled_for<now_at;
            SELECT count(*) INTO retention_candidates FROM public.analysis_cycles c
                WHERE c.workspace_id=wid AND c.analysis_run_id IS NULL
                  AND c.refresh_status='failed'
                  AND c.updated_at<now_at-make_interval(days=>p_failed_retention_days);

            IF p_recover_stale AND NOT p_dry_run THEN
                WITH recoverable AS (
                    SELECT c.id FROM public.analysis_cycles c
                     WHERE c.workspace_id=wid AND c.refresh_status='refreshing'
                       AND c.refresh_lease_expires_at<=now_at AND c.refresh_attempts<3
                       AND c.scheduled_for>=now_at-interval '1 hour'
                     ORDER BY c.refresh_lease_expires_at,c.id
                     FOR UPDATE SKIP LOCKED LIMIT p_max_rows
                ), changed AS (
                    UPDATE public.analysis_cycles c SET refresh_status='scheduled',last_error_code=NULL,
                        refresh_lease_owner=NULL,refresh_lease_token=NULL,refresh_lease_expires_at=NULL,
                        updated_at=now_at FROM recoverable r WHERE c.id=r.id RETURNING c.id
                ) SELECT count(*) INTO recovered FROM changed;

                WITH terminal AS (
                    SELECT c.id FROM public.analysis_cycles c
                     WHERE c.workspace_id=wid AND c.analysis_run_id IS NULL
                       AND c.refresh_status<>'failed'
                       AND (c.scheduled_for<now_at-interval '1 hour'
                            OR (c.refresh_status='refreshing'
                                AND c.refresh_lease_expires_at<=now_at
                                AND c.refresh_attempts>=3))
                     ORDER BY c.scheduled_for,c.id
                     FOR UPDATE SKIP LOCKED LIMIT p_max_rows
                ), changed AS (
                    UPDATE public.analysis_cycles c SET refresh_status='failed',last_error_code='sync_failed',
                        refresh_lease_owner=NULL,refresh_lease_token=NULL,refresh_lease_expires_at=NULL,
                        updated_at=now_at FROM terminal t WHERE c.id=t.id RETURNING c.id
                ) SELECT count(*) INTO failed_stale FROM changed;
            END IF;

            IF NOT p_dry_run THEN
                WITH expired AS (
                    SELECT c.id FROM public.analysis_cycles c
                     WHERE c.workspace_id=wid AND c.analysis_run_id IS NULL
                       AND c.refresh_status='failed'
                       AND c.updated_at<now_at-make_interval(days=>p_failed_retention_days)
                     ORDER BY c.updated_at,c.id LIMIT p_max_rows
                ), removed AS (
                    DELETE FROM public.analysis_cycles c USING expired e
                     WHERE c.id=e.id RETURNING c.id
                ) SELECT count(*) INTO deleted FROM removed;
            END IF;

            RETURN jsonb_build_object(
                'stale_refreshing',stale_refreshing,'overdue',overdue,
                'recovered_stale_refreshes',recovered,'failed_stale_cycles',failed_stale,
                'failed_retention_candidates',retention_candidates,'failed_deleted',deleted);
        END $$;

        CREATE FUNCTION public.activity_event_maintenance(
            p_dry_run boolean,p_retention_days integer,p_max_rows integer)
        RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER
        SET search_path=pg_catalog,public,pg_temp AS $$
        DECLARE wid uuid:=nullif(current_setting('app.workspace_id',true),'')::uuid;
            uid text:=nullif(current_setting('app.user_id',true),'');
            now_at timestamptz:=clock_timestamp(); candidates integer:=0; deleted integer:=0;
        BEGIN
            IF wid IS NULL OR uid IS NULL THEN
                RAISE EXCEPTION 'Activity maintenance requires workspace and user context'
                    USING ERRCODE='42501'; END IF;
            PERFORM m.user_id FROM public.workspace_members m
                JOIN public.auth_users u ON u.id=m.user_id
                WHERE m.workspace_id=wid AND m.user_id=uid AND m.role='owner'
                  AND NOT u.disabled FOR SHARE OF m,u;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Activity maintenance restricted to workspace owner'
                    USING ERRCODE='42501'; END IF;
            IF p_dry_run IS NULL OR p_retention_days IS NULL
                OR p_retention_days NOT BETWEEN 1 AND 3650
                OR p_max_rows IS NULL OR p_max_rows NOT BETWEEN 1 AND 50000 THEN
                RAISE EXCEPTION 'Invalid activity maintenance parameters'
                    USING ERRCODE='22023'; END IF;

            SELECT count(*)::integer INTO candidates FROM (
                SELECT e.id FROM public.activity_events e
                 WHERE e.workspace_id=wid
                   AND e.created_at<now_at-make_interval(days=>p_retention_days)
                 ORDER BY e.created_at,e.id
                 LIMIT p_max_rows
            ) bounded;
            IF NOT p_dry_run THEN
                WITH expired AS (
                    SELECT e.id FROM public.activity_events e
                     WHERE e.workspace_id=wid
                       AND e.created_at<now_at-make_interval(days=>p_retention_days)
                     ORDER BY e.created_at,e.id
                     LIMIT p_max_rows
                ), removed AS (
                    DELETE FROM public.activity_events e USING expired x
                     WHERE e.workspace_id=wid AND e.id=x.id RETURNING e.id
                ) SELECT count(*) INTO deleted FROM removed;
            END IF;
            RETURN jsonb_build_object('candidates',candidates,'deleted',deleted);
        END $$;

        CREATE FUNCTION public.queue_operational_health()
        RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER
        SET search_path=pg_catalog,public,pg_temp AS $$
        DECLARE wid uuid:=nullif(current_setting('app.workspace_id',true),'')::uuid;
            uid text:=nullif(current_setting('app.user_id',true),'');
            now_at timestamptz:=clock_timestamp(); value jsonb;
        BEGIN
            IF wid IS NULL OR uid IS NULL THEN
                RAISE EXCEPTION 'Queue health requires workspace and user context'
                    USING ERRCODE='42501'; END IF;
            PERFORM m.user_id FROM public.workspace_members m
                JOIN public.auth_users u ON u.id=m.user_id
                WHERE m.workspace_id=wid AND m.user_id=uid AND m.role='owner'
                  AND NOT u.disabled FOR SHARE OF m,u;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Queue health restricted to workspace owner'
                    USING ERRCODE='42501'; END IF;

            SELECT jsonb_build_object(
                'analysis',to_jsonb(analysis_row),
                'flares',to_jsonb(flare_row),
                'cycles',to_jsonb(cycle_row))
              INTO value
              FROM (
                SELECT
                    count(*) FILTER(WHERE status='pending')::integer AS pending,
                    count(*) FILTER(WHERE status='processing')::integer AS processing,
                    count(*) FILTER(WHERE status='completed')::integer AS completed,
                    count(*) FILTER(WHERE status='failed')::integer AS failed,
                    count(*) FILTER(WHERE status='pending' AND available_at<=now_at)::integer AS due,
                    count(*) FILTER(WHERE status='processing' AND lease_expires_at<=now_at)::integer
                        AS stale_processing,
                    extract(epoch FROM (now_at-min(created_at) FILTER(WHERE status='pending')))
                        AS oldest_pending_seconds,
                    extract(epoch FROM (now_at-min(created_at) FILTER(WHERE status='processing')))
                        AS oldest_processing_seconds
                  FROM public.analysis_jobs WHERE workspace_id=wid
              ) analysis_row
              CROSS JOIN (
                SELECT
                    count(*) FILTER(WHERE status='pending')::integer AS pending,
                    count(*) FILTER(WHERE status='processing')::integer AS processing,
                    count(*) FILTER(WHERE status='completed')::integer AS completed,
                    count(*) FILTER(WHERE status='failed')::integer AS failed,
                    count(*) FILTER(WHERE status='pending' AND available_at<=now_at)::integer AS due,
                    count(*) FILTER(WHERE status='processing' AND lease_expires_at<=now_at)::integer
                        AS stale_processing,
                    extract(epoch FROM (now_at-min(created_at) FILTER(WHERE status='pending')))
                        AS oldest_pending_seconds,
                    extract(epoch FROM (now_at-min(created_at) FILTER(WHERE status='processing')))
                        AS oldest_processing_seconds
                  FROM public.flare_generation_runs WHERE workspace_id=wid
              ) flare_row
              CROSS JOIN (
                SELECT
                    count(*) FILTER(WHERE refresh_status='scheduled')::integer AS scheduled,
                    count(*) FILTER(WHERE refresh_status='refreshing')::integer AS refreshing,
                    count(*) FILTER(WHERE refresh_status='ready')::integer AS ready,
                    count(*) FILTER(WHERE refresh_status='failed')::integer AS failed,
                    count(*) FILTER(WHERE refresh_status='scheduled' AND refresh_due_at<=now_at)::integer
                        AS due_refresh,
                    count(*) FILTER(WHERE refresh_status='ready' AND analysis_run_id IS NULL
                        AND scheduled_for<=now_at)::integer AS due_run,
                    count(*) FILTER(WHERE refresh_status='refreshing'
                        AND refresh_lease_expires_at<=now_at)::integer AS stale_refreshing,
                    count(*) FILTER(WHERE analysis_run_id IS NULL AND refresh_status<>'failed'
                        AND scheduled_for<now_at-interval '1 hour')::integer AS overdue,
                    extract(epoch FROM (now_at-min(refresh_due_at) FILTER(
                        WHERE refresh_status='scheduled' AND refresh_due_at<=now_at)))
                        AS oldest_refresh_due_seconds,
                    extract(epoch FROM (now_at-min(scheduled_for) FILTER(
                        WHERE refresh_status='ready' AND analysis_run_id IS NULL
                          AND scheduled_for<=now_at))) AS oldest_run_due_seconds
                  FROM public.analysis_cycles WHERE workspace_id=wid
              ) cycle_row;
            RETURN value;
        END $$;
        """
    )
    signatures = {
        "set_analysis_schedule(boolean,text,time without time zone)": "flare_app",
        "start_daily_analysis_run(uuid,uuid[],text,text,text,integer,integer,integer)": "flare_app",
        "materialize_analysis_cycles(timestamp with time zone,integer)": "flare_worker",
        "claim_analysis_cycle_refresh(uuid,integer)": "flare_worker",
        "load_analysis_cycle_candidates(uuid,uuid,integer,integer)": "flare_worker",
        "finish_analysis_cycle_refresh(uuid,uuid,uuid[],text,double precision)": "flare_worker",
        "enqueue_due_analysis_cycles(text,text,integer,timestamp with time zone,integer)": "flare_worker",
        "analysis_cycle_maintenance(boolean,boolean,integer,integer)": "flare_app",
        "activity_event_maintenance(boolean,integer,integer)": "flare_app",
        "queue_operational_health()": "flare_app",
    }
    for signature, runtime_role in signatures.items():
        op.execute(f"ALTER FUNCTION public.{signature} OWNER TO {owner}")
        op.execute(f"REVOKE ALL ON FUNCTION public.{signature} FROM PUBLIC")
        op.execute(f"GRANT EXECUTE ON FUNCTION public.{signature} TO {runtime_role}")
    for trigger_signature in ("guard_analysis_schedule()", "guard_analysis_cycle_quota()"):
        op.execute(f"ALTER FUNCTION public.{trigger_signature} OWNER TO {owner}")
        op.execute(f"REVOKE ALL ON FUNCTION public.{trigger_signature} FROM PUBLIC")
    op.execute(
        """
        -- All runtime analysis requests now pass through the daily quota
        -- capability.  Keep the private four-argument enqueue available to
        -- SECURITY DEFINER orchestration functions, but remove the old API
        -- role's direct queue bypass.
        REVOKE EXECUTE ON FUNCTION public.enqueue_analysis_job(uuid[],text,integer)
            FROM flare_app;
        REVOKE INSERT,UPDATE,DELETE ON public.analysis_schedules FROM flare_app;

        -- Rows produced by the legacy direct-enqueue path have no public run
        -- to own or observe them.  Fence unfinished rows during the migration
        -- so they cannot execute after the bypass has been removed.  Existing
        -- completed history remains intact.
        UPDATE public.analysis_jobs j
           SET status='failed',last_error_code='source_invalid',result=NULL,metadata=NULL,
               lease_owner=NULL,lease_token=NULL,lease_expires_at=NULL,
               completed_at=clock_timestamp(),updated_at=clock_timestamp()
         WHERE j.status IN ('pending','processing')
           AND NOT EXISTS(SELECT 1 FROM public.analysis_runs r
                           WHERE r.analysis_job_id=j.id);

        UPDATE public.flare_generation_runs g
           SET status='failed',last_error_code='generation_mismatch',metadata=NULL,flare_ids=NULL,
               lease_owner=NULL,lease_token=NULL,lease_expires_at=NULL,
               completed_at=clock_timestamp(),updated_at=clock_timestamp()
         WHERE g.status IN ('pending','processing')
           AND NOT EXISTS(SELECT 1 FROM public.analysis_runs r
                           WHERE r.analysis_job_id=g.analysis_job_id);
        """
    )
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
                'flare_viewed','screen_opened','queue_health_requested','queue_maintenance_run','import_started',
                'import_completed','import_failed','analysis_requested','schedule_updated',
                'analysis_refresh_started','analysis_refresh_completed','analysis_refresh_failed',
                'github_connection_started','github_installation_authorized',
                'github_repository_selected','github_disconnected'));
        END $$;
        """
    )


def downgrade():
    raise RuntimeError("Daily analysis snapshots contain customer evidence; restore from backup instead.")
