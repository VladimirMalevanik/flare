"""Durable worker invariants exercised against real PostgreSQL roles."""
import os
from uuid import uuid4

import psycopg
import pytest

pytestmark = pytest.mark.integration


@pytest.fixture
def admin_url():
    value = os.getenv('TEST_DATABASE_URL')
    if not value:
        pytest.skip('Requires disposable migrated PostgreSQL')
    return value


def test_worker_roles_and_function_capabilities(admin_url):
    with psycopg.connect(admin_url) as conn:
        roles = conn.execute("SELECT rolname,rolsuper,rolbypassrls,rolcanlogin,rolcreaterole FROM pg_roles WHERE rolname IN ('flare_worker','flare_job_executor') ORDER BY rolname").fetchall()
        assert roles == [('flare_job_executor', False, False, False, False), ('flare_worker', False, False, True, False)]
        funcs = conn.execute("SELECT p.proname,p.prosecdef,p.proconfig,r.rolname FROM pg_proc p JOIN pg_roles r ON r.oid=p.proowner WHERE r.rolname='flare_job_executor' AND p.proname IN ('analysis_job_check','enqueue_analysis_job','claim_analysis_job','load_analysis_evidence','finish_analysis_job')").fetchall()
        assert len(funcs) == 5
        assert all(row[1:] == (True, ['search_path=pg_catalog, public, pg_temp'], 'flare_job_executor') for row in funcs)
        assert conn.execute("SELECT count(*) FROM pg_auth_members WHERE roleid=(SELECT oid FROM pg_roles WHERE rolname='flare_job_executor')").fetchone() == (0,)
        for role in ('flare_app', 'flare_worker'):
            assert not conn.execute("SELECT has_function_privilege(%s, 'public.analysis_job_check(public.analysis_jobs)', 'EXECUTE')", (role,)).fetchone()[0]
        assert not conn.execute("SELECT has_function_privilege('flare_app', 'public.claim_analysis_job(uuid,integer)', 'EXECUTE')").fetchone()[0]
        for table in ('analysis_jobs','analysis_job_sources','documents','chunks','workspace_members','auth_users'):
            assert not conn.execute('SELECT has_table_privilege(%s,%s,%s)', ('flare_worker', 'public.'+table, 'SELECT,INSERT,UPDATE,DELETE')).fetchone()[0]


def test_force_rls_and_fail_closed_context(admin_url):
    with psycopg.connect(admin_url) as conn:
        for table in ('analysis_jobs','analysis_job_sources','documents','chunks','workspace_members'):
            assert conn.execute('SELECT relrowsecurity,relforcerowsecurity FROM pg_class WHERE oid=%s::regclass', ('public.'+table,)).fetchone() == (True, True)
        conn.execute('SET LOCAL ROLE flare_job_executor')
        for table in ('documents','chunks','workspace_members'):
            assert conn.execute(f'SELECT count(*) FROM public.{table}').fetchone() == (0,)
        conn.execute('RESET ROLE')
        conn.execute('SET LOCAL ROLE flare_app')
        for table in ('analysis_jobs','analysis_job_sources'):
            assert conn.execute(f'SELECT count(*) FROM public.{table}').fetchone() == (0,)


def test_worker_cannot_read_or_enqueue_directly(admin_url):
    with psycopg.connect(admin_url) as conn:
        conn.execute('SET LOCAL ROLE flare_worker')
        for sql, params in [('SELECT * FROM public.documents', ()), ('SELECT public.enqueue_analysis_job(%s,%s,%s)', ([uuid4()], 'v1', 3))]:
            with pytest.raises(psycopg.errors.InsufficientPrivilege), conn.transaction():
                conn.execute(sql, params)


@pytest.fixture
def jobs(admin_url):
    from app.models.database import Database, WorkspaceIdentity
    from app.services.auth_service import AuthService
    from app.services.item_service import ItemService
    from app.models.analysis_jobs import AnalysisJobs, WorkerJobs
    from test_items_api import ApiEnvironment
    runtime = os.environ['DATABASE_URL']
    db = Database(runtime)
    db.open()
    auth = AuthService(db)
    users, chunks = [], []
    for _ in range(2):
        token = auth.register(f'{uuid4()}@jobs-test.invalid', 'a-long-test-password', 'Jobs Test')
        user = auth.current(token)
        identity = WorkspaceIdentity(user.workspace_id, user.user_id)
        users.append(identity)
        ItemService(db, identity).create_note(title='Decision', content='We decided to use PostgreSQL.')
        with db.workspace_transaction(identity) as conn:
            chunks.append(conn.execute('SELECT id FROM public.chunks').fetchone()['id'])
    worker_url = os.getenv('WORKER_DATABASE_URL')
    if not worker_url:
        from psycopg.conninfo import make_conninfo
        worker_url = make_conninfo(admin_url, user='flare_worker')
    yield AnalysisJobs(db), WorkerJobs(worker_url), users, chunks
    db.close()
    with psycopg.connect(admin_url) as conn:
        conn.execute('DELETE FROM public.insight_sources WHERE workspace_id=ANY(%s)', ([u.workspace_id for u in users],))
        conn.execute('DELETE FROM public.insights WHERE workspace_id=ANY(%s)', ([u.workspace_id for u in users],))
        conn.execute('DELETE FROM public.analysis_jobs WHERE workspace_id=ANY(%s)', ([u.workspace_id for u in users],))
        conn.execute('DELETE FROM public.auth_users WHERE id=ANY(%s)', ([u.user_id for u in users],))
    cleanup = ApiEnvironment(runtime, admin_url)
    cleanup.workspace_ids.update(u.workspace_id for u in users)
    cleanup.cleanup()


def test_enqueue_dedupe_and_tenant_isolation(jobs, admin_url):
    from app.models.analysis_jobs import JobUnavailable
    queue, worker, users, chunks = jobs
    job = queue.enqueue(users[0], (chunks[0],), 'v1')
    assert queue.enqueue(users[0], (chunks[0],), 'v1') == job
    assert queue.enqueue(users[0], (chunks[0],), 'v2') != job
    with pytest.raises(JobUnavailable):
        queue.enqueue(users[0], (chunks[1],), 'v1')
    with pytest.raises(JobUnavailable):
        queue.enqueue(users[0], (chunks[0], chunks[0]), 'v1')
    with queue.database.workspace_transaction(users[1]) as conn:
        assert conn.execute('SELECT * FROM public.analysis_jobs').fetchall() == []
        assert conn.execute('SELECT * FROM public.analysis_job_sources').fetchall() == []
    with queue.database.workspace_transaction(users[0]) as conn:
        assert len(conn.execute('SELECT * FROM public.analysis_jobs').fetchall()) == 2


def test_concurrent_enqueue(jobs):
    from concurrent.futures import ThreadPoolExecutor
    queue, _, users, chunks = jobs
    with ThreadPoolExecutor(max_workers=4) as pool:
        ids = list(pool.map(lambda _: queue.enqueue(users[0], (chunks[0],), 'v1'), range(8)))
    assert len(set(ids)) == 1


def test_atomic_claim_and_expired_lease(jobs, admin_url):
    from concurrent.futures import ThreadPoolExecutor
    queue, worker, users, chunks = jobs
    job = queue.enqueue(users[0], (chunks[0],), 'v1')
    with ThreadPoolExecutor(max_workers=2) as pool:
        claims = list(pool.map(lambda _: worker.claim(uuid4(), 120), range(2)))
    claimed = [c for c in claims if c]
    assert len(claimed) == 1 and claimed[0].job_id == job and claimed[0].attempts == 1
    with psycopg.connect(admin_url) as conn:
        conn.execute("UPDATE analysis_jobs SET lease_expires_at=now()-interval '1 second' WHERE id=%s", (job,))
    second = worker.claim(uuid4(), 120)
    assert second.job_id == job and second.attempts == 2
    assert second.lease_token != claimed[0].lease_token
    assert worker.finish(claimed[0], error='internal_error') == 'lease_lost'


def test_last_attempt_crash_becomes_terminal(jobs, admin_url):
    queue, worker, users, chunks = jobs
    job = queue.enqueue(users[0], (chunks[0],), 'v1', max_attempts=1)
    assert worker.claim(uuid4(), 120).job_id == job
    with psycopg.connect(admin_url) as conn:
        conn.execute("UPDATE analysis_jobs SET lease_expires_at=now()-interval '1 second' WHERE id=%s", (job,))
    assert worker.claim(uuid4(), 120) is None
    with psycopg.connect(admin_url) as conn:
        assert conn.execute('SELECT status,last_error_code,attempts FROM analysis_jobs WHERE id=%s', (job,)).fetchone() == ('failed','lease_expired',1)


def test_evidence_is_pinned_bounded_and_lease_fenced(jobs):
    from dataclasses import replace
    queue, worker, users, chunks = jobs
    queue.enqueue(users[0], (chunks[0],), 'v1')
    claim = worker.claim(uuid4(), 120)
    assert worker.evidence(claim, 5, 4000) == {'evidence': [{'source_id': str(chunks[0]), 'content': 'We decided to use PostgreSQL.'}]}
    assert worker.evidence(claim, 5, 1) == {'error': 'invalid_request'}
    assert worker.evidence(replace(claim, lease_token=uuid4()), 5, 4000) == {'error': 'lease_lost'}


@pytest.mark.parametrize('change,code', [
    ('revoke', 'authorization_revoked'), ('disable', 'authorization_revoked'),
    ('reader', 'authorization_revoked'), ('delete', 'source_invalid'),
])
def test_invalidation_before_evidence(jobs, admin_url, change, code):
    queue, worker, users, chunks = jobs
    queue.enqueue(users[0], (chunks[0],), 'v1')
    claim = worker.claim(uuid4(), 120)
    invalidate(admin_url, users[0], change)
    assert worker.evidence(claim, 5, 4000) == {'error': code}
    assert worker.finish(claim, result={'observations': []}, metadata={}) == 'failed'
    with psycopg.connect(admin_url) as conn:
        assert conn.execute('SELECT result,last_error_code FROM analysis_jobs WHERE id=%s', (claim.job_id,)).fetchone() == (None, code)


def invalidate(admin_url, user, change):
    with psycopg.connect(admin_url) as conn:
        if change == 'revoke':
            conn.execute('DELETE FROM workspace_members WHERE workspace_id=%s AND user_id=%s', (user.workspace_id,user.user_id))
        elif change == 'reader':
            conn.execute("UPDATE workspace_members SET role='viewer' WHERE workspace_id=%s AND user_id=%s", (user.workspace_id,user.user_id))
        elif change == 'disable':
            conn.execute('UPDATE auth_users SET disabled=true WHERE id=%s', (user.user_id,))
        else:
            conn.execute('UPDATE documents SET deleted_at=now() WHERE workspace_id=%s', (user.workspace_id,))


def test_finish_retry_and_completed_dedupe(jobs, admin_url):
    queue, worker, users, chunks = jobs
    job = queue.enqueue(users[0], (chunks[0],), 'v1')
    first = worker.claim(uuid4(), 120)
    assert worker.finish(first, error='rate_limited', retry_seconds=90) == 'pending'
    assert worker.claim(uuid4(), 120) is None
    with psycopg.connect(admin_url) as conn:
        assert conn.execute('SELECT available_at>now()+interval \'85 seconds\' FROM analysis_jobs WHERE id=%s', (job,)).fetchone()[0]
        conn.execute('UPDATE analysis_jobs SET available_at=now() WHERE id=%s', (job,))
    second = worker.claim(uuid4(), 120)
    assert second.job_id == job and second.attempts == 2
    assert worker.finish(second, result={'observations': []}, metadata={}) == 'completed'
    assert worker.finish(second, error='internal_error') == 'lease_lost'
    assert queue.enqueue(users[0], (chunks[0],), 'v1') == job
    assert worker.claim(uuid4(), 120) is None


@pytest.mark.parametrize('code', ['provider_auth','configuration','invalid_request','invalid_output','provider_failure'])
def test_permanent_failure_is_terminal(jobs, code):
    queue, worker, users, chunks = jobs
    job = queue.enqueue(users[0], (chunks[0],), 'v1')
    claim = worker.claim(uuid4(), 120)
    assert worker.finish(claim, error=code, retry_seconds=0) == 'failed'
    assert queue.enqueue(users[0], (chunks[0],), 'v1') == job
    assert worker.claim(uuid4(), 120) is None


def test_retry_exhaustion(jobs):
    queue, worker, users, chunks = jobs
    job = queue.enqueue(users[0], (chunks[0],), 'v1', 2)
    assert worker.finish(worker.claim(uuid4(), 120), error='network', retry_seconds=0) == 'pending'
    second = worker.claim(uuid4(), 120)
    assert second.job_id == job and second.attempts == 2
    assert worker.finish(second, error='network', retry_seconds=0) == 'failed'
    assert worker.claim(uuid4(), 120) is None


class FakeAnalyzer:
    def __init__(self, error=None, invalid=False):
        self.calls, self.error, self.invalid = 0, error, invalid

    async def analyze(self, evidence):
        from app.ai_engine.analysis import AnalysisResult, AnalysisMetadata, TextAnalysis
        from app.ai_engine.prompts import PROMPT_VERSION, SCHEMA_VERSION
        self.calls += 1
        if self.error:
            raise self.error
        analysis = TextAnalysis.model_validate({'observations': [{
            'category': 'decision', 'text': 'Use PostgreSQL.',
            'evidence': [{'source_id': 'invented' if self.invalid else evidence[0].source_id,
                          'quote': evidence[0].content}]}]})
        return AnalysisResult(analysis, AnalysisMetadata(
            configured_model='openai/gpt-oss-20b', returned_model='openai/gpt-oss-20b',
            prompt_version=PROMPT_VERSION, schema_version=SCHEMA_VERSION,
            validation_outcome='valid', input_tokens=12, completion_tokens=8, finish_reason='stop'))


def processor_for(jobs, analyzer):
    from app.config import AISettings
    from app.services.analysis_jobs import AnalysisJobService, AnalysisProcessor
    from app.workers.config import WorkerSettings
    queue, worker, users, chunks = jobs
    ai, settings = AISettings(), WorkerSettings()
    job_id = AnalysisJobService(queue, ai, settings).enqueue(users[0], (chunks[0],))
    return job_id, AnalysisProcessor(worker, analyzer, ai, settings)


def test_full_pipeline_and_no_transaction_while_analyzer_blocked(jobs, admin_url):
    import asyncio
    async def scenario():
        started, release = asyncio.Event(), asyncio.Event()
        class Blocked(FakeAnalyzer):
            async def analyze(self, evidence):
                started.set()
                await release.wait()
                return await super().analyze(evidence)
        analyzer = Blocked()
        job, processor = processor_for(jobs, analyzer)
        task = asyncio.create_task(processor.process_one())
        await asyncio.wait_for(started.wait(), 3)
        try:
            with psycopg.connect(admin_url) as conn:
                assert conn.execute("SELECT count(*) FROM pg_stat_activity WHERE application_name='flare-analysis-worker'").fetchone() == (0,)
                assert conn.execute('SELECT status,attempts FROM analysis_jobs WHERE id=%s', (job,)).fetchone() == ('processing',1)
            # Another process cannot claim a job with a valid lease.
            assert await asyncio.to_thread(jobs[1].claim, uuid4(), 120) is None
        finally:
            release.set()
        assert await task == 'completed'
        assert await processor.process_one() is None
        with psycopg.connect(admin_url) as conn:
            result, metadata = conn.execute('SELECT result,metadata FROM analysis_jobs WHERE id=%s', (job,)).fetchone()
            assert result['observations'][0]['evidence'][0]['source_id'] == str(jobs[3][0])
            assert metadata['validation_outcome'] == 'valid' and metadata['input_tokens'] == 12
        assert analyzer.calls == 1
    asyncio.run(scenario())


@pytest.mark.parametrize('change', ['revoke','reader','disable','delete'])
def test_authorization_changed_during_analyzer_discards_result(jobs, admin_url, change):
    import asyncio
    class Revoking(FakeAnalyzer):
        async def analyze(self, evidence):
            invalidate(admin_url, jobs[2][0], change)
            return await super().analyze(evidence)
    job, processor = processor_for(jobs, Revoking())
    assert asyncio.run(processor.process_one()) == 'failed'
    with psycopg.connect(admin_url) as conn:
        row = conn.execute('SELECT result,metadata,last_error_code FROM analysis_jobs WHERE id=%s', (job,)).fetchone()
        assert row == (None, None, 'source_invalid' if change == 'delete' else 'authorization_revoked')


@pytest.mark.parametrize('kind', ['invalid', 'private_exception', 'permanent', 'transient', 'retry_after'])
def test_processor_errors_are_safe_and_retryable(jobs, admin_url, kind, caplog):
    import asyncio
    from app.ai_engine.errors import AnalysisError
    errors = {
        'private_exception': RuntimeError('PRIVATE_NOTE_TEXT secret-provider-key'),
        'permanent': AnalysisError('provider_auth'),
        'transient': AnalysisError('network', retryable=True),
        'retry_after': AnalysisError('rate_limited', retryable=True, retry_after_seconds=123),
    }
    job, processor = processor_for(jobs, FakeAnalyzer(errors.get(kind), invalid=kind == 'invalid'))
    assert asyncio.run(processor.process_one()) == ('pending' if kind in ('transient','retry_after') else 'failed')
    with psycopg.connect(admin_url) as conn:
        row = conn.execute('SELECT result,last_error_code,available_at>now()+interval \'120 seconds\' FROM analysis_jobs WHERE id=%s', (job,)).fetchone()
        assert row[0] is None
        assert row[1] == {'invalid':'invalid_output','private_exception':'internal_error',
                          'permanent':'provider_auth','transient':'network','retry_after':'rate_limited'}[kind]
        if kind == 'retry_after':
            assert row[2]
    assert 'PRIVATE_NOTE_TEXT' not in caplog.text and 'secret-provider-key' not in caplog.text


def test_revoke_before_processing_never_calls_analyzer(jobs, admin_url):
    import asyncio
    fake = FakeAnalyzer()
    _, processor = processor_for(jobs, fake)
    invalidate(admin_url, jobs[2][0], 'revoke')
    assert asyncio.run(processor.process_one()) == 'failed' and fake.calls == 0


def test_worker_rejects_admin_connection(admin_url):
    from app.models.analysis_jobs import WorkerJobs, JobUnavailable
    with pytest.raises(JobUnavailable):
        WorkerJobs(admin_url).claim(uuid4(), 120)


def test_pipeline_mismatch_does_not_call_analyzer(jobs):
    import asyncio
    from app.config import AISettings
    from app.services.analysis_jobs import AnalysisProcessor
    from app.workers.config import WorkerSettings
    queue, worker, users, chunks = jobs
    queue.enqueue(users[0], (chunks[0],), 'obsolete-pipeline')
    fake = FakeAnalyzer()
    processor = AnalysisProcessor(worker, fake, AISettings(), WorkerSettings())
    assert asyncio.run(processor.process_one()) == 'failed' and fake.calls == 0


def test_graceful_stop_finishes_current_job(jobs):
    import asyncio
    from app.workers.analysis_worker import run_loop
    async def scenario():
        stop = asyncio.Event()
        class StopAnalyzer(FakeAnalyzer):
            async def analyze(self, evidence):
                stop.set()
                return await super().analyze(evidence)
        _, processor = processor_for(jobs, StopAnalyzer())
        await run_loop(processor, stop)
        assert processor.analyzer.calls == 1
        assert await processor.process_one() is None
    asyncio.run(scenario())


@pytest.mark.parametrize('change', ['revoke', 'disable', 'delete'])
def test_finalization_serializes_with_inflight_revocation(jobs, admin_url, change):
    import threading
    from concurrent.futures import ThreadPoolExecutor
    queue, worker, users, chunks = jobs
    queue.enqueue(users[0], (chunks[0],), 'v1')
    claim = worker.claim(uuid4(), 120)
    assert 'evidence' in worker.evidence(claim, 5, 4000)
    started = threading.Event()
    def finish():
        started.set()
        return worker.finish(claim, result={'observations': []}, metadata={})
    with ThreadPoolExecutor(max_workers=1) as pool:
        with psycopg.connect(admin_url) as conn:
            if change == 'revoke':
                conn.execute('DELETE FROM workspace_members WHERE workspace_id=%s AND user_id=%s',
                             (users[0].workspace_id, users[0].user_id))
            elif change == 'disable':
                conn.execute('UPDATE auth_users SET disabled=true WHERE id=%s', (users[0].user_id,))
            else:
                conn.execute('UPDATE documents SET deleted_at=now() WHERE workspace_id=%s', (users[0].workspace_id,))
            future = pool.submit(finish)
            assert started.wait(2)
            # Wait for PostgreSQL to prove the finalizer is blocked on the exact
            # membership row held by this transaction, not merely thread scheduling.
            import time
            deadline = time.monotonic() + 3
            while time.monotonic() < deadline:
                with psycopg.connect(admin_url) as monitor:
                    waiting = monitor.execute("SELECT count(*) FROM pg_stat_activity WHERE application_name='flare-analysis-worker' AND wait_event_type='Lock'").fetchone()[0]
                if waiting:
                    break
                time.sleep(0.01)
            assert waiting == 1 and not future.done()
        assert future.result(timeout=3) == 'failed'


def test_force_rls_even_if_executor_owned_tenant_table(jobs, admin_url):
    # Rollback-only ownership change proves FORCE matters, including real rows.
    with psycopg.connect(admin_url) as conn:
        try:
            conn.execute('GRANT CREATE ON SCHEMA public TO flare_job_executor')
            conn.execute('ALTER TABLE public.documents OWNER TO flare_job_executor')
            conn.execute('SET LOCAL ROLE flare_job_executor')
            assert conn.execute('SELECT count(*) FROM public.documents').fetchone() == (0,)
            conn.execute("SELECT set_config('app.workspace_id',%s,true),set_config('app.user_id',%s,true)",
                         (str(jobs[2][0].workspace_id), jobs[2][0].user_id))
            assert conn.execute('SELECT count(*) FROM public.documents').fetchone() == (1,)
        finally:
            conn.rollback()


def test_independent_worker_process(jobs, admin_url):
    import subprocess
    import sys
    from pathlib import Path
    fake = FakeAnalyzer()
    job, _ = processor_for(jobs, fake)
    # Inject the deterministic analyzer into the real CLI lifecycle in a child
    # process; no Groq client/network request is created by this test.
    code = '''
import sys
from test_analysis_jobs import FakeAnalyzer
import app.workers.analysis_worker as worker
class Fake(FakeAnalyzer):
    def __init__(self, settings): super().__init__()
    async def __aenter__(self): return self
    async def __aexit__(self, *args): pass
worker.GroqTextAnalyzer = Fake
sys.argv = ['analysis_worker', '--once']
raise SystemExit(worker.main())
'''
    env = {**os.environ, 'PYTHONPATH': str(Path(__file__).parent.resolve()),
           'WORKER_DATABASE_URL': jobs[1]._database_url, 'GROQ_API_KEY': 'unused-test'}
    result = subprocess.run([sys.executable, '-c', code], env=env, capture_output=True, text=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert 'status=completed' in result.stderr
    with psycopg.connect(admin_url) as conn:
        assert conn.execute('SELECT status FROM analysis_jobs WHERE id=%s', (job,)).fetchone() == ('completed',)


def test_failed_row_can_be_explicitly_requeued_in_future(jobs, admin_url):
    queue, worker, users, chunks = jobs
    job = queue.enqueue(users[0], (chunks[0],), 'v1', 1)
    assert worker.finish(worker.claim(uuid4(), 120), error='provider_auth') == 'failed'
    # No runtime retry endpoint/capability is exposed. Prove schema permits a
    # future authorized requeue to reuse the same identity and uniqueness key.
    with psycopg.connect(admin_url) as conn:
        conn.execute("UPDATE analysis_jobs SET status='pending',attempts=0,completed_at=NULL,last_error_code=NULL,available_at=now() WHERE id=%s", (job,))
    assert worker.claim(uuid4(), 120).job_id == job


def test_dedupe_uses_sorted_snapshot_ids_and_results_stay_isolated(jobs):
    import asyncio
    from app.services.item_service import ItemService
    from app.services.analysis_jobs import AnalysisJobService, AnalysisProcessor
    from app.workers.config import WorkerSettings
    from app.config import AISettings
    queue, worker, users, chunks = jobs
    ItemService(queue.database, users[0]).create_note(title='Second', content='Second immutable source.')
    with queue.database.workspace_transaction(users[0]) as conn:
        selected = tuple(row['id'] for row in conn.execute('SELECT id FROM chunks ORDER BY id').fetchall())
    service = AnalysisJobService(queue, AISettings(), WorkerSettings())
    first = service.enqueue(users[0], selected)
    assert service.enqueue(users[0], tuple(reversed(selected))) == first
    second = service.enqueue(users[1], (chunks[1],))
    processor = AnalysisProcessor(worker, FakeAnalyzer(), AISettings(), WorkerSettings())
    assert asyncio.run(processor.process_one()) == 'completed'
    assert asyncio.run(processor.process_one()) == 'completed'
    for user, expected in zip(users, (first, second)):
        with queue.database.workspace_transaction(user) as conn:
            rows = conn.execute('SELECT id,result FROM analysis_jobs').fetchall()
            assert len(rows) == 1 and rows[0]['id'] == expected and rows[0]['result'] is not None
            assert {r['job_id'] for r in conn.execute('SELECT job_id FROM analysis_job_sources')} == {expected}


def test_analyzer_deadline_becomes_retry_without_holding_database(jobs):
    import asyncio
    from app.services.analysis_jobs import AnalysisJobService, AnalysisProcessor
    from app.workers.config import WorkerSettings
    from app.config import AISettings
    class NeverReturns(FakeAnalyzer):
        async def analyze(self, evidence):
            await asyncio.Event().wait()
    ai = AISettings(deadline_seconds=0.02)
    queue, worker, users, chunks = jobs
    AnalysisJobService(queue, ai, WorkerSettings()).enqueue(users[0], (chunks[0],))
    processor = AnalysisProcessor(worker, NeverReturns(), ai, WorkerSettings())
    assert asyncio.run(processor.process_one()) == 'pending'


def test_source_bounds_reject_before_analyzer(jobs):
    import asyncio
    from app.services.analysis_jobs import AnalysisJobService, AnalysisProcessor
    from app.workers.config import WorkerSettings
    from app.config import AISettings
    ai = AISettings(max_input_bytes=1)
    queue, worker, users, chunks = jobs
    AnalysisJobService(queue, ai, WorkerSettings()).enqueue(users[0], (chunks[0],))
    fake = FakeAnalyzer()
    processor = AnalysisProcessor(worker, fake, ai, WorkerSettings())
    assert asyncio.run(processor.process_one()) == 'failed' and fake.calls == 0
