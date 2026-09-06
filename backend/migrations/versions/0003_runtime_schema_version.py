"""Allow the restricted runtime role to verify the applied schema revision."""

from alembic import op


revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("GRANT SELECT ON public.alembic_version TO flare_app")


def downgrade():
    op.execute("REVOKE SELECT ON public.alembic_version FROM flare_app")
