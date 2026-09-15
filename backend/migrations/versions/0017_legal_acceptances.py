"""Record the legal document versions accepted during account creation."""

from alembic import op


revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE public.auth_legal_acceptances (
            user_id text NOT NULL REFERENCES public.auth_users(id) ON DELETE CASCADE,
            terms_version date NOT NULL,
            privacy_version date NOT NULL,
            accepted_at timestamptz NOT NULL DEFAULT now(),
            PRIMARY KEY (user_id, terms_version, privacy_version)
        );
        REVOKE ALL ON public.auth_legal_acceptances FROM PUBLIC;
        GRANT SELECT, INSERT ON public.auth_legal_acceptances TO flare_app;
        """
    )


def downgrade() -> None:
    raise RuntimeError(
        "Legal acceptance records are audit evidence; restore from backup instead."
    )
