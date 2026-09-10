"""First-party users/sessions and user-aware tenant authorization."""
import os

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade():
    yandex = os.getenv("FLARE_DATABASE_PROVIDER", "self-managed") == "yandex"
    onboarding_role = "" if yandex else """
        -- An isolated function owner: no login, inheritance or RLS bypass.
        CREATE ROLE flare_onboarding NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;
        GRANT USAGE ON SCHEMA public TO flare_onboarding;
        GRANT SELECT, INSERT ON public.workspaces, public.workspace_members TO flare_onboarding;
    """
    function_owner = "" if yandex else """
        ALTER FUNCTION public.provision_workspace(uuid, text) OWNER TO flare_onboarding;
    """
    op.execute("""
        CREATE TABLE public.auth_users (
            id text PRIMARY KEY,
            email text NOT NULL UNIQUE CHECK (email = lower(btrim(email))),
            password_hash text NOT NULL,
            name text NOT NULL CHECK (length(btrim(name)) BETWEEN 1 AND 100),
            initial_workspace_id uuid NOT NULL REFERENCES public.workspaces(id),
            disabled boolean NOT NULL DEFAULT false,
            created_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE TABLE public.auth_sessions (
            token_hash text PRIMARY KEY CHECK (token_hash ~ '^[0-9a-f]{64}$'),
            user_id text NOT NULL REFERENCES public.auth_users(id) ON DELETE CASCADE,
            workspace_id uuid NOT NULL REFERENCES public.workspaces(id),
            created_at timestamptz NOT NULL DEFAULT now(),
            expires_at timestamptz NOT NULL,
            last_seen_at timestamptz NOT NULL DEFAULT now(),
            revoked_at timestamptz
        );
        CREATE INDEX auth_sessions_user_idx ON public.auth_sessions(user_id);
        CREATE INDEX auth_sessions_expiry_idx ON public.auth_sessions(expires_at);
        REVOKE ALL ON public.auth_users, public.auth_sessions FROM PUBLIC;
        GRANT SELECT, INSERT, UPDATE, DELETE ON public.auth_users, public.auth_sessions TO flare_app;
    """ + onboarding_role + """
        CREATE FUNCTION public.provision_workspace(new_id uuid, new_name text)
        RETURNS void LANGUAGE plpgsql SECURITY DEFINER
        SET search_path = pg_catalog, public AS $$
        DECLARE caller_id text := nullif(current_setting('app.user_id', true), '');
        BEGIN
            IF caller_id IS NULL THEN RAISE EXCEPTION 'User context required' USING ERRCODE = '42501'; END IF;
            PERFORM set_config('app.workspace_id', new_id::text, true);
            -- No ON CONFLICT: this function can never join an existing workspace.
            INSERT INTO public.workspaces(id, name) VALUES (new_id, new_name);
            INSERT INTO public.workspace_members(workspace_id, user_id, role)
                VALUES (new_id, caller_id, 'owner');
        END;
        $$;
    """ + function_owner + """
        REVOKE ALL ON FUNCTION public.provision_workspace(uuid, text) FROM PUBLIC;
        GRANT EXECUTE ON FUNCTION public.provision_workspace(uuid, text) TO flare_app;
        REVOKE INSERT, UPDATE, DELETE ON public.workspace_members, public.workspaces FROM flare_app;

        -- Non-recursive: membership reads expose only the caller's own row,
        -- still intersected with the original workspace policy.
        CREATE POLICY member_identity ON public.workspace_members AS RESTRICTIVE TO flare_app
            USING (user_id = nullif(current_setting('app.user_id', true), ''));
    """)
    for table in ("workspaces", "documents", "document_versions", "chunks", "insights", "insight_sources"):
        workspace = f"{table}.id" if table == "workspaces" else f"{table}.workspace_id"
        member = f"""EXISTS (SELECT 1 FROM public.workspace_members m
            WHERE m.workspace_id = {workspace}
            AND m.user_id = nullif(current_setting('app.user_id', true), ''))"""
        writer = member[:-1] + " AND m.role IN ('owner', 'editor'))"
        op.execute(f"CREATE POLICY member_access ON public.{table} AS RESTRICTIVE TO flare_app USING ({member})")
        for command in ("INSERT", "UPDATE", "DELETE"):
            check = f"WITH CHECK ({writer})" if command == "INSERT" else f"USING ({writer})"
            if command == "UPDATE":
                check += f" WITH CHECK ({writer})"
            op.execute(f"CREATE POLICY writer_{command.lower()} ON public.{table} AS RESTRICTIVE FOR {command} TO flare_app {check}")


def downgrade():
    raise RuntimeError("Authentication data must not be dropped automatically; restore a reviewed backup.")
