"""Analytics endpoint checks for production-style workflow telemetry."""

import os
import uuid

import pytest

from test_items_api import ApiEnvironment, _create_note


@pytest.fixture
def api_environment():
    environment = ApiEnvironment(
        runtime_url=os.environ.get("DATABASE_URL", ""),
        admin_url=os.environ.get("TEST_DATABASE_URL", ""),
    )
    try:
        yield environment
    finally:
        environment.cleanup()


@pytest.mark.integration
@pytest.mark.parametrize("window_hours", [24])
def test_analytics_summary_collects_item_and_capture_events(api_environment, window_hours):
    workspace_id, user_id = uuid.uuid4(), f"api-test|{uuid.uuid4()}"
    if not api_environment.runtime_url or not api_environment.admin_url:
        pytest.skip("DATABASE_URL and TEST_DATABASE_URL are required for analytics API tests")

    with api_environment.client(workspace_id=workspace_id, user_id=user_id) as client:
        note = _create_note(
            client,
            title="Project health check",
            content="Captured context should create events for product telemetry.",
        )

        post_status = client.post(
            "/analytics/events",
            json={
                "eventType": "capture_started",
                "targetType": "capture",
                "metadata": {"channel": "orb"},
            },
        )
        assert post_status.status_code == 202
        viewed = client.post(
            "/analytics/events",
            json={
                "eventType": "item_viewed",
                "targetType": "item",
                "targetId": note["id"],
                "metadata": {"sourceType": "note"},
            },
        )
        assert viewed.status_code == 202

        response = client.get(f"/analytics/events?window_hours={window_hours}")
        assert response.status_code == 200
        summary = response.json()

    events = {row["event_type"]: row["count"] for row in summary["events"]}
    assert events.get("item_created", 0) >= 1
    assert events.get("capture_started", 0) == 1
    assert events.get("item_viewed", 0) == 1


@pytest.mark.integration
def test_analytics_endpoints_reject_users_outside_workspace(api_environment):
    workspace_id, owner_id = uuid.uuid4(), f"api-test|{uuid.uuid4()}"
    outsider_workspace_id = uuid.uuid4()
    outsider_id = f"api-test|{uuid.uuid4()}"
    if not api_environment.runtime_url or not api_environment.admin_url:
        pytest.skip("DATABASE_URL and TEST_DATABASE_URL are required for analytics API tests")

    with api_environment.client(workspace_id=workspace_id, user_id=owner_id) as owner_client:
        _create_note(owner_client, title="Only for owner", content="No one else can read this workspace")

    with api_environment.client(
        workspace_id=outsider_workspace_id, user_id=outsider_id
    ) as outsider_client:
        api_environment.execute_admin(
            "DELETE FROM public.workspace_members WHERE workspace_id = %s AND user_id = %s",
            (outsider_workspace_id, outsider_id),
        )
        assert outsider_client.post(
            "/analytics/events",
            json={
                "eventType": "capture_submitted",
                "targetType": "item",
                "targetId": str(uuid.uuid4()),
                "metadata": {"sourceType": "note"},
            },
        ).status_code == 403
        assert outsider_client.get("/analytics/events").status_code == 403


def test_invalid_analytics_event_is_422(api_environment):
    workspace_id, user_id = uuid.uuid4(), f"api-test|{uuid.uuid4()}"
    if not api_environment.runtime_url or not api_environment.admin_url:
        pytest.skip("DATABASE_URL and TEST_DATABASE_URL are required for analytics API tests")

    with api_environment.client(workspace_id=workspace_id, user_id=user_id) as client:
        response = client.post(
            "/analytics/events",
            json={"eventType": "this_event_does_not_exist"},
        )
    assert response.status_code == 422


@pytest.mark.integration
def test_viewer_can_persist_client_event_but_cannot_forge_server_outcome(api_environment):
    workspace_id, viewer_id = uuid.uuid4(), f"api-test|{uuid.uuid4()}"
    if not api_environment.runtime_url or not api_environment.admin_url:
        pytest.skip("DATABASE_URL and TEST_DATABASE_URL are required for analytics API tests")

    with api_environment.client(workspace_id=workspace_id, user_id=viewer_id) as client:
        api_environment.execute_admin(
            "UPDATE public.workspace_members SET role = 'viewer' "
            "WHERE workspace_id = %s AND user_id = %s",
            (workspace_id, viewer_id),
        )

        accepted = client.post(
            "/analytics/events",
            json={"eventType": "capture_started", "targetType": "capture"},
        )
        forged = client.post(
            "/analytics/events",
            json={
                "eventType": "item_created",
                "targetType": "item",
                "targetId": str(uuid.uuid4()),
                "metadata": {"item_type": "note"},
            },
        )
        nonexistent_view = client.post(
            "/analytics/events",
            json={
                "eventType": "item_viewed",
                "targetType": "item",
                "targetId": str(uuid.uuid4()),
                "metadata": {"sourceType": "note"},
            },
        )

        row = api_environment.fetchone_admin(
            "SELECT workspace_id, actor_id, event_type FROM public.activity_events "
            "WHERE workspace_id = %s AND actor_id = %s ORDER BY created_at DESC LIMIT 1",
            (workspace_id, viewer_id),
        )

    assert accepted.status_code == 202
    assert forged.status_code == 422
    assert nonexistent_view.status_code == 422
    assert row == (workspace_id, viewer_id, "capture_started")


@pytest.mark.integration
def test_client_event_rate_limit_drops_excess_without_breaking_product_action(api_environment):
    workspace_id, user_id = uuid.uuid4(), f"api-test|{uuid.uuid4()}"
    if not api_environment.runtime_url or not api_environment.admin_url:
        pytest.skip("DATABASE_URL and TEST_DATABASE_URL are required for analytics API tests")

    with api_environment.client(workspace_id=workspace_id, user_id=user_id) as client:
        api_environment.execute_admin(
            """INSERT INTO public.activity_events(
                   workspace_id,actor_id,event_type,target_type,metadata)
               SELECT %s,%s,'capture_started','capture','{}'::jsonb
                 FROM generate_series(1,600)""",
            (workspace_id, user_id),
        )
        response = client.post(
            "/analytics/events",
            json={"eventType": "capture_started", "targetType": "capture"},
        )
        count = api_environment.fetchone_admin(
            """SELECT count(*) FROM public.activity_events
                WHERE workspace_id=%s AND actor_id=%s""",
            (workspace_id, user_id),
        )

    assert response.status_code == 202
    assert count == (600,)
