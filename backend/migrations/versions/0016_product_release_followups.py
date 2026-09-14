"""Scheduled Flare notification preferences and durable email delivery."""

import os

from alembic import op


revision = "0016"
down_revision = "0015"
branch_labels = None
depends_on = None


def upgrade():
    owner = "flare_owner" if os.getenv("FLARE_DATABASE_PROVIDER") == "yandex" else "flare_job_executor"
    op.execute(
        f"""
        ALTER TABLE public.analysis_schedules
            ADD COLUMN email_notifications_enabled boolean NOT NULL DEFAULT true;

        CREATE TABLE public.scheduled_analysis_notifications (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            workspace_id uuid NOT NULL REFERENCES public.workspaces(id) ON DELETE CASCADE,
            analysis_run_id uuid NOT NULL UNIQUE REFERENCES public.analysis_runs(id) ON DELETE CASCADE,
            requested_by_user_id text NOT NULL REFERENCES public.auth_users(id),
            flare_ids uuid[] NOT NULL CHECK (
                cardinality(flare_ids) BETWEEN 1 AND 3
                AND array_position(flare_ids, NULL) IS NULL
            ),
            status text NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending','processing','sent','failed')),
            attempts integer NOT NULL DEFAULT 0 CHECK (attempts BETWEEN 0 AND 3),
            max_attempts integer NOT NULL DEFAULT 3 CHECK (max_attempts = 3),
            available_at timestamptz NOT NULL DEFAULT now(),
            lease_owner uuid,
            lease_token uuid,
            lease_expires_at timestamptz,
            last_error_code text CHECK (last_error_code IN (
                'delivery_unavailable','delivery_failed','invalid_payload','notifications_disabled'
            )),
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            sent_at timestamptz,
            UNIQUE (workspace_id, id),
            CHECK ((status = 'processing') = (
                lease_owner IS NOT NULL AND lease_token IS NOT NULL AND lease_expires_at IS NOT NULL
            )),
            CHECK (status = 'processing' OR (
                lease_owner IS NULL AND lease_token IS NULL AND lease_expires_at IS NULL
            )),
            CHECK ((status = 'sent') = (sent_at IS NOT NULL)),
            CHECK (status <> 'sent' OR last_error_code IS NULL)
        );
        CREATE INDEX scheduled_notifications_pending_idx
            ON public.scheduled_analysis_notifications(available_at, created_at, id)
            WHERE status = 'pending';
        CREATE INDEX scheduled_notifications_lease_idx
            ON public.scheduled_analysis_notifications(lease_expires_at, id)
            WHERE status = 'processing';

        ALTER TABLE public.scheduled_analysis_notifications ENABLE ROW LEVEL SECURITY;
        ALTER TABLE public.scheduled_analysis_notifications FORCE ROW LEVEL SECURITY;
        REVOKE ALL ON public.scheduled_analysis_notifications FROM PUBLIC;
        GRANT SELECT,INSERT,UPDATE ON public.scheduled_analysis_notifications TO {owner};
        GRANT SELECT ON public.scheduled_analysis_notifications TO flare_app;
        GRANT SELECT (id,email,email_verified_at,disabled)
            ON public.auth_users TO {owner};
        CREATE POLICY scheduled_notification_executor
            ON public.scheduled_analysis_notifications TO {owner}
            USING (true) WITH CHECK (true);

        CREATE FUNCTION public.set_analysis_schedule_email_notifications(p_enabled boolean)
        RETURNS boolean LANGUAGE plpgsql SECURITY DEFINER
        SET search_path=pg_catalog,public,pg_temp AS $$
        DECLARE wid uuid:=nullif(current_setting('app.workspace_id',true),'')::uuid;
            uid text:=nullif(current_setting('app.user_id',true),'');
        BEGIN
            IF wid IS NULL OR uid IS NULL OR p_enabled IS NULL THEN
                RAISE EXCEPTION 'Invalid notification preference' USING ERRCODE='22023';
            END IF;
            PERFORM u.id FROM public.auth_users u
                WHERE u.id=uid AND NOT u.disabled FOR SHARE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Authorization required' USING ERRCODE='42501';
            END IF;
            PERFORM m.user_id FROM public.workspace_members m
                WHERE m.workspace_id=wid AND m.user_id=uid
                  AND m.role IN ('owner','editor') FOR SHARE;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Write permission required' USING ERRCODE='42501';
            END IF;
            UPDATE public.analysis_schedules
               SET email_notifications_enabled=p_enabled,
                   updated_by_user_id=uid
             WHERE workspace_id=wid;
            IF NOT FOUND THEN
                RAISE EXCEPTION 'Analysis schedule required' USING ERRCODE='22023';
            END IF;
            RETURN p_enabled;
        END $$;

        CREATE FUNCTION public.enqueue_scheduled_flare_notification()
        RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER
        SET search_path=pg_catalog,public,pg_temp AS $$
        DECLARE run_id uuid; actor_id text;
        BEGIN
            IF NEW.status <> 'completed' OR OLD.status = 'completed'
                OR NEW.flare_ids IS NULL OR cardinality(NEW.flare_ids) = 0 THEN
                RETURN NEW;
            END IF;
            SELECT r.id,c.requested_by_user_id INTO run_id,actor_id
              FROM public.analysis_runs r
              JOIN public.analysis_cycles c ON c.analysis_run_id=r.id
              JOIN public.analysis_schedules s ON s.workspace_id=c.workspace_id
              JOIN public.auth_users u ON u.id=c.requested_by_user_id
              JOIN public.workspace_members m
                ON (m.workspace_id,m.user_id)=(c.workspace_id,c.requested_by_user_id)
             WHERE r.analysis_job_id=NEW.analysis_job_id
               AND r.workspace_id=NEW.workspace_id
               AND c.mode='scheduled'
               AND s.email_notifications_enabled
               AND NOT u.disabled
               AND u.email_verified_at IS NOT NULL
               AND m.role IN ('owner','editor');
            IF FOUND THEN
                INSERT INTO public.scheduled_analysis_notifications(
                    workspace_id,analysis_run_id,requested_by_user_id,flare_ids
                ) VALUES(NEW.workspace_id,run_id,actor_id,NEW.flare_ids)
                ON CONFLICT(analysis_run_id) DO NOTHING;
            END IF;
            RETURN NEW;
        END $$;
        CREATE TRIGGER scheduled_flare_notification_handoff
            AFTER UPDATE OF status ON public.flare_generation_runs
            FOR EACH ROW EXECUTE FUNCTION public.enqueue_scheduled_flare_notification();

        CREATE FUNCTION public.claim_scheduled_flare_notification(p_owner uuid,p_seconds integer)
        RETURNS SETOF public.scheduled_analysis_notifications
        LANGUAGE plpgsql SECURITY DEFINER
        SET search_path=pg_catalog,public,pg_temp AS $$
        DECLARE selected public.scheduled_analysis_notifications;
        BEGIN
            IF p_owner IS NULL OR p_seconds IS NULL OR p_seconds NOT BETWEEN 1 AND 3600 THEN
                RAISE EXCEPTION 'Invalid lease' USING ERRCODE='22023';
            END IF;
            UPDATE public.scheduled_analysis_notifications n
               SET status='failed',last_error_code='delivery_failed',
                   lease_owner=NULL,lease_token=NULL,lease_expires_at=NULL,
                   updated_at=clock_timestamp()
             WHERE n.status='processing' AND n.lease_expires_at<=clock_timestamp()
               AND n.attempts>=n.max_attempts;
            SELECT * INTO selected
              FROM public.scheduled_analysis_notifications n
             WHERE n.attempts<n.max_attempts
               AND ((n.status='pending' AND n.available_at<=clock_timestamp())
                    OR (n.status='processing' AND n.lease_expires_at<=clock_timestamp()))
             ORDER BY n.available_at,n.created_at,n.id
             FOR UPDATE SKIP LOCKED LIMIT 1;
            IF NOT FOUND THEN RETURN; END IF;
            RETURN QUERY UPDATE public.scheduled_analysis_notifications n
               SET status='processing',attempts=n.attempts+1,
                   lease_owner=p_owner,lease_token=gen_random_uuid(),
                   lease_expires_at=clock_timestamp()+make_interval(secs=>p_seconds),
                   last_error_code=NULL,updated_at=clock_timestamp()
             WHERE n.id=selected.id RETURNING n.*;
        END $$;

        CREATE FUNCTION public.load_scheduled_flare_notification(p_id uuid,p_token uuid)
        RETURNS jsonb LANGUAGE plpgsql SECURITY DEFINER
        SET search_path=pg_catalog,public,pg_temp AS $$
        DECLARE notification public.scheduled_analysis_notifications; payload jsonb;
        BEGIN
            SELECT * INTO notification FROM public.scheduled_analysis_notifications n
             WHERE n.id=p_id AND n.status='processing' AND n.lease_token=p_token
               AND n.lease_expires_at>clock_timestamp() FOR UPDATE;
            IF NOT FOUND THEN RETURN jsonb_build_object('error','lease_lost'); END IF;
            PERFORM set_config('app.workspace_id',notification.workspace_id::text,true);
            PERFORM set_config('app.user_id',notification.requested_by_user_id,true);
            IF NOT EXISTS(SELECT 1 FROM public.analysis_schedules s
                WHERE s.workspace_id=notification.workspace_id
                  AND s.email_notifications_enabled) THEN
                RETURN jsonb_build_object('error','notifications_disabled');
            END IF;
            SELECT jsonb_build_object(
                'analysis_run_id',notification.analysis_run_id,
                'recipient',u.email,
                'flares',jsonb_agg(jsonb_build_object('id',i.id,'title',i.title)
                    ORDER BY f.ordinality)
            ) INTO payload
              FROM public.auth_users u
              JOIN public.workspace_members m
                ON m.user_id=u.id AND m.workspace_id=notification.workspace_id
              CROSS JOIN unnest(notification.flare_ids) WITH ORDINALITY f(id,ordinality)
              JOIN public.insights i
                ON i.id=f.id AND i.workspace_id=notification.workspace_id
               AND i.flare_type IS NOT NULL
             WHERE u.id=notification.requested_by_user_id
               AND NOT u.disabled AND u.email_verified_at IS NOT NULL
               AND m.role IN ('owner','editor')
             GROUP BY u.email;
            IF payload IS NULL OR jsonb_array_length(payload->'flares')<>cardinality(notification.flare_ids) THEN
                RETURN jsonb_build_object('error','invalid_payload');
            END IF;
            RETURN payload;
        END $$;

        CREATE FUNCTION public.finish_scheduled_flare_notification(
            p_id uuid,p_token uuid,p_error text,p_retry double precision)
        RETURNS text LANGUAGE plpgsql SECURITY DEFINER
        SET search_path=pg_catalog,public,pg_temp AS $$
        DECLARE notification public.scheduled_analysis_notifications; next_status text;
        BEGIN
            SELECT * INTO notification FROM public.scheduled_analysis_notifications n
             WHERE n.id=p_id AND n.status='processing' AND n.lease_token=p_token
               AND n.lease_expires_at>clock_timestamp() FOR UPDATE;
            IF NOT FOUND THEN RETURN 'lease_lost'; END IF;
            IF p_error IS NULL THEN
                next_status:='sent';
            ELSIF p_error NOT IN ('delivery_unavailable','delivery_failed','invalid_payload','notifications_disabled') THEN
                RAISE EXCEPTION 'Invalid notification result' USING ERRCODE='22023';
            ELSIF p_error='delivery_failed' AND notification.attempts<notification.max_attempts
                AND p_retry IS NOT NULL AND p_retry>=0 AND p_retry<'Infinity'::double precision THEN
                next_status:='pending';
            ELSE
                next_status:='failed';
            END IF;
            UPDATE public.scheduled_analysis_notifications
               SET status=next_status,last_error_code=p_error,
                   available_at=CASE WHEN next_status='pending'
                       THEN clock_timestamp()+make_interval(secs=>p_retry) ELSE available_at END,
                   lease_owner=NULL,lease_token=NULL,lease_expires_at=NULL,
                   updated_at=clock_timestamp(),
                   sent_at=CASE WHEN next_status='sent' THEN clock_timestamp() ELSE NULL END
             WHERE id=notification.id;
            RETURN next_status;
        END $$;
        """
    )
    signatures = {
        "set_analysis_schedule_email_notifications(boolean)": "flare_app",
        "enqueue_scheduled_flare_notification()": None,
        "claim_scheduled_flare_notification(uuid,integer)": "flare_worker",
        "load_scheduled_flare_notification(uuid,uuid)": "flare_worker",
        "finish_scheduled_flare_notification(uuid,uuid,text,double precision)": "flare_worker",
    }
    for signature, role in signatures.items():
        op.execute(f"ALTER FUNCTION public.{signature} OWNER TO {owner}")
        op.execute(f"REVOKE ALL ON FUNCTION public.{signature} FROM PUBLIC")
        if role:
            op.execute(f"GRANT EXECUTE ON FUNCTION public.{signature} TO {role}")


def downgrade():
    raise RuntimeError("Scheduled email delivery records are durable; restore from backup instead.")
