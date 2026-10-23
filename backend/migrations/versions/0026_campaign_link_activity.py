"""Anonymous daily campaign opens; lifetime counters remain authoritative."""

import os

from alembic import op


revision = "0026"
down_revision = "0025"
branch_labels = None
depends_on = None


def upgrade() -> None:
    managed = os.getenv("FLARE_DATABASE_PROVIDER") == "yandex"
    owner = "flare_owner" if managed else "flare_job_executor"
    if not managed:
        op.execute(f"GRANT CREATE ON SCHEMA public TO {owner}")
    op.execute(f"""
        -- Existing totals have no dates. Record when real daily coverage starts;
        -- never distribute historical opens over invented dates.
        ALTER TABLE public.campaign_links ADD COLUMN activity_started_at
            timestamptz NOT NULL DEFAULT transaction_timestamp();

        CREATE TABLE public.campaign_link_daily_opens (
            link_id uuid NOT NULL REFERENCES public.campaign_links(id) ON DELETE CASCADE,
            day date NOT NULL,
            opens bigint NOT NULL CHECK (opens > 0),
            PRIMARY KEY (link_id, day)
        );
        ALTER TABLE public.campaign_link_daily_opens ENABLE ROW LEVEL SECURITY;
        ALTER TABLE public.campaign_link_daily_opens FORCE ROW LEVEL SECURITY;
        REVOKE ALL ON public.campaign_link_daily_opens FROM PUBLIC, flare_app, flare_worker;
        GRANT SELECT ON public.campaign_link_daily_opens TO flare_app;
        GRANT SELECT, INSERT, UPDATE, DELETE ON public.campaign_link_daily_opens TO {owner};
        CREATE POLICY campaign_daily_owner ON public.campaign_link_daily_opens
            FOR SELECT TO flare_app USING (
                EXISTS (
                    SELECT 1 FROM public.campaign_links link
                    JOIN public.workspace_members member ON member.workspace_id=link.workspace_id
                    WHERE link.id=campaign_link_daily_opens.link_id
                      AND link.workspace_id=nullif(current_setting('app.workspace_id',true),'')::uuid
                      AND member.user_id=nullif(current_setting('app.user_id',true),'')
                      AND member.role='owner'
                )
            );
        CREATE POLICY campaign_daily_executor ON public.campaign_link_daily_opens
            TO {owner} USING (true) WITH CHECK (true);

        CREATE OR REPLACE FUNCTION public.campaign_link_count(p_slug text) RETURNS boolean
        LANGUAGE plpgsql SECURITY DEFINER
        SET search_path=pg_catalog,public,pg_temp AS $$
        DECLARE selected_link uuid;
        BEGIN
            UPDATE public.campaign_links SET click_count=click_count+1
             WHERE slug=p_slug AND archived_at IS NULL
               AND p_slug ~ '^[A-Za-z0-9_-]{{22,32}}$'
             RETURNING id INTO selected_link;
            IF selected_link IS NULL THEN RETURN false; END IF;
            -- Both increments share the same transaction. A failure rolls back
            -- both counters; the separately resolved redirect still succeeds.
            INSERT INTO public.campaign_link_daily_opens(link_id,day,opens)
                VALUES(selected_link,(clock_timestamp() AT TIME ZONE 'UTC')::date,1)
            ON CONFLICT(link_id,day) DO UPDATE
                SET opens=campaign_link_daily_opens.opens+1;
            RETURN true;
        END $$;
        ALTER FUNCTION public.campaign_link_count(text) OWNER TO {owner};
        REVOKE ALL ON FUNCTION public.campaign_link_count(text) FROM PUBLIC, flare_app, flare_worker;
        GRANT EXECUTE ON FUNCTION public.campaign_link_count(text) TO flare_app;
        ALTER FUNCTION public.campaign_link_count(text) SET statement_timeout='250ms';
        ALTER FUNCTION public.campaign_link_count(text) SET lock_timeout='100ms';
    """)
    if not managed:
        op.execute(f"REVOKE CREATE ON SCHEMA public FROM {owner}")


def downgrade() -> None:
    raise RuntimeError("Campaign activity is release analytics; restore a reviewed backup instead.")
