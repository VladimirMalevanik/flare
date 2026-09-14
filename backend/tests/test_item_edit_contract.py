"""Fast checks for the versioned source edit HTTP contract."""

from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.api.schemas import UpdateItemRequest
from app.services.analytics_service import _sanitize_metadata


def test_update_contract_requires_version_token_and_reports_only_supplied_changes():
    version_id = uuid4()
    payload = UpdateItemRequest.model_validate(
        {
            "expectedCurrentVersionId": str(version_id),
            "title": "  Revised title  ",
            "content": "  significant imported whitespace\n",
        }
    )

    assert payload.expected_current_version_id == version_id
    assert payload.changes() == {
        "title": "Revised title",
        "content": "  significant imported whitespace\n",
    }

    with pytest.raises(ValidationError):
        UpdateItemRequest.model_validate({"content": "Missing token"})
    with pytest.raises(ValidationError):
        UpdateItemRequest.model_validate(
            {
                "expectedCurrentVersionId": str(version_id),
                "metadata": {"sourceText": "must never be accepted"},
            }
        )


@pytest.mark.parametrize("event_type", ["item_updated", "source_replaced"])
def test_edit_analytics_accept_only_bounded_non_content_metadata(event_type):
    assert _sanitize_metadata(
        event_type,
        {"item_type": "note", "version_number": 2},
    ) == {"item_type": "note", "version_number": 2}

    with pytest.raises(ValueError, match="metadata key is not allowed"):
        _sanitize_metadata(event_type, {"content": "customer source text"})
