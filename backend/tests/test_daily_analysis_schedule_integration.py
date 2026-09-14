"""PostgreSQL invariants for one daily workspace cycle and schedule permissions."""

from uuid import uuid4

import psycopg
import pytest

from test_analysis_jobs import executor_role, jobs, admin_url
from test_flares_api import client_for


pytestmark = pytest.mark.integration


def _post_analyze(client, key):
    return client.post(
        "/analyze",
        headers={"Origin": "http://testserver", "Idempotency-Key": str(key)},
        json={},
    )


def test_manual_analysis_is_idempotent_and_second_key_cannot_bypass_daily_slot(jobs, admin_url):
    first_key = uuid4()
    with client_for(jobs) as client:
        first = _post_analyze(client, first_key)
        assert first.status_code == 202
        assert _post_analyze(client, first_key).json()["id"] == first.json()["id"]
        blocked = _post_analyze(client, uuid4())
        assert blocked.status_code == 409
        assert blocked.json() == {"detail": "daily_limit"}
        status = client.get("/analysis/daily-status")
        assert status.status_code == 200
        assert status.json()["cycleId"] is not None
        assert status.json()["runId"] == first.json()["id"]
        assert status.json()["canRequestToday"] is False
    with psycopg.connect(admin_url) as connection:
        assert connection.execute(
            "SELECT count(*) FROM analysis_cycles WHERE workspace_id=%s",
            (jobs[2][0].workspace_id,),
        ).fetchone() == (1,)


def test_schedule_contract_and_viewer_cannot_update(jobs, admin_url):
    with client_for(jobs) as client:
        response = client.put(
            "/analysis-schedule",
            headers={"Origin": "http://testserver"},
            json={"enabled": True, "timezone": "America/New_York", "localTime": "18:30"},
        )
        assert response.status_code == 200
        assert response.json()["leadMinutes"] == 30
        assert response.json()["localTime"] == "18:30"
        assert response.json()["nextRunAt"] is not None
        assert client.put(
            "/analysis-schedule",
            headers={"Origin": "http://testserver"},
            json={"enabled": True, "timezone": "Not/AZone", "localTime": "18:30"},
        ).status_code == 422
    with psycopg.connect(admin_url) as connection:
        connection.execute(
            "UPDATE workspace_members SET role='viewer' WHERE workspace_id=%s AND user_id=%s",
            (jobs[2][0].workspace_id, jobs[2][0].user_id),
        )
    with client_for(jobs) as client:
        assert client.get("/analysis-schedule").status_code == 200
        denied = client.put(
            "/analysis-schedule",
            headers={"Origin": "http://testserver"},
            json={"enabled": False, "timezone": "UTC", "localTime": "12:00"},
        )
        assert denied.status_code == 403


def test_worker_has_capabilities_but_no_direct_customer_table_access(jobs, admin_url):
    with psycopg.connect(admin_url) as connection:
        for function in (
            "materialize_analysis_cycles(timestamp with time zone,integer)",
            "claim_analysis_cycle_refresh(uuid,integer)",
            "load_analysis_cycle_candidates(uuid,uuid,integer,integer)",
            "finish_analysis_cycle_refresh(uuid,uuid,uuid[],text,double precision)",
            "enqueue_due_analysis_cycles(text,text,integer,timestamp with time zone,integer)",
        ):
            assert connection.execute(
                "SELECT has_function_privilege('flare_worker',%s,'EXECUTE')", ("public." + function,)
            ).fetchone() == (True,)
        for table in ("analysis_cycles", "analysis_cycle_sources", "analysis_schedules"):
            assert connection.execute(
                "SELECT has_table_privilege('flare_worker',%s,'SELECT,INSERT,UPDATE,DELETE')",
                ("public." + table,),
            ).fetchone() == (False,)
        assert connection.execute(
            "SELECT pg_get_userbyid(proowner) FROM pg_proc WHERE proname='start_daily_analysis_run'"
        ).fetchone() == (executor_role(),)
