"""Workspace export authorization, isolation, and archive-content checks."""

from io import BytesIO
import json
from uuid import uuid4
from zipfile import ZipFile

import psycopg
import pytest

from test_items_api import ApiEnvironment, _create_note


pytestmark = pytest.mark.integration


@pytest.fixture
def api_environment():
    from test_items_api import _required_urls

    runtime_url, admin_url = _required_urls()
    environment = ApiEnvironment(runtime_url, admin_url)
    try:
        yield environment
    finally:
        environment.cleanup()


def test_owner_export_is_portable_tenant_scoped_and_excludes_secrets(api_environment):
    first_workspace, second_workspace = uuid4(), uuid4()
    first_user, second_user = f"api-test|{uuid4()}", f"api-test|{uuid4()}"

    with api_environment.client(workspace_id=first_workspace, user_id=first_user) as client:
        note = _create_note(client, title="First workspace plan", content="Portable context")
        with psycopg.connect(api_environment.admin_url) as connection:
            connection.execute("SET LOCAL session_replication_role=replica")
            connection.execute(
                """UPDATE public.document_versions
                      SET snapshot_metadata=snapshot_metadata || %s::jsonb
                    WHERE id=%s""",
                (json.dumps({"fileName": "plan.md", "githubToken": "do-not-export"}), note["currentVersionId"]),
            )
    with api_environment.client(workspace_id=second_workspace, user_id=second_user) as client:
        _create_note(client, title="Other tenant secret title", content="Cross-tenant content")

    with api_environment.client(workspace_id=first_workspace, user_id=first_user) as client:
        response = client.get("/export")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert response.headers["cache-control"] == "no-store"
    assert "flare-export-" in response.headers["content-disposition"]
    with ZipFile(BytesIO(response.content)) as archive:
        names = archive.namelist()
        assert {"README.md", "workspace.json", "raw/export.json"}.issubset(names)
        note_name = next(name for name in names if name.startswith("notes/"))
        assert "First workspace plan" in archive.read(note_name).decode()
        raw = archive.read("raw/export.json").decode()
        assert "First workspace plan" in raw
        assert '"fileName": "plan.md"' in raw
        assert "Other tenant secret title" not in raw
        assert "githubToken" not in raw
        assert "do-not-export" not in raw


def test_export_requires_workspace_owner(api_environment):
    workspace_id, user_id = uuid4(), f"api-test|{uuid4()}"
    with api_environment.client(workspace_id=workspace_id, user_id=user_id) as client:
        _create_note(client)
        api_environment.execute_admin(
            "UPDATE public.workspace_members SET role='editor' WHERE workspace_id=%s AND user_id=%s",
            (workspace_id, user_id),
        )
        assert client.get("/export").status_code == 403
