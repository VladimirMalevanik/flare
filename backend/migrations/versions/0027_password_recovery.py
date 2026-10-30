"""Add private, one-use password recovery without changing existing credentials."""

from alembic import op

revision = "0027"
down_revision = "0026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE public.auth_users ADD COLUMN password_reset_requested_at timestamptz;
        CREATE TABLE public.auth_password_resets (
            token_hash text PRIMARY KEY CHECK (token_hash ~ '^[0-9a-f]{64}$'),
            user_id text NOT NULL REFERENCES public.auth_users(id) ON DELETE CASCADE,
            email text NOT NULL CHECK (email=lower(btrim(email))),
            created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
            expires_at timestamptz NOT NULL CHECK (expires_at > created_at),
            sent_at timestamptz
        );
        CREATE INDEX auth_password_resets_user_idx ON public.auth_password_resets(user_id);
        REVOKE ALL ON public.auth_password_resets FROM PUBLIC, flare_app, flare_worker;
        GRANT SELECT, INSERT, UPDATE, DELETE ON public.auth_password_resets TO flare_app;
    """)


def downgrade() -> None:
    raise RuntimeError("Password recovery contains security state; restore a reviewed backup instead.")
