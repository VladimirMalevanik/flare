"""Operational queue health and maintenance API checks."""

from collections.abc import Iterator
import os
from uuid import uuid4

import pytest
from test_items_api import ApiEnvironment, _create_note


def _required_urls_for_ops() -> tuple[str, str]:
    runtime_url = os.getenv("DATABASE_URL")
    admin_url = os.getenv("TEST_DATABASE_URL")
    if not runtime_url or not admin_url:
        pytest.skip("DATABASE_URL and TEST_DATABASE_URL are required for ops API tests")
    return runtime_url, admin_url


@pytest.fixture
def api_environment() -> Iterator[ApiEnvironment]:
    runtime_url, admin_url = _required_urls_for_ops()
    environment = ApiEnvironment(runtime_url, admin_url)
    try:
        yield environment
    finally:
        environment.cleanup()


def test_ops_endpoints_require_workspace_owner_and_return_health(api_environment):
    workspace_id = uuid4()
    owner_user = f"api-test|{uuid4()}"
    viewer_user = f"api-test|{uuid4()}"

    with api_environment.client(workspace_id=workspace_id, user_id=owner_user) as owner_client:
        _create_note(owner_client, title="Owner note", content="Owner has rights")
        health = owner_client.get("/ops/queue")
        assert health.status_code == 200
        assert health.json().keys() == {"asOf", "analysis", "flares", "alerts"}
        maintenance = owner_client.post("/ops/queue/maintenance")
        assert maintenance.status_code == 200
        assert maintenance.json().keys() >= {"dryRun", "applied", "before", "after", "analysisJobs", "flareGenerationRuns"}

    api_environment.execute_admin(
        "UPDATE public.workspace_members SET role = 'viewer' WHERE workspace_id = %s AND user_id = %s",
        (workspace_id, owner_user),
    )
    with api_environment.client(workspace_id=workspace_id, user_id=owner_user) as viewer_client:
        assert viewer_client.get("/ops/queue").status_code == 403
        assert viewer_client.post("/ops/queue/maintenance").status_code == 403

    with api_environment.client(workspace_id=workspace_id, user_id=viewer_user) as non_member:
        assert non_member.get("/ops/queue").status_code == 403


@pytest.mark.integration
def test_ops_maintenance_dry_run_is_safe_and_recover_stale_can_be_applied(api_environment):
    workspace_id = uuid4()
    owner_user = f"api-test|{uuid4()}"

    with api_environment.client(workspace_id=workspace_id, user_id=owner_user) as owner_client:
        _create_note(owner_client, title="Recovery note", content="Needs stale recovery")
        row = api_environment.fetchone_admin(
            """SELECT id, max_attempts
               FROM public.analysis_jobs aj
               WHERE aj.workspace_id = %s
               ORDER BY aj.created_at DESC
               LIMIT 1""",
            (workspace_id,),
        )
        assert row is not None
        job_id, max_attempts = row

    api_environment.execute_admin(
        """UPDATE public.analysis_jobs
           SET status = 'processing', attempts = %s, lease_owner = gen_random_uuid(),
               lease_token = gen_random_uuid(), lease_expires_at = now() - interval '2 minutes'
           WHERE id = %s""",
        (max_attempts, job_id),
    )

    with api_environment.client(workspace_id=workspace_id, user_id=owner_user) as owner_client:
        dry_run = owner_client.post("/ops/queue/maintenance")
        assert dry_run.status_code == 200
        payload = dry_run.json()
        assert payload["dryRun"] is True
        assert payload["applied"] is False
        assert payload["analysisJobs"]["deleted"] == 0
        assert payload["recoveredStaleAnalysisJobs"] == 0

        status_before = api_environment.fetchone_admin(
            "SELECT status FROM public.analysis_jobs WHERE id = %s",
            (job_id,),
        )
        assert status_before == ("processing",)

        applied = owner_client.post(
            "/ops/queue/maintenance",
            json={
                "dry_run": False,
                "recover_stale": True,
                "max_rows": 50,
                "analysis_completed_retention_days": 1,
                "analysis_failed_retention_days": 1,
                "flare_completed_retention_days": 1,
                "flare_failed_retention_days": 1,
            },
        )
        assert applied.status_code == 200
        result = applied.json()
        assert result["dryRun"] is False
        assert result["applied"] is True
        assert result["recoveredStaleAnalysisJobs"] == 1
        assert result["analysisJobs"]["deleted"] >= 0

        status_after = api_environment.fetchone_admin(
            "SELECT status FROM public.analysis_jobs WHERE id = %s",
            (job_id,),
        )
        assert status_after == ("failed",)
