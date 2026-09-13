"""Integration coverage for bounded, tenant-safe text imports."""

from __future__ import annotations

import os
from uuid import UUID, uuid4

import pytest

from test_items_api import ApiEnvironment


pytestmark = pytest.mark.integration


@pytest.fixture
def api_environment():
    runtime_url = os.environ.get("DATABASE_URL")
    admin_url = os.environ.get("TEST_DATABASE_URL")
    if not runtime_url or not admin_url:
        pytest.skip("DATABASE_URL and TEST_DATABASE_URL are required for import API tests")
    environment = ApiEnvironment(runtime_url, admin_url)
    try:
        yield environment
    finally:
        environment.cleanup()


def _post_import(client, *, format: str, file_name: str, content: str, file_type: str | None = None):
    payload = {
        "format": format,
        "fileName": file_name,
        "fileSize": len(content.encode("utf-8")),
        "content": content,
    }
    if file_type is not None:
        payload["fileType"] = file_type
    return client.post("/imports", json=payload)


def test_csv_import_persists_exact_text_locators_and_bounded_jobs(api_environment, monkeypatch):
    # Force multiple chunks/jobs so the test proves the worker's hard limits
    # are respected rather than merely exercising the single-chunk happy path.
    monkeypatch.setenv("LLM_MAX_INPUT_BYTES", "80")
    monkeypatch.setenv("LLM_MAX_SOURCES", "2")
    monkeypatch.setenv("ANALYSIS_LEASE_SECONDS", "120")
    source = (
        "company,signal\n"
        "Acme,Customers need faster onboarding to invite their team\n"
        "Beta,Founders are asking for a clean export every week\n"
        "Coda,Teams want one place for interview evidence and decisions\n"
    )
    workspace_id, user_id = uuid4(), f"import-test|{uuid4()}"
    with api_environment.client(workspace_id=workspace_id, user_id=user_id) as client:
        response = _post_import(
            client,
            format="csv",
            file_name="signals.csv",
            file_type="application/octet-stream",
            content=source,
        )
        assert response.status_code == 201, response.text
        result = response.json()
        assert result["format"] == "csv"
        assert result["fileName"] == "signals.csv"
        assert result["rowCount"] == 3
        assert result["chunkCount"] >= 3
        assert result["analysisJobsQueued"] >= 2
        assert result["item"]["type"] == "file"
        assert result["item"]["content"] == source
        assert result["item"]["fileType"] == "application/octet-stream"

        fetched = client.get(f"/imports/{result['id']}")
        assert fetched.status_code == 200
        assert fetched.json() == result

    batch_id = UUID(result["id"])
    item_id = UUID(result["item"]["id"])
    persisted = api_environment.fetchone_admin(
        """SELECT b.format, b.file_name, b.file_size, b.row_count, b.chunk_count,
                  b.analysis_jobs_queued, b.document_id, v.parser_version,
                  string_agg(c.content, '' ORDER BY c.ordinal)
             FROM public.import_batches b
             JOIN public.document_versions v
               ON (v.workspace_id, v.document_id) = (b.workspace_id, b.document_id)
             JOIN public.chunks c
               ON (c.workspace_id, c.document_version_id) = (v.workspace_id, v.id)
            WHERE b.workspace_id = %s AND b.id = %s AND v.id = (
                SELECT current_version_id FROM public.documents WHERE id = b.document_id
            )
            GROUP BY b.id, v.id""",
        (workspace_id, batch_id),
    )
    assert persisted == (
        "csv",
        "signals.csv",
        len(source.encode("utf-8")),
        3,
        result["chunkCount"],
        result["analysisJobsQueued"],
        item_id,
        "import-csv-v1",
        source,
    )
    locator_rows = api_environment.fetchone_admin(
        """SELECT count(*) FILTER (WHERE locator->>'format' = 'csv'),
                  min((locator->>'rowStart')::integer),
                  max((locator->>'rowEnd')::integer)
             FROM public.chunks c
             JOIN public.document_versions v ON v.id = c.document_version_id
            WHERE v.document_id = %s""",
        (item_id,),
    )
    assert locator_rows == (result["chunkCount"], 1, 4)
    job_bounds = api_environment.fetchone_admin(
        """SELECT max(source_count), max(source_bytes), count(*)
             FROM (
                SELECT j.id, count(*)::int AS source_count,
                       sum(octet_length(c.content))::int AS source_bytes
                  FROM public.analysis_jobs j
                  JOIN public.analysis_job_sources s
                    ON (s.workspace_id, s.job_id) = (j.workspace_id, j.id)
                  JOIN public.chunks c
                    ON (c.workspace_id, c.id) = (s.workspace_id, s.chunk_id)
                 WHERE j.workspace_id = %s
                 GROUP BY j.id
             ) grouped""",
        (workspace_id,),
    )
    assert job_bounds[0] <= 2
    assert job_bounds[1] <= 80
    assert job_bounds[2] == result["analysisJobsQueued"]


def test_markdown_import_keeps_content_and_section_boundaries(api_environment, monkeypatch):
    monkeypatch.setenv("LLM_MAX_INPUT_BYTES", "120")
    monkeypatch.setenv("LLM_MAX_SOURCES", "2")
    source = "# Market\nTeams need cited answers.\n\n## Interviews\nOnboarding is the recurring pain.\n"
    with api_environment.client() as client:
        response = _post_import(
            client,
            format="md",
            file_name="research.md",
            file_type="text/markdown",
            content=source,
        )
        assert response.status_code == 201, response.text
        result = response.json()
        assert result["rowCount"] is None
        assert result["item"]["content"] == source

    sections = api_environment.fetchone_admin(
        """SELECT count(*), bool_or(locator->>'section' = 'Market'),
                  bool_or(locator->>'section' = 'Interviews')
             FROM public.chunks c
             JOIN public.document_versions v ON v.id = c.document_version_id
            WHERE v.document_id = %s""",
        (UUID(result["item"]["id"]),),
    )
    assert sections == (result["chunkCount"], True, True)


def test_import_rejects_invalid_csv_unsupported_format_and_byte_overflow(api_environment):
    with api_environment.client() as client:
        invalid_csv = _post_import(
            client,
            format="csv",
            file_name="broken.csv",
            content='name,signal\n"unterminated\n',
        )
        assert invalid_csv.status_code == 422
        assert "unterminated" not in str(invalid_csv.json())

        wrong_extension = _post_import(
            client,
            format="csv",
            file_name="not-a-csv.txt",
            content="name,signal\nAcme,Fast\n",
        )
        assert wrong_extension.status_code == 422

        binary_text = _post_import(
            client,
            format="txt",
            file_name="not-text.txt",
            content="safe\x00bytes",
        )
        assert binary_text.status_code == 422
        assert "safe" not in str(binary_text.json())

        too_many_bytes = _post_import(
            client,
            format="txt",
            file_name="unicode.txt",
            content="é" * 100_001,
        )
        assert too_many_bytes.status_code == 422
        assert too_many_bytes.json()["detail"] == "content exceeds the 200,000-byte import limit"

        assert client.get("/items").json() == []


def test_import_is_idempotent_per_workspace_and_format_and_isolated(api_environment):
    source = "A decision log with real source text.\n"
    workspace_a, workspace_b = uuid4(), uuid4()
    user_a, user_b = f"import-test|{uuid4()}", f"import-test|{uuid4()}"
    with api_environment.client(workspace_id=workspace_a, user_id=user_a) as client_a:
        first = _post_import(client_a, format="txt", file_name="decisions.txt", content=source)
        assert first.status_code == 201, first.text
        duplicate = _post_import(client_a, format="txt", file_name="renamed.txt", content=source)
        assert duplicate.status_code == 200, duplicate.text
        assert duplicate.json() == first.json()
        first_result = first.json()

    with api_environment.client(workspace_id=workspace_b, user_id=user_b) as client_b:
        other = _post_import(client_b, format="txt", file_name="decisions.txt", content=source)
        assert other.status_code == 201, other.text
        assert other.json()["id"] != first_result["id"]
        assert client_b.get(f"/imports/{first_result['id']}").status_code == 404

    with api_environment.client(workspace_id=workspace_a, user_id=user_a) as client_a:
        assert client_a.get(f"/imports/{other.json()['id']}").status_code == 404
        # The same bytes have a separate canonical batch when parsed as Markdown.
        as_markdown = _post_import(client_a, format="md", file_name="decisions.md", content=source)
        assert as_markdown.status_code == 201, as_markdown.text
        assert as_markdown.json()["id"] != first_result["id"]

    assert api_environment.fetchone_admin(
        "SELECT count(*) FROM public.import_batches WHERE workspace_id = %s",
        (workspace_a,),
    ) == (2,)
    assert api_environment.fetchone_admin(
        "SELECT count(*) FROM public.import_batches WHERE workspace_id = %s",
        (workspace_b,),
    ) == (1,)
