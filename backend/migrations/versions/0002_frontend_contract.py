"""Align persisted documents and insights with the frontend domain contract."""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        "ALTER TABLE public.documents "
        "DROP CONSTRAINT documents_source_type_check, "
        "ADD CONSTRAINT documents_source_type_check "
        "CHECK (source_type IN ('file', 'url', 'note', 'audio')), "
        "ADD COLUMN metadata jsonb NOT NULL DEFAULT '{}'::jsonb "
        "CHECK (jsonb_typeof(metadata) = 'object')"
    )
    op.execute(
        "ALTER TABLE public.insights "
        "ADD COLUMN title text, "
        "ADD COLUMN summary text, "
        "ADD COLUMN kind text, "
        "ADD COLUMN detail_title text"
    )
    op.execute(
        "UPDATE public.insights SET title = left(body, 120), summary = body "
        "WHERE title IS NULL OR summary IS NULL"
    )
    op.execute(
        "ALTER TABLE public.insights "
        "ALTER COLUMN title SET NOT NULL, "
        "ALTER COLUMN summary SET NOT NULL, "
        "ADD CONSTRAINT insights_title_not_blank CHECK (length(btrim(title)) > 0), "
        "ADD CONSTRAINT insights_summary_not_blank CHECK (length(btrim(summary)) > 0), "
        "ADD CONSTRAINT insights_kind_check CHECK (kind IS NULL OR kind IN ("
        "'Contradiction', 'Repeated Problem', 'Hidden Connection', "
        "'Unresolved Question'))"
    )


def downgrade():
    op.execute(
        "ALTER TABLE public.insights "
        "DROP CONSTRAINT insights_kind_check, "
        "DROP CONSTRAINT insights_summary_not_blank, "
        "DROP CONSTRAINT insights_title_not_blank, "
        "DROP COLUMN detail_title, DROP COLUMN kind, "
        "DROP COLUMN summary, DROP COLUMN title"
    )
    op.execute(
        "ALTER TABLE public.documents DROP COLUMN metadata, "
        "DROP CONSTRAINT documents_source_type_check, "
        "ADD CONSTRAINT documents_source_type_check "
        "CHECK (source_type IN ('file', 'url', 'note'))"
    )
