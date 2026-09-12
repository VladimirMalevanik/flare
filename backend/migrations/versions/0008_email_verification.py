"""email verification

Revision ID: 0008
Revises: 0007
"""
from alembic import op
import sqlalchemy as sa


revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "auth_users",
        sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_table(
        "auth_email_verifications",
        sa.Column("token_hash", sa.Text, primary_key=True),
        sa.Column("user_id", sa.Text, nullable=False),
        sa.Column("email", sa.Text, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["auth_users.id"],
            ondelete="CASCADE",
        ),
    )
    op.create_check_constraint(
        "auth_email_verifications_token_hash_check",
        "auth_email_verifications",
        "token_hash ~ '^[0-9a-f]{64}$'",
    )
    op.create_check_constraint(
        "auth_email_verifications_email_check",
        "auth_email_verifications",
        "email = lower(btrim(email))",
    )

    op.create_index(
        "auth_email_verifications_user_active_idx",
        "auth_email_verifications",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("consumed_at IS NULL"),
    )

    # Users created before this migration have already used the product and
    # must retain access. New registrations omit the nullable column and start
    # unverified when verification is enabled.
    op.execute(
        "UPDATE public.auth_users SET email_verified_at=now() "
        "WHERE email_verified_at IS NULL"
    )
    op.execute("REVOKE ALL ON public.auth_email_verifications FROM PUBLIC")
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE "
        "ON public.auth_email_verifications TO flare_app"
    )


def downgrade() -> None:
    op.execute("REVOKE ALL ON public.auth_email_verifications FROM flare_app")
    op.drop_index(
        "auth_email_verifications_user_active_idx",
        table_name="auth_email_verifications",
    )
    op.drop_table("auth_email_verifications")
    op.drop_column("auth_users", "email_verified_at")
