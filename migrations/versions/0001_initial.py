"""Initial knowledge schema with tenant isolation and source versions."""
from pathlib import Path

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    # Treat this SQL file as immutable after release; add a new migration for changes.
    schema = Path(__file__).resolve().parents[2] / "db" / "schema.sql"
    op.execute(schema.read_text(encoding="utf-8"))
    op.execute("GRANT USAGE ON SCHEMA public TO flare_app")
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON "
        "workspaces, workspace_members, documents, document_versions, "
        "chunks, insights, insight_sources TO flare_app"
    )


def downgrade():
    raise RuntimeError("This initial migration contains customer data; restore a backup instead.")

