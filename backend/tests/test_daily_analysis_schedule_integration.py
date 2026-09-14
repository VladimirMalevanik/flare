"""PostgreSQL invariants for one daily workspace cycle and schedule permissions."""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import psycopg
import pytest

from test_analysis_jobs import executor_role, jobs, admin_url
from test_flares_api import client_for
from app.models.analysis_schedules import WorkerAnalysisSchedules
from app.services.item_service import ItemService


pytestmark = pytest.mark.integration
UTC = timezone.utc


def _post_analyze(client, key):
    return client.post(
        "/analyze",
        headers={"Origin": "http://testserver", "Idempotency-Key": str(key)},
        json={},
    )


def _materialize_scheduled_cycle(jobs, admin_url):
    """Create a real near-future slot while staying inside the DB clock fence."""
    target = (datetime.now(UTC) + timedelta(minutes=32)).replace(second=0, microsecond=0)
    with client_for(jobs) as client:
        response = client.put(
            "/analysis-schedule",
            headers={"Origin": "http://testserver"},
            json={"enabled": True, "timezone": "UTC", "localTime": target.strftime("%H:%M")},
        )
        assert response.status_code == 200, response.text
        refresh_at = datetime.fromisoformat(response.json()["nextRefreshAt"])
    worker = WorkerAnalysisSchedules(jobs[1]._database_url)
    assert worker.materialize(refresh_at + timedelta(seconds=1)) == 1
    with psycopg.connect(admin_url) as connection:
        cycle = connection.execute(
            """SELECT id, scheduled_for, refresh_due_at
                 FROM public.analysis_cycles
                WHERE workspace_id=%s""",
            (jobs[2][0].workspace_id,),
        ).fetchone()
    assert cycle is not None
    with client_for(jobs) as client:
        preview = client.get("/analysis-schedule")
        assert preview.status_code == 200
        assert datetime.fromisoformat(preview.json()["nextRunAt"]) == cycle[1]
        assert datetime.fromisoformat(preview.json()["nextRefreshAt"]) == cycle[2]
    return worker, cycle


def _insert_newer_processing_documents(admin_url, workspace_id, count=200):
    document_ids = [uuid4() for _ in range(count)]
    version_ids = [uuid4() for _ in range(count)]
    with psycopg.connect(admin_url) as connection:
        connection.execute(
            """INSERT INTO public.documents(id,workspace_id,title,source_type,metadata)
               SELECT id,%s,'Still processing','note','{}'::jsonb
                 FROM unnest(%s::uuid[]) AS pending(id)""",
            (workspace_id, document_ids),
        )
        connection.execute(
            """INSERT INTO public.document_versions(
                   id,workspace_id,document_id,version_number,content_hash,parser_version,state)
               SELECT version_id,%s,document_id,1,repeat('a',64),'test-processing-v1','processing'
                 FROM unnest(%s::uuid[],%s::uuid[]) AS pending(version_id,document_id)""",
            (workspace_id, version_ids, document_ids),
        )
        connection.execute(
            """UPDATE public.documents d SET current_version_id=pending.version_id
                 FROM unnest(%s::uuid[],%s::uuid[]) AS pending(version_id,document_id)
                WHERE d.id=pending.document_id AND d.workspace_id=%s""",
            (version_ids, document_ids, workspace_id),
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
        assert connection.execute(
            """SELECT count(*) FROM public.activity_events
                WHERE target_id=%s AND event_type='analysis_requested'
                  AND metadata=jsonb_build_object('mode','manual')""",
            (first.json()["id"],),
        ).fetchone() == (1,)


def test_concurrent_manual_requests_create_one_run_and_report_daily_limit(jobs):
    def request_once(_):
        with client_for(jobs) as client:
            response = _post_analyze(client, uuid4())
            return response.status_code, response.json()

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(request_once, range(2)))

    assert sorted(status for status, _ in results) == [202, 409]
    loser = next(payload for status, payload in results if status == 409)
    assert loser == {"detail": "daily_limit"}


def test_job_retention_cascade_cannot_reopen_the_local_day(jobs, admin_url):
    """The quota survives cleanup, including New York's 25-hour fall-back day."""
    with client_for(jobs) as client:
        schedule = client.put(
            "/analysis-schedule",
            headers={"Origin": "http://testserver"},
            json={"enabled": True, "timezone": "America/New_York", "localTime": "19:00"},
        )
        assert schedule.status_code == 200
        first = _post_analyze(client, uuid4())
        assert first.status_code == 202

    with psycopg.connect(admin_url) as connection:
        job_id = connection.execute(
            "SELECT analysis_job_id FROM public.analysis_runs WHERE id=%s",
            (first.json()["id"],),
        ).fetchone()[0]
        connection.execute(
            """UPDATE public.analysis_jobs
                  SET status='failed',last_error_code='internal_error',
                      completed_at=clock_timestamp()-interval '2 days',
                      updated_at=clock_timestamp()-interval '2 days'
                WHERE id=%s""",
            (job_id,),
        )

    with client_for(jobs) as client:
        cleanup = client.post(
            "/ops/queue/maintenance",
            json={
                "dry_run": False,
                "recover_stale": False,
                "max_rows": 50,
                "analysis_completed_retention_days": 1,
                "analysis_failed_retention_days": 1,
                "flare_completed_retention_days": 1,
                "flare_failed_retention_days": 1,
                "cycle_failed_retention_days": 1,
            },
        )
        assert cleanup.status_code == 200, cleanup.text
        assert cleanup.json()["analysisJobs"]["deleted"] == 1
        status = client.get("/analysis/daily-status")
        assert status.status_code == 200
        assert status.json()["canRequestToday"] is False
        assert _post_analyze(client, uuid4()).status_code == 409

    with psycopg.connect(admin_url) as connection:
        assert connection.execute(
            "SELECT count(*) FROM public.analysis_cycles WHERE workspace_id=%s",
            (jobs[2][0].workspace_id,),
        ).fetchone() == (0,)
        assert connection.execute(
            "SELECT count(*) FROM public.analysis_daily_quotas WHERE workspace_id=%s",
            (jobs[2][0].workspace_id,),
        ).fetchone() == (1,)


def test_timezone_change_cannot_make_recent_daily_cycle_look_available(jobs):
    with client_for(jobs) as client:
        first = _post_analyze(client, uuid4())
        assert first.status_code == 202
        utc_hour = datetime.now(UTC).hour
        changed_zone = "Pacific/Kiritimati" if utc_hour >= 10 else "Pacific/Pago_Pago"
        changed = client.put(
            "/analysis-schedule",
            headers={"Origin": "http://testserver"},
            json={"enabled": True, "timezone": changed_zone, "localTime": "19:00"},
        )
        assert changed.status_code == 200
        status = client.get("/analysis/daily-status")
        assert status.status_code == 200
        assert status.json()["cycleId"] is not None
        assert status.json()["canRequestToday"] is False
        assert _post_analyze(client, uuid4()).status_code == 409


def test_schedule_preview_and_materializer_share_recent_cycle_guard(jobs):
    now = datetime.now(UTC)
    target = (now + timedelta(minutes=32)).replace(second=0, microsecond=0)
    with client_for(jobs) as client:
        assert _post_analyze(client, uuid4()).status_code == 202
        schedule = client.put(
            "/analysis-schedule",
            headers={"Origin": "http://testserver"},
            json={"enabled": True, "timezone": "UTC", "localTime": target.strftime("%H:%M")},
        )
        assert schedule.status_code == 200
        promised = datetime.fromisoformat(schedule.json()["nextRunAt"])
        assert promised > now + timedelta(hours=20)

    # The current wall-clock slot reaches T-30 within the worker clock fence,
    # but both the DB and preview skip it because the manual cycle is recent.
    worker = WorkerAnalysisSchedules(jobs[1]._database_url)
    assert worker.materialize(target - timedelta(minutes=30) + timedelta(seconds=1)) == 0


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


def test_schedule_change_atomically_cancels_unstarted_materialized_cycle(jobs, admin_url):
    _, cycle = _materialize_scheduled_cycle(jobs, admin_url)
    with client_for(jobs) as client:
        changed = client.put(
            "/analysis-schedule",
            headers={"Origin": "http://testserver"},
            json={"enabled": False, "timezone": "UTC", "localTime": "20:00"},
        )
        assert changed.status_code == 200
    with psycopg.connect(admin_url) as connection:
        assert connection.execute(
            "SELECT count(*) FROM public.analysis_cycles WHERE id=%s", (cycle[0],)
        ).fetchone() == (0,)
        assert connection.execute(
            """SELECT count(*) FROM public.analysis_daily_quotas
                WHERE workspace_id=%s""",
            (jobs[2][0].workspace_id,),
        ).fetchone() == (0,)


def test_revoked_schedule_actor_fails_closed_and_disables_unadopted_schedule(jobs, admin_url):
    worker, cycle = _materialize_scheduled_cycle(jobs, admin_url)
    with psycopg.connect(admin_url) as connection:
        connection.execute(
            "UPDATE public.workspace_members SET role='viewer' WHERE workspace_id=%s AND user_id=%s",
            (jobs[2][0].workspace_id, jobs[2][0].user_id),
        )
        connection.execute(
            "UPDATE public.analysis_cycles SET refresh_due_at=now()-interval '1 second' WHERE id=%s",
            (cycle[0],),
        )
    claim = worker.claim_refresh(uuid4(), 120)
    assert claim is not None
    assert worker.candidates(claim, 100, 100_000) == {"error": "authorization_revoked"}
    assert worker.finish_refresh(claim, error="authorization_revoked") == "failed"
    with psycopg.connect(admin_url) as connection:
        assert connection.execute(
            "SELECT enabled FROM public.analysis_schedules WHERE workspace_id=%s",
            (jobs[2][0].workspace_id,),
        ).fetchone() == (False,)


def test_scheduled_cycle_freezes_version_enqueues_and_emits_metric(jobs, admin_url):
    worker, cycle = _materialize_scheduled_cycle(jobs, admin_url)
    with psycopg.connect(admin_url) as connection:
        connection.execute(
            "UPDATE public.analysis_cycles SET refresh_due_at=now()-interval '1 second' WHERE id=%s",
            (cycle[0],),
        )
    claim = worker.claim_refresh(uuid4(), 120)
    assert claim is not None and claim.cycle_id == cycle[0]
    _insert_newer_processing_documents(admin_url, jobs[2][0].workspace_id)
    loaded = worker.candidates(claim, 100, 100_000)
    candidate_ids = {row["id"] for row in loaded["candidates"]}
    old_chunk = jobs[3][0]
    assert str(old_chunk) in candidate_ids
    assert worker.finish_refresh(claim, chunks=(old_chunk,)) == "ready"

    with jobs[0].database.workspace_transaction(jobs[2][0]) as connection:
        item = connection.execute(
            """SELECT d.id,d.current_version_id
                 FROM public.documents d
                 JOIN public.document_versions v
                   ON (v.workspace_id,v.id)=(d.workspace_id,d.current_version_id)
                 JOIN public.chunks c
                   ON (c.workspace_id,c.document_version_id)=(v.workspace_id,v.id)
                WHERE c.id=%s""",
            (old_chunk,),
        ).fetchone()
    updated = ItemService(jobs[0].database, jobs[2][0]).update_item(
        item["id"],
        expected_current_version_id=item["current_version_id"],
        changes={"content": "The current decision was edited after the daily snapshot."},
    )
    assert updated.changed is True

    with psycopg.connect(admin_url) as connection:
        enqueue_at = connection.execute(
            """UPDATE public.analysis_cycles SET scheduled_for=clock_timestamp()
                 WHERE id=%s RETURNING scheduled_for""",
            (cycle[0],),
        ).fetchone()[0]
    outcomes = worker.enqueue_due(
        pipeline_revision="scheduled-lifecycle-v1",
        generation_revision="scheduled-generation-v1",
        max_attempts=3,
        now=enqueue_at + timedelta(seconds=1),
    )
    assert len(outcomes) == 1 and outcomes[0]["status"] == "queued"
    run_id = outcomes[0]["run_id"]
    with psycopg.connect(admin_url) as connection:
        assert connection.execute(
            """SELECT s.chunk_id
                 FROM public.analysis_runs r
                 JOIN public.analysis_job_sources s ON s.job_id=r.analysis_job_id
                WHERE r.id=%s ORDER BY s.ordinal""",
            (run_id,),
        ).fetchall() == [(old_chunk,)]
        assert connection.execute(
            """SELECT event_type,target_type,metadata
                 FROM public.activity_events
                WHERE target_id=%s""",
            (run_id,),
        ).fetchone() == ("analysis_requested", "analysis_run", {"mode": "scheduled"})
        job_id = connection.execute(
            "SELECT analysis_job_id FROM public.analysis_runs WHERE id=%s", (run_id,)
        ).fetchone()[0]
        connection.execute("DELETE FROM public.analysis_jobs WHERE id=%s", (job_id,))
        assert connection.execute(
            "SELECT count(*) FROM public.analysis_cycles WHERE id=%s", (cycle[0],)
        ).fetchone() == (0,)


def test_delete_after_snapshot_revokes_scheduled_evidence_before_enqueue(jobs, admin_url):
    worker, cycle = _materialize_scheduled_cycle(jobs, admin_url)
    with psycopg.connect(admin_url) as connection:
        connection.execute(
            "UPDATE public.analysis_cycles SET refresh_due_at=now()-interval '1 second' WHERE id=%s",
            (cycle[0],),
        )
    claim = worker.claim_refresh(uuid4(), 120)
    assert claim is not None
    old_chunk = jobs[3][0]
    loaded = worker.candidates(claim, 100, 100_000)
    assert str(old_chunk) in {candidate["id"] for candidate in loaded["candidates"]}
    assert worker.finish_refresh(claim, chunks=(old_chunk,)) == "ready"

    with jobs[0].database.workspace_transaction(jobs[2][0]) as connection:
        item_id = connection.execute(
            """SELECT v.document_id FROM public.document_versions v
                 JOIN public.chunks c
                   ON (c.workspace_id,c.document_version_id)=(v.workspace_id,v.id)
                WHERE c.id=%s""",
            (old_chunk,),
        ).fetchone()["document_id"]
    ItemService(jobs[0].database, jobs[2][0]).delete_item(item_id)

    with psycopg.connect(admin_url) as connection:
        enqueue_at = connection.execute(
            """UPDATE public.analysis_cycles SET scheduled_for=clock_timestamp()
                 WHERE id=%s RETURNING scheduled_for""",
            (cycle[0],),
        ).fetchone()[0]
    outcomes = worker.enqueue_due(
        pipeline_revision="deleted-snapshot-v1",
        generation_revision="deleted-snapshot-v1",
        max_attempts=3,
        now=enqueue_at + timedelta(seconds=1),
    )
    assert outcomes == [{
        "cycle_id": str(cycle[0]),
        "status": "failed",
        "error_code": "source_invalid",
    }]
    with psycopg.connect(admin_url) as connection:
        assert connection.execute(
            "SELECT analysis_run_id FROM public.analysis_cycles WHERE id=%s", (cycle[0],)
        ).fetchone() == (None,)
        assert connection.execute(
            "SELECT count(*) FROM public.analysis_daily_quotas WHERE workspace_id=%s",
            (jobs[2][0].workspace_id,),
        ).fetchone() == (1,)


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
        for table in (
            "analysis_cycles", "analysis_cycle_sources", "analysis_schedules",
            "analysis_daily_quotas",
        ):
            assert connection.execute(
                "SELECT has_table_privilege('flare_worker',%s,'SELECT,INSERT,UPDATE,DELETE')",
                ("public." + table,),
            ).fetchone() == (False,)
        assert connection.execute(
            "SELECT pg_get_userbyid(proowner) FROM pg_proc WHERE proname='start_daily_analysis_run'"
        ).fetchone() == (executor_role(),)
        assert connection.execute(
            """SELECT has_function_privilege(
                   'flare_app','public.enqueue_analysis_job(uuid[],text,integer)','EXECUTE')"""
        ).fetchone() == (False,)
        assert connection.execute(
            """SELECT has_table_privilege(
                   'flare_app','public.analysis_schedules','INSERT,UPDATE,DELETE')"""
        ).fetchone() == (False,)
        assert connection.execute(
            """SELECT has_function_privilege(
                   'flare_app',
                   'public.analysis_cycle_maintenance(boolean,boolean,integer,integer)',
                   'EXECUTE')"""
        ).fetchone() == (True,)

    worker = WorkerAnalysisSchedules(jobs[1]._database_url)
    with pytest.raises(psycopg.errors.InvalidParameterValue):
        worker.enqueue_due(
            pipeline_revision="clock-fence-v1",
            generation_revision="clock-fence-v1",
            max_attempts=3,
            now=datetime.now(UTC) + timedelta(days=1),
        )
