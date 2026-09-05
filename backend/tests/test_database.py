"""Integration checks for a migrated, disposable PostgreSQL database.

TEST_DATABASE_URL must connect as an administrator allowed to SET ROLE flare_app.
Every test rolls back its changes. No network services or model API calls are used.
"""

import os
from uuid import uuid4

import psycopg
import pytest
from dotenv import load_dotenv
from psycopg import sql
from psycopg.errors import CheckViolation, ForeignKeyViolation, InsufficientPrivilege, UniqueViolation


load_dotenv()
pytestmark = pytest.mark.integration


TABLES = (
    "workspaces",
    "workspace_members",
    "documents",
    "document_versions",
    "chunks",
    "insights",
    "insight_sources",
)


def select_workspace(conn, workspace_id):
    conn.execute(
        "SELECT set_config('app.workspace_id', %s, true)",
        (str(workspace_id) if workspace_id else "",),
    )


@pytest.fixture
def db():
    url = os.environ.get("TEST_DATABASE_URL")
    if not url:
        pytest.skip("Set TEST_DATABASE_URL to run PostgreSQL integration tests")
    with psycopg.connect(url, autocommit=False) as conn:
        try:
            conn.execute("SET LOCAL ROLE flare_app")
            yield conn
        finally:
            conn.rollback()


def add_version(conn, workspace_id, document_id, number, *, ready=True, content="Evidence", embedding_model=None):
    version_id, chunk_id = uuid4(), uuid4()
    conn.execute(
        """INSERT INTO public.document_versions
           (id, workspace_id, document_id, version_number, content_hash, parser_version)
           VALUES (%s, %s, %s, %s, %s, 'test-parser-v1')""",
        (version_id, workspace_id, document_id, number, f"{number:064x}"),
    )
    conn.execute(
        """INSERT INTO public.chunks
           (id, workspace_id, document_version_id, ordinal, content, locator)
           VALUES (%s, %s, %s, 0, %s, '{"page": 1}')""",
        (chunk_id, workspace_id, version_id, content),
    )
    if embedding_model:
        conn.execute(
            "UPDATE public.chunks SET embedding = %s::vector, embedding_model = %s WHERE id = %s",
            ("[" + ",".join(["0.1"] * 1536) + "]", embedding_model, chunk_id),
        )
    if ready:
        conn.execute("UPDATE public.document_versions SET state = 'ready' WHERE id = %s", (version_id,))
    return version_id, chunk_id


@pytest.fixture
def tenants(db):
    result = []
    for name in ("Alpha", "Beta"):
        workspace_id, document_id, insight_id = uuid4(), uuid4(), uuid4()
        select_workspace(db, workspace_id)
        db.execute("INSERT INTO public.workspaces (id, name) VALUES (%s, %s)", (workspace_id, name))
        db.execute(
            "INSERT INTO public.workspace_members (workspace_id, user_id, role) VALUES (%s, %s, 'owner')",
            (workspace_id, f"test-auth|{workspace_id}"),
        )
        db.execute(
            "INSERT INTO public.documents (id, workspace_id, title, source_type) VALUES (%s, %s, %s, 'file')",
            (document_id, workspace_id, name),
        )
        version_id, chunk_id = add_version(db, workspace_id, document_id, 1, content=f"{name} evidence v1")
        db.execute("UPDATE public.documents SET current_version_id = %s WHERE id = %s", (version_id, document_id))
        db.execute(
            """INSERT INTO public.insights
               (id, workspace_id, title, summary, body, model, prompt_version)
               VALUES (%s, %s, %s, %s, %s, 'test-model', 'v1')""",
            (
                insight_id,
                workspace_id,
                f"{name} insight",
                f"{name} summary",
                f"{name} insight",
            ),
        )
        db.execute(
            "INSERT INTO public.insight_sources (workspace_id, insight_id, chunk_id) VALUES (%s, %s, %s)",
            (workspace_id, insight_id, chunk_id),
        )
        result.append(dict(workspace=workspace_id, document=document_id, version=version_id, chunk=chunk_id, insight=insight_id))
    select_workspace(db, result[0]["workspace"])
    return result


def test_runtime_role_cannot_bypass_rls(db):
    row = db.execute(
        "SELECT rolname, rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user"
    ).fetchone()
    assert row == ("flare_app", False, False)


@pytest.mark.parametrize("table", TABLES)
def test_every_table_is_tenant_filtered(db, tenants, table):
    workspace_column = "id" if table == "workspaces" else "workspace_id"
    rows = db.execute(sql.SQL("SELECT {} FROM public.{}").format(sql.Identifier(workspace_column), sql.Identifier(table))).fetchall()
    assert rows == [(tenants[0]["workspace"],)]


def test_missing_context_denies_reads_and_writes(db, tenants):
    select_workspace(db, None)
    for table in TABLES:
        assert db.execute(sql.SQL("SELECT count(*) FROM public.{}").format(sql.Identifier(table))).fetchone()[0] == 0
    with pytest.raises(InsufficientPrivilege):
        with db.transaction():
            db.execute("INSERT INTO public.workspaces (name) VALUES ('Blocked')")


def test_known_foreign_id_cannot_be_changed_or_selected(db, tenants):
    foreign_id = tenants[1]["document"]
    assert db.execute("SELECT id FROM public.documents WHERE id = %s", (foreign_id,)).fetchall() == []
    assert db.execute("UPDATE public.documents SET title = 'Changed' WHERE id = %s", (foreign_id,)).rowcount == 0
    assert db.execute("DELETE FROM public.documents WHERE id = %s", (foreign_id,)).rowcount == 0
    with pytest.raises(InsufficientPrivilege):
        with db.transaction():
            db.execute(
                "INSERT INTO public.documents (workspace_id, title, source_type) VALUES (%s, 'Blocked', 'note')",
                (tenants[1]["workspace"],),
            )


def test_cross_tenant_parent_reference_is_rejected(db, tenants):
    a, b = tenants
    with pytest.raises(ForeignKeyViolation):
        with db.transaction():
            db.execute(
                """INSERT INTO public.document_versions
                   (workspace_id, document_id, version_number, content_hash, parser_version)
                   VALUES (%s, %s, 2, %s, 'v1')""",
                (a["workspace"], b["document"], "a" * 64),
            )
    with pytest.raises(ForeignKeyViolation):
        with db.transaction():
            db.execute(
                "INSERT INTO public.insight_sources (workspace_id, insight_id, chunk_id) VALUES (%s, %s, %s)",
                (a["workspace"], a["insight"], b["chunk"]),
            )


@pytest.mark.parametrize("operation", ("update_version", "delete_version", "update_chunk", "delete_chunk", "append_chunk"))
def test_ready_snapshots_are_immutable(db, tenants, operation):
    a = tenants[0]
    statements = {
        "update_version": ("UPDATE public.document_versions SET state = 'processing' WHERE id = %s", (a["version"],)),
        "delete_version": ("DELETE FROM public.document_versions WHERE id = %s", (a["version"],)),
        "update_chunk": ("UPDATE public.chunks SET content = 'Changed' WHERE id = %s", (a["chunk"],)),
        "delete_chunk": ("DELETE FROM public.chunks WHERE id = %s", (a["chunk"],)),
        "append_chunk": (
            "INSERT INTO public.chunks (workspace_id, document_version_id, ordinal, content) VALUES (%s, %s, 1, 'Late chunk')",
            (a["workspace"], a["version"]),
        ),
    }
    with pytest.raises(CheckViolation):
        with db.transaction():
            db.execute(*statements[operation])


def test_current_version_must_be_ready_and_belong_to_document(db, tenants):
    a, b = tenants
    pending_version, _ = add_version(db, a["workspace"], a["document"], 2, ready=False)
    with pytest.raises(CheckViolation):
        with db.transaction():
            db.execute("UPDATE public.documents SET current_version_id = %s WHERE id = %s", (pending_version, a["document"]))
    with pytest.raises(ForeignKeyViolation):
        with db.transaction():
            db.execute("UPDATE public.documents SET current_version_id = %s WHERE id = %s", (b["version"], a["document"]))
    assert db.execute("SELECT current_version_id FROM public.documents WHERE id = %s", (a["document"],)).fetchone()[0] == a["version"]


def test_citation_keeps_original_snapshot_after_new_publication(db, tenants):
    a = tenants[0]
    new_version, _ = add_version(db, a["workspace"], a["document"], 2, content="Alpha evidence v2")
    db.execute("UPDATE public.documents SET current_version_id = %s WHERE id = %s", (new_version, a["document"]))
    row = db.execute(
        """SELECT c.document_version_id, c.content FROM public.insight_sources s
           JOIN public.chunks c ON (c.workspace_id, c.id) = (s.workspace_id, s.chunk_id)
           WHERE s.insight_id = %s""",
        (a["insight"],),
    ).fetchone()
    assert row == (a["version"], "Alpha evidence v1")


def test_retrieval_uses_only_current_ready_active_sources(db, tenants):
    a = tenants[0]
    new_version, new_chunk = add_version(db, a["workspace"], a["document"], 2)
    db.execute("UPDATE public.documents SET current_version_id = %s WHERE id = %s", (new_version, a["document"]))
    add_version(db, a["workspace"], a["document"], 3, ready=False)
    # Embeddings remain optional until the worker supplies a real model. The same
    # filtering predicates must precede ORDER BY embedding <=> query LIMIT k.
    retrieval = """SELECT c.id FROM public.chunks c
        JOIN public.document_versions v
          ON (v.workspace_id, v.id) = (c.workspace_id, c.document_version_id)
        JOIN public.documents d
          ON (d.workspace_id, d.id, d.current_version_id) = (v.workspace_id, v.document_id, v.id)
        WHERE c.workspace_id = %s AND v.state = 'ready' AND d.deleted_at IS NULL"""
    assert db.execute(retrieval, (a["workspace"],)).fetchall() == [(new_chunk,)]
    assert db.execute(retrieval, (tenants[1]["workspace"],)).fetchall() == []
    db.execute("UPDATE public.documents SET deleted_at = now() WHERE id = %s", (a["document"],))
    assert db.execute(retrieval, (a["workspace"],)).fetchall() == []


def test_vector_retrieval_filters_workspace_version_and_embedding_model(db, tenants):
    a, b = tenants
    model = "test-embedding-v1"
    query_vector = "[" + ",".join(["0.1"] * 1536) + "]"
    # Both tenants have relevant embeddings. All vectors deliberately have
    # equal distance, so an accidental tenant/version leak cannot hide in ranking.
    select_workspace(db, b["workspace"])
    foreign_version, _ = add_version(db, b["workspace"], b["document"], 2, embedding_model=model)
    db.execute("UPDATE public.documents SET current_version_id = %s WHERE id = %s", (foreign_version, b["document"]))
    select_workspace(db, a["workspace"])
    add_version(db, a["workspace"], a["document"], 2, embedding_model=model)
    current_version, current_chunk = add_version(db, a["workspace"], a["document"], 3, embedding_model=model)
    db.execute("UPDATE public.documents SET current_version_id = %s WHERE id = %s", (current_version, a["document"]))
    add_version(db, a["workspace"], a["document"], 4, ready=False, embedding_model=model)

    other_document = uuid4()
    db.execute(
        "INSERT INTO public.documents (id, workspace_id, title, source_type) VALUES (%s, %s, 'Other model', 'note')",
        (other_document, a["workspace"]),
    )
    other_version, _ = add_version(db, a["workspace"], other_document, 1, embedding_model="test-embedding-v2")
    db.execute("UPDATE public.documents SET current_version_id = %s WHERE id = %s", (other_version, other_document))

    retrieval = """SELECT c.id, c.embedding <=> %s::vector AS distance
        FROM public.chunks c
        JOIN public.document_versions v
          ON (v.workspace_id, v.id) = (c.workspace_id, c.document_version_id)
        JOIN public.documents d
          ON (d.workspace_id, d.id, d.current_version_id) = (v.workspace_id, v.document_id, v.id)
        WHERE c.workspace_id = %s AND c.embedding_model = %s
          AND c.embedding IS NOT NULL AND v.state = 'ready' AND d.deleted_at IS NULL
        ORDER BY c.embedding <=> %s::vector LIMIT 5"""
    rows = db.execute(retrieval, (query_vector, a["workspace"], model, query_vector)).fetchall()
    assert [row[0] for row in rows] == [current_chunk]
    assert rows[0][1] == pytest.approx(0, abs=1e-6)
    assert db.execute(retrieval, (query_vector, b["workspace"], model, query_vector)).fetchall() == []
    db.execute("UPDATE public.documents SET deleted_at = now() WHERE id = %s", (a["document"],))
    assert db.execute(retrieval, (query_vector, a["workspace"], model, query_vector)).fetchall() == []


def test_retry_does_not_duplicate_chunks(db, tenants):
    a = tenants[0]
    version_id, _ = add_version(db, a["workspace"], a["document"], 2, ready=False)
    with pytest.raises(UniqueViolation):
        with db.transaction():
            db.execute(
                "INSERT INTO public.chunks (workspace_id, document_version_id, ordinal, content) VALUES (%s, %s, 0, 'Duplicate')",
                (a["workspace"], version_id),
            )


def test_embedding_requires_model_metadata(db, tenants):
    a = tenants[0]
    _, chunk_id = add_version(db, a["workspace"], a["document"], 2, ready=False)
    vector = "[" + ",".join(["0.1"] * 1536) + "]"
    with pytest.raises(CheckViolation):
        with db.transaction():
            db.execute("UPDATE public.chunks SET embedding = %s::vector WHERE id = %s", (vector, chunk_id))
    db.execute(
        "UPDATE public.chunks SET embedding = %s::vector, embedding_model = 'test-embedding-model' WHERE id = %s",
        (vector, chunk_id),
    )


def test_frontend_contract_fields_are_persisted(db, tenants):
    workspace_id = tenants[0]["workspace"]
    document_id, insight_id = uuid4(), uuid4()
    db.execute(
        """INSERT INTO public.documents
           (id, workspace_id, title, source_type, metadata)
           VALUES (%s, %s, 'Voice memo', 'audio', '{"duration_seconds": 42}')""",
        (document_id, workspace_id),
    )
    db.execute(
        """INSERT INTO public.insights
           (id, workspace_id, title, summary, body, kind, detail_title,
            model, prompt_version)
           VALUES (%s, %s, 'Repeated objection', 'Price appears repeatedly',
                   'Three interviews mention price.', 'Repeated Problem',
                   'Evidence', 'test-model', 'v1')""",
        (insight_id, workspace_id),
    )
    assert db.execute(
        "SELECT source_type, metadata->>'duration_seconds' FROM public.documents WHERE id = %s",
        (document_id,),
    ).fetchone() == ("audio", "42")
    assert db.execute(
        "SELECT title, summary, kind, detail_title FROM public.insights WHERE id = %s",
        (insight_id,),
    ).fetchone() == (
        "Repeated objection",
        "Price appears repeatedly",
        "Repeated Problem",
        "Evidence",
    )


def test_workspace_setting_does_not_escape_transaction(db, tenants):
    # A rollback is safe: this connection and all its fixture data belong to this test.
    db.rollback()
    db.execute("SET LOCAL ROLE flare_app")
    assert db.execute("SELECT nullif(current_setting('app.workspace_id', true), '')").fetchone()[0] is None
