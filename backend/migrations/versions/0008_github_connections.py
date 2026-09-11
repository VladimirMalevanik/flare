"""Workspace-scoped GitHub App connections and one-time authorization state."""

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(r"""
        CREATE TABLE public.github_connection_states (
            token_hash text PRIMARY KEY CHECK(token_hash ~ '^[0-9a-f]{64}$'),
            workspace_id uuid NOT NULL REFERENCES public.workspaces(id) ON DELETE CASCADE,
            user_id text NOT NULL REFERENCES public.auth_users(id) ON DELETE CASCADE,
            created_at timestamptz NOT NULL DEFAULT now(),
            expires_at timestamptz NOT NULL,
            consumed_at timestamptz,
            CHECK(expires_at > created_at)
        );
        CREATE INDEX github_connection_states_expiry_idx
            ON public.github_connection_states(expires_at);

        CREATE TABLE public.github_connections (
            workspace_id uuid PRIMARY KEY REFERENCES public.workspaces(id) ON DELETE CASCADE,
            installation_id bigint NOT NULL CHECK(installation_id > 0),
            account_id bigint NOT NULL CHECK(account_id > 0),
            account_login text NOT NULL CHECK(length(account_login) BETWEEN 1 AND 255),
            account_type text NOT NULL CHECK(length(account_type) BETWEEN 1 AND 40),
            authorized_user_id bigint NOT NULL CHECK(authorized_user_id > 0),
            authorized_user_login text NOT NULL CHECK(length(authorized_user_login) BETWEEN 1 AND 255),
            status text NOT NULL CHECK(status IN ('pending', 'connected')),
            repository_id bigint CHECK(repository_id > 0),
            repository_owner text CHECK(length(repository_owner) BETWEEN 1 AND 255),
            repository_name text CHECK(length(repository_name) BETWEEN 1 AND 255),
            repository_full_name text CHECK(length(repository_full_name) BETWEEN 3 AND 511),
            repository_private boolean,
            repository_html_url text CHECK(length(repository_html_url) BETWEEN 1 AND 2048),
            connected_at timestamptz,
            created_at timestamptz NOT NULL DEFAULT now(),
            updated_at timestamptz NOT NULL DEFAULT now(),
            CHECK(
                (status = 'pending' AND repository_id IS NULL AND repository_owner IS NULL
                    AND repository_name IS NULL AND repository_full_name IS NULL
                    AND repository_private IS NULL AND repository_html_url IS NULL
                    AND connected_at IS NULL)
                OR
                (status = 'connected' AND repository_id IS NOT NULL AND repository_owner IS NOT NULL
                    AND repository_name IS NOT NULL AND repository_full_name IS NOT NULL
                    AND repository_private IS NOT NULL AND repository_html_url IS NOT NULL
                    AND connected_at IS NOT NULL)
            )
        );

        ALTER TABLE public.github_connection_states ENABLE ROW LEVEL SECURITY;
        ALTER TABLE public.github_connection_states FORCE ROW LEVEL SECURITY;
        ALTER TABLE public.github_connections ENABLE ROW LEVEL SECURITY;
        ALTER TABLE public.github_connections FORCE ROW LEVEL SECURITY;
        REVOKE ALL ON public.github_connection_states, public.github_connections FROM PUBLIC;
        GRANT SELECT, INSERT, UPDATE, DELETE
            ON public.github_connection_states, public.github_connections TO flare_app;

        CREATE POLICY github_state_reader ON public.github_connection_states
            FOR SELECT TO flare_app USING(
                workspace_id = nullif(current_setting('app.workspace_id', true), '')::uuid
                AND user_id = nullif(current_setting('app.user_id', true), '')
                AND EXISTS(SELECT 1 FROM public.workspace_members m
                    WHERE m.workspace_id = github_connection_states.workspace_id
                    AND m.user_id = github_connection_states.user_id)
            );
        CREATE POLICY github_state_writer ON public.github_connection_states
            FOR ALL TO flare_app USING(
                workspace_id = nullif(current_setting('app.workspace_id', true), '')::uuid
                AND user_id = nullif(current_setting('app.user_id', true), '')
                AND EXISTS(SELECT 1 FROM public.workspace_members m
                    WHERE m.workspace_id = github_connection_states.workspace_id
                    AND m.user_id = github_connection_states.user_id
                    AND m.role IN ('owner', 'editor'))
            ) WITH CHECK(
                workspace_id = nullif(current_setting('app.workspace_id', true), '')::uuid
                AND user_id = nullif(current_setting('app.user_id', true), '')
                AND EXISTS(SELECT 1 FROM public.workspace_members m
                    WHERE m.workspace_id = github_connection_states.workspace_id
                    AND m.user_id = github_connection_states.user_id
                    AND m.role IN ('owner', 'editor'))
            );

        CREATE POLICY github_connection_reader ON public.github_connections
            FOR SELECT TO flare_app USING(
                workspace_id = nullif(current_setting('app.workspace_id', true), '')::uuid
                AND EXISTS(SELECT 1 FROM public.workspace_members m
                    WHERE m.workspace_id = github_connections.workspace_id
                    AND m.user_id = nullif(current_setting('app.user_id', true), ''))
            );
        CREATE POLICY github_connection_writer ON public.github_connections
            FOR ALL TO flare_app USING(
                workspace_id = nullif(current_setting('app.workspace_id', true), '')::uuid
                AND EXISTS(SELECT 1 FROM public.workspace_members m
                    WHERE m.workspace_id = github_connections.workspace_id
                    AND m.user_id = nullif(current_setting('app.user_id', true), '')
                    AND m.role IN ('owner', 'editor'))
            ) WITH CHECK(
                workspace_id = nullif(current_setting('app.workspace_id', true), '')::uuid
                AND EXISTS(SELECT 1 FROM public.workspace_members m
                    WHERE m.workspace_id = github_connections.workspace_id
                    AND m.user_id = nullif(current_setting('app.user_id', true), '')
                    AND m.role IN ('owner', 'editor'))
            );
    """)


def downgrade():
    raise RuntimeError("GitHub connection data requires a reviewed restore plan")
