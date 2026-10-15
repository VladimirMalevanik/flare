"""Adversarial release regressions: no real provider, email or production data."""

from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.api.schemas import CreateItemRequest, UpdateItemRequest
from test_items_api import api_environment  # noqa: F401


@pytest.mark.parametrize("schema,extra", [
    (CreateItemRequest, {"type": "note", "content": "Valid note"}),
    (UpdateItemRequest, {"expectedCurrentVersionId": str(uuid4())}),
])
@pytest.mark.parametrize("field", ["title", "content", "sourceUrl", "fileName", "fileType"])
@pytest.mark.parametrize("invalid", ["before\x00after", "before\ud800after"])
def test_item_contract_rejects_non_postgresql_text(schema, extra, field, invalid):
    with pytest.raises(ValidationError):
        schema.model_validate({**extra, field: invalid})


@pytest.mark.integration
@pytest.mark.parametrize("text", [
    "Release decision: finish the release this week.\n" * 1100,
    "Решение: закончить выпуск на этой неделе. 🌍\n" * 800,
])
def test_long_manual_note_remains_exact_and_has_bounded_analyzable_chunks(api_environment, text):
    with api_environment.client() as client:
        response = client.post("/items", json={"type": "note", "title": "Long release notes", "content": text})
        assert response.status_code == 201
        item = response.json()
        normalized = text.strip()
        assert item["content"] == normalized
        assert client.get(f"/items/{item['id']}").json()["content"] == normalized
        rows = api_environment.fetchone_admin("""
            SELECT count(*), max(octet_length(content)), string_agg(content,'' ORDER BY ordinal)
            FROM public.chunks WHERE document_version_id=%s
        """, (item["currentVersionId"],))
        assert rows[0] > 1, "a long capture must not be one permanently ineligible source"
        assert rows[1] <= 4000
        assert rows[2] == normalized
        revision = client.patch(f"/items/{item['id']}", json={
            "expectedCurrentVersionId": item["currentVersionId"],
            "content": normalized + "\nFinal decision: release next Friday.",
        })
        assert revision.status_code == 200
        updated = revision.json()
        assert updated["versionNumber"] == 2
        assert updated["content"] == normalized + "\nFinal decision: release next Friday."
        bounds = api_environment.fetchone_admin("""
            SELECT count(*),max(octet_length(content)),string_agg(content,'' ORDER BY ordinal)
            FROM public.chunks WHERE document_version_id=%s
        """, (updated["currentVersionId"],))
        assert bounds[0] > 1 and bounds[1] <= 4000
        assert bounds[2] == updated["content"]
        assert api_environment.fetchone_admin("""
            SELECT string_agg(content,'' ORDER BY ordinal) FROM public.chunks
            WHERE document_version_id=%s
        """, (item["currentVersionId"],))[0] == normalized
