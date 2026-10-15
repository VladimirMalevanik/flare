"""Workspace campaign links with aggregate click counters."""

import os

from alembic import op


revision = "0025"
down_revision = "0024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    managed = os.getenv("FLARE_DATABASE_PROVIDER") == "yandex"
    owner = "flare_owner" if managed else "flare_job_executor"
    # PostgreSQL requires a function's new owner to have CREATE on its schema.
    # The restricted executor must not keep that capability after ownership is
    # transferred, so grant it only inside this migration transaction.
    if not managed:
        op.execute(f"GRANT CREATE ON SCHEMA public TO {owner}")
    op.execute(
        f"""
        CREATE TABLE public.campaign_links (
            id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            workspace_id uuid NOT NULL REFERENCES public.workspaces(id) ON DELETE CASCADE,
            created_by_user_id text DEFAULT nullif(current_setting('app.user_id', true), '')
                REFERENCES public.auth_users(id) ON DELETE SET NULL,
            label text NOT NULL CHECK (
                length(btrim(label)) BETWEEN 1 AND 80
                AND label !~ '[[:cntrl:]]'
            ),
            slug text NOT NULL UNIQUE CHECK (slug ~ '^[A-Za-z0-9_-]{{22,32}}$'),
            destination_path text NOT NULL CHECK (destination_path IN ('/', '/register', '/login')),
            utm_source text NOT NULL CHECK (utm_source ~ '^[a-z0-9][a-z0-9._-]{{0,79}}$'),
            utm_medium text NOT NULL CHECK (utm_medium ~ '^[a-z0-9][a-z0-9._-]{{0,79}}$'),
            utm_campaign text NOT NULL CHECK (utm_campaign ~ '^[a-z0-9][a-z0-9._-]{{0,79}}$'),
            utm_content text CHECK (
                utm_content IS NULL OR utm_content ~ '^[a-z0-9][a-z0-9._-]{{0,79}}$'
            ),
            click_count bigint NOT NULL DEFAULT 0 CHECK (click_count >= 0),
            created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            archived_at timestamptz
        );
        CREATE INDEX campaign_links_workspace_created_idx
            ON public.campaign_links(workspace_id, created_at DESC, id DESC);
        CREATE INDEX campaign_links_active_workspace_idx
            ON public.campaign_links(workspace_id) WHERE archived_at IS NULL;

        ALTER TABLE public.campaign_links ENABLE ROW LEVEL SECURITY;
        ALTER TABLE public.campaign_links FORCE ROW LEVEL SECURITY;
        REVOKE ALL ON public.campaign_links FROM PUBLIC, flare_app, flare_worker;
        GRANT SELECT ON public.campaign_links TO flare_app;
        GRANT INSERT(
            id, workspace_id, label, slug, destination_path,
            utm_source, utm_medium, utm_campaign, utm_content
        ) ON public.campaign_links TO flare_app;
        GRANT UPDATE(label, archived_at) ON public.campaign_links TO flare_app;
        GRANT SELECT, INSERT, UPDATE, DELETE ON public.campaign_links TO {owner};

        CREATE POLICY campaign_links_owner ON public.campaign_links TO flare_app
            USING (
                workspace_id = nullif(current_setting('app.workspace_id', true), '')::uuid
                AND EXISTS (
                    SELECT 1 FROM public.workspace_members member
                    WHERE member.workspace_id = campaign_links.workspace_id
                      AND member.user_id = nullif(current_setting('app.user_id', true), '')
                      AND member.role = 'owner'
                )
            )
            WITH CHECK (
                workspace_id = nullif(current_setting('app.workspace_id', true), '')::uuid
                AND EXISTS (
                    SELECT 1 FROM public.workspace_members member
                    WHERE member.workspace_id = campaign_links.workspace_id
                      AND member.user_id = nullif(current_setting('app.user_id', true), '')
                      AND member.role = 'owner'
                )
            );
        CREATE POLICY campaign_links_executor ON public.campaign_links TO {owner}
            USING (true) WITH CHECK (true);

        CREATE FUNCTION public.guard_campaign_link_limit() RETURNS trigger
        LANGUAGE plpgsql SECURITY DEFINER
        SET search_path=pg_catalog,public,pg_temp AS $$
        DECLARE active_count integer;
        BEGIN
            IF NEW.archived_at IS NULL AND (
                TG_OP = 'INSERT' OR OLD.archived_at IS NOT NULL
            ) THEN
                PERFORM pg_advisory_xact_lock(
                    hashtextextended(NEW.workspace_id::text || '-campaign-links', 0)
                );
                SELECT count(*) INTO active_count
                  FROM public.campaign_links link
                 WHERE link.workspace_id = NEW.workspace_id
                   AND link.archived_at IS NULL
                   AND (TG_OP = 'INSERT' OR link.id <> NEW.id);
                IF active_count >= 25 THEN
                    RAISE EXCEPTION 'Campaign link limit reached' USING ERRCODE='P0001';
                END IF;
            END IF;
            RETURN NEW;
        END $$;
        ALTER FUNCTION public.guard_campaign_link_limit() OWNER TO {owner};
        REVOKE ALL ON FUNCTION public.guard_campaign_link_limit()
            FROM PUBLIC, flare_app, flare_worker;
        CREATE TRIGGER campaign_link_limit_guard
            BEFORE INSERT OR UPDATE OF archived_at ON public.campaign_links
            FOR EACH ROW EXECUTE FUNCTION public.guard_campaign_link_limit();

        CREATE FUNCTION public.campaign_link_resolve(p_slug text)
        RETURNS TABLE(
            destination_path text,
            utm_source text,
            utm_medium text,
            utm_campaign text,
            utm_content text
        )
        LANGUAGE sql SECURITY DEFINER
        SET search_path=pg_catalog,public,pg_temp AS $$
            SELECT destination_path,utm_source,utm_medium,utm_campaign,utm_content
              FROM public.campaign_links
             WHERE slug=p_slug AND p_slug ~ '^[A-Za-z0-9_-]{{22,32}}$'
        $$;
        ALTER FUNCTION public.campaign_link_resolve(text) OWNER TO {owner};
        REVOKE ALL ON FUNCTION public.campaign_link_resolve(text)
            FROM PUBLIC, flare_app, flare_worker;
        GRANT EXECUTE ON FUNCTION public.campaign_link_resolve(text) TO flare_app;
        ALTER FUNCTION public.campaign_link_resolve(text) SET statement_timeout='500ms';

        CREATE FUNCTION public.campaign_link_count(p_slug text) RETURNS boolean
        LANGUAGE plpgsql SECURITY DEFINER
        SET search_path=pg_catalog,public,pg_temp AS $$
        BEGIN
            UPDATE public.campaign_links
               SET click_count=click_count+1
             WHERE slug=p_slug AND archived_at IS NULL
               AND p_slug ~ '^[A-Za-z0-9_-]{{22,32}}$';
            RETURN FOUND;
        END $$;
        ALTER FUNCTION public.campaign_link_count(text) OWNER TO {owner};
        REVOKE ALL ON FUNCTION public.campaign_link_count(text)
            FROM PUBLIC, flare_app, flare_worker;
        GRANT EXECUTE ON FUNCTION public.campaign_link_count(text) TO flare_app;
        ALTER FUNCTION public.campaign_link_count(text) SET statement_timeout='250ms';
        ALTER FUNCTION public.campaign_link_count(text) SET lock_timeout='100ms';
        """
    )
    if not managed:
        op.execute(f"REVOKE CREATE ON SCHEMA public FROM {owner}")


def downgrade() -> None:
    raise RuntimeError(
        "Campaign link counters are release analytics; restore a reviewed backup instead."
    )
