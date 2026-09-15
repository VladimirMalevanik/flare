"""Operational queue health and maintenance API checks."""

from collections.abc import Iterator
import os
import secrets
from uuid import uuid4

import pytest
from test_items_api import ApiEnvironment, _create_note
from app.legal import (
    CURRENT_PRIVACY_CONTENT_ID,
    CURRENT_PRIVACY_VERSION,
    CURRENT_TERMS_CONTENT_ID,
    CURRENT_TERMS_VERSION,
)
from app.services.auth_service import token_digest


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
    non_member_workspace_id = uuid4()

    with api_environment.client(workspace_id=workspace_id, user_id=owner_user) as owner_client:
        _create_note(owner_client, title="Owner note", content="Owner has rights")
        health = owner_client.get("/ops/queue")
        assert health.status_code == 200
        assert health.json().keys() == {"asOf", "analysis", "flares", "cycles", "alerts"}
        assert health.json()["cycles"].keys() == {
            "scheduled", "refreshing", "ready", "failed", "dueRefresh", "dueRun",
            "staleRefreshing", "overdue", "oldestRefreshDueSeconds", "oldestRunDueSeconds",
        }
        maintenance = owner_client.post("/ops/queue/maintenance")
        assert maintenance.status_code == 200
        assert maintenance.json().keys() >= {
            "dryRun", "applied", "before", "after", "analysisJobs",
            "flareGenerationRuns", "analysisCycles",
            "recoveredStaleAnalysisCycleRefreshes", "failedStaleAnalysisCycles",
        }

    api_environment.execute_admin(
        "UPDATE public.workspace_members SET role = 'viewer' WHERE workspace_id = %s AND user_id = %s",
        (workspace_id, owner_user),
    )
    with api_environment.client(workspace_id=workspace_id, user_id=owner_user) as viewer_client:
        assert viewer_client.get("/ops/queue").status_code == 403
        assert viewer_client.post("/ops/queue/maintenance").status_code == 403

    with api_environment.client(
        workspace_id=non_member_workspace_id, user_id=viewer_user
    ) as non_member:
        api_environment.execute_admin(
            "DELETE FROM public.workspace_members WHERE workspace_id = %s AND user_id = %s",
            (non_member_workspace_id, viewer_user),
        )
        assert non_member.get("/ops/queue").status_code == 403


@pytest.mark.integration
def test_owner_health_includes_jobs_created_by_another_workspace_editor(api_environment):
    workspace_id = uuid4()
    owner_user = f"api-test|{uuid4()}"
    editor_user = f"api-test|{uuid4()}"
    with api_environment.client(workspace_id=workspace_id, user_id=owner_user) as owner_client:
        # Schedule endpoints deliberately require a real, revocable session even
        # when the app is running with the local development identity enabled.
        # A real production session is also subject to the legal gate, so make
        # this unrelated ops fixture explicitly current-accepted.
        owner_token = secrets.token_urlsafe(32)
        api_environment.execute_admin(
            """INSERT INTO public.auth_legal_acceptances(
                   user_id,terms_version,privacy_version,
                   terms_content_id,privacy_content_id)
               VALUES(%s,%s,%s,%s,%s)
               ON CONFLICT DO NOTHING""",
            (
                owner_user,
                CURRENT_TERMS_VERSION,
                CURRENT_PRIVACY_VERSION,
                CURRENT_TERMS_CONTENT_ID,
                CURRENT_PRIVACY_CONTENT_ID,
            ),
        )
        api_environment.execute_admin(
            """INSERT INTO public.auth_sessions(
                   token_hash,user_id,workspace_id,expires_at)
               VALUES(%s,%s,%s,now()+interval '1 hour')""",
            (token_digest(owner_token), owner_user, workspace_id),
        )
        owner_client.cookies.set("flare_session", owner_token)
        api_environment.user_ids.add(editor_user)
        api_environment.execute_admin(
            """INSERT INTO public.auth_users(
                   id,email,password_hash,name,initial_workspace_id,disabled)
               SELECT %s,%s,password_hash,'Workspace editor',%s,false
                 FROM public.auth_users WHERE id=%s""",
            (editor_user, f"{uuid4()}@ops-test.invalid", workspace_id, owner_user),
        )
        api_environment.execute_admin(
            "INSERT INTO public.workspace_members(workspace_id,user_id,role) VALUES(%s,%s,'editor')",
            (workspace_id, editor_user),
        )
        parent_job = uuid4()
        api_environment.execute_admin(
            """INSERT INTO public.analysis_jobs(
                   id,workspace_id,requested_by_user_id,pipeline_revision,dedupe_key,max_attempts)
               VALUES(%s,%s,%s,'ops-editor-v1',%s,3)""",
            (parent_job, workspace_id, editor_user, "a" * 64),
        )
        api_environment.execute_admin(
            """INSERT INTO public.flare_generation_runs(
                   workspace_id,analysis_job_id,generation_revision,max_attempts)
               VALUES(%s,%s,'ops-editor-v1',3)""",
            (workspace_id, parent_job),
        )
        api_environment.execute_admin(
            """INSERT INTO public.analysis_schedules(
                   workspace_id,enabled,timezone,local_time,updated_by_user_id)
               VALUES(%s,true,'UTC',TIME '19:00',%s)""",
            (workspace_id, editor_user),
        )
        schedule = owner_client.get("/analysis-schedule")
        assert schedule.status_code == 200
        assert schedule.json()["enabled"] is True
        health = owner_client.get("/ops/queue")
        assert health.status_code == 200
        assert health.json()["analysis"]["pending"] == 1
        assert health.json()["flares"]["pending"] == 1


@pytest.mark.integration
def test_ops_maintenance_dry_run_is_safe_and_recover_stale_can_be_applied(api_environment):
    workspace_id = uuid4()
    owner_user = f"api-test|{uuid4()}"
    job_id = uuid4()
    old_event_id = uuid4()

    with api_environment.client(workspace_id=workspace_id, user_id=owner_user) as owner_client:
        _create_note(owner_client, title="Recovery note", content="Needs stale recovery")
    max_attempts = 3
    api_environment.execute_admin(
        """INSERT INTO public.analysis_jobs(
               id,workspace_id,requested_by_user_id,pipeline_revision,dedupe_key,max_attempts)
           VALUES(%s,%s,%s,'ops-maintenance-v1',%s,%s)""",
        (job_id, workspace_id, owner_user, "c" * 64, max_attempts),
    )
    api_environment.execute_admin(
        """INSERT INTO public.activity_events(
               id,workspace_id,actor_id,event_type,target_type,metadata,created_at)
           VALUES(%s,%s,%s,'capture_started','capture','{}'::jsonb,
                  now()-interval '100 days')""",
        (old_event_id, workspace_id, owner_user),
    )

    api_environment.execute_admin(
        """UPDATE public.analysis_jobs
           SET status = 'processing', attempts = %s, lease_owner = gen_random_uuid(),
               lease_token = gen_random_uuid(), lease_expires_at = now() - interval '2 minutes'
           WHERE id = %s""",
        (max_attempts, job_id),
    )
    api_environment.execute_admin(
        """INSERT INTO public.analysis_cycles(
               workspace_id,local_date,timezone,mode,state,requested_by_user_id,
               refresh_due_at,scheduled_for,refresh_started_at,refresh_lease_owner,
               refresh_lease_token,refresh_lease_expires_at)
           VALUES(%s,current_date,'UTC','scheduled','refreshing',%s,
                  now()-interval '1 hour',now()+interval '2 hours',now()-interval '10 minutes',
                  gen_random_uuid(),gen_random_uuid(),now()-interval '2 minutes')""",
        (workspace_id, owner_user),
    )
    with api_environment.client(workspace_id=workspace_id, user_id=owner_user) as owner_client:
        dry_run = owner_client.post("/ops/queue/maintenance")
        assert dry_run.status_code == 200
        assert dry_run.json()["dryRun"] is True
        assert dry_run.json()["applied"] is False
        assert dry_run.json()["analysisJobs"]["wouldFail"] >= 1
        assert dry_run.json()["analysisCycles"]["wouldRecoverRefreshing"] >= 1

        applied = owner_client.post("/ops/queue/maintenance?apply=true")
        assert applied.status_code == 200
        assert applied.json()["dryRun"] is False
        assert applied.json()["applied"] is True
        assert applied.json()["analysisJobs"]["failed"] >= 1
        assert applied.json()["recoveredStaleAnalysisCycleRefreshes"] >= 1

    row = api_environment.fetchone_admin(
        "SELECT status,error FROM public.analysis_jobs WHERE id=%s", (job_id,)
    )
    assert row[0] == "failed"
    assert row[1] == "worker_lease_expired"
