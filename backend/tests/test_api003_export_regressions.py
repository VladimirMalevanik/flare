"""Exports remain one tenant-scoped snapshot while other requests commit edits."""

from io import BytesIO
import json
from uuid import uuid4
from zipfile import ZipFile

import pytest

from app.models.database import MembershipRequiredError, WorkspaceIdentity
from app.services import export_service
from app.services.export_service import WorkspaceExportService
from test_export_api import api_environment  # noqa: F401
from test_items_api import _create_note


pytestmark = pytest.mark.integration


@pytest.mark.parametrize("change", ["edit", "delete", "create"])
def test_export_keeps_snapshot_across_pages_and_formats(api_environment, monkeypatch, change):
    monkeypatch.setattr(export_service, "PAGE_SIZE", 1)
    workspace, user = uuid4(), f"api003-export|{uuid4()}"
    with api_environment.client(workspace_id=workspace, user_id=user) as client:
        notes = sorted(
            [_create_note(client, title=f"Plan {i}", content=f"Original content {i}") for i in range(3)],
            key=lambda note: note["id"],
        )
        original_name = client.get("/auth/me").json()["workspace"]["name"]
        target = notes[-1]

        class ConcurrentExport(WorkspaceExportService):
            changed = False

            def _items(self, connection):
                for item in super()._items(connection):
                    yield item
                    if self.changed:
                        continue
                    self.changed = True
                    # A separate HTTP request commits while this export still
                    # has two pages left to read and has not written JSON yet.
                    if change == "edit":
                        response = client.patch(f"/items/{target['id']}", json={
                            "expectedCurrentVersionId": target["currentVersionId"],
                            "title": "Concurrent title",
                            "content": "Concurrent edit",
                        })
                        assert response.status_code == 200, response.text
                    elif change == "delete":
                        assert client.delete(f"/items/{target['id']}").status_code == 204
                    else:
                        _create_note(client, title="Concurrent new note", content="New content")
                    api_environment.execute_admin(
                        "UPDATE public.workspaces SET name='Concurrent workspace name' WHERE id=%s",
                        (workspace,),
                    )

        database = client.app.state.database
        identity = WorkspaceIdentity(workspace, user)
        export = ConcurrentExport(database, identity).build()
        with ZipFile(BytesIO(b"".join(export.chunks()))) as archive:
            raw = json.loads(archive.read("raw/export.json"))
            workspace_json = json.loads(archive.read("workspace.json"))
            assert raw["workspace"] == workspace_json
            assert workspace_json["name"] == original_name
            assert len(raw["notes"]) == len(notes)
            assert {note["id"] for note in raw["notes"]} == {note["id"] for note in notes}
            for note in notes:
                exported = next(row for row in raw["notes"] if row["id"] == note["id"])
                assert exported["content"] == note["content"]
                assert exported["title"] == note["title"]
                assert exported["currentVersionId"] == note["currentVersionId"]
                name = next(name for name in archive.namelist() if name.startswith(f"notes/{note['id']}-"))
                markdown = archive.read(name).decode()
                assert note["content"] in markdown
                assert note["title"] in markdown
                assert note["currentVersionId"] in markdown
                assert "Concurrent" not in markdown
        assert api_environment.fetchone_admin(
            "SELECT name FROM public.workspaces WHERE id=%s", (workspace,)
        ) == ("Concurrent workspace name",)
        # The option is local to the export transaction, including pooled
        # connections subsequently reused for ordinary write-capable requests.
        with database.workspace_transaction(identity) as connection:
            assert connection.execute("SHOW transaction_isolation").fetchone()["transaction_isolation"] == "read committed"
            assert connection.execute("SHOW transaction_read_only").fetchone()["transaction_read_only"] == "off"
        _create_note(client, content="Write still succeeds after export")


def test_snapshot_still_requires_membership_and_rejects_writes(api_environment):
    workspace, user = uuid4(), f"api003-export|{uuid4()}"
    with api_environment.client(workspace_id=workspace, user_id=user) as client:
        database = client.app.state.database
        identity = WorkspaceIdentity(workspace, user)
        with pytest.raises(ValueError, match="read-only"):
            with database.workspace_transaction(identity, write=True, snapshot=True):
                pytest.fail("A write snapshot must not be entered")
        with pytest.raises(MembershipRequiredError):
            with database.workspace_transaction(WorkspaceIdentity(workspace, str(uuid4())), snapshot=True):
                pytest.fail("A foreign identity must not obtain an export snapshot")
