"""Public Analyze acceptance through restricted runtime connections, no Groq network."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from uuid import UUID, uuid4
from dataclasses import replace

import psycopg
import pytest
from fastapi.testclient import TestClient

from app.config import AISettings, Settings
from app.models.database import WorkspaceIdentity
from app.models.analysis_runs import AnalysisRuns, DailyLimitReached
from app.services.analysis_jobs import AnalysisJobService, AnalysisProcessor
from app.services.context_selection import select_context
from app.ai_engine.prompts import build_bounded_request, request_size_bytes
from app.ai_engine.flare_config import FlareSettings
from app.services.flare_generation import FlareProcessor
from app.models.flare_runs import FlareRuns
from app.services.item_service import ItemService
from app.workers.config import WorkerSettings
from app.main import create_app
from test_analysis_jobs import jobs, admin_url, executor_role, FakeAnalyzer
from test_flare_runs import Detector, TEXT
from test_flares_api import client_for

pytestmark = pytest.mark.integration


def post(client, key=None, **kwargs):
    return client.post('/analyze', headers={'Origin': 'http://testserver', 'Idempotency-Key': str(key or uuid4())}, json={}, **kwargs)


def service(jobs, ai=None):
    return AnalysisJobService(jobs[0], ai or AISettings(), WorkerSettings())


def start(jobs, key=None, ai=None):
    return service(jobs, ai).start_run(jobs[2][0], key or uuid4(), FlareSettings().revision(ai or AISettings()))


def snapshot(admin_url, run_id):
    with psycopg.connect(admin_url) as c:
        return c.execute('SELECT s.chunk_id FROM analysis_runs r JOIN analysis_job_sources s ON s.job_id=r.analysis_job_id WHERE r.id=%s ORDER BY s.ordinal', (run_id,)).fetchall()


def test_public_auth_body_and_headers(jobs):
    with client_for(jobs) as c:
        for payload in ([], None, 'text', {'workspaceId': str(uuid4())}, {'sources': []}):
            response = c.post('/analyze', headers={'Origin':'http://testserver','Idempotency-Key':str(uuid4())}, json=payload)
            assert response.status_code == 422
        for key in ('bad', ''):
            assert c.post('/analyze', headers={'Origin':'http://testserver','Idempotency-Key':key}, json={}).status_code == 422
        assert c.post('/analyze', headers={'Origin':'http://testserver'}, json={}).status_code == 422
        assert c.post('/analyze', headers={'Origin':'http://evil.invalid','Idempotency-Key':str(uuid4())}, json={}).status_code == 403
        c.cookies.clear()
        assert post(c).status_code == 401
        assert c.get('/analysis-runs/' + str(uuid4())).status_code == 401


@pytest.mark.parametrize('role,status', [('owner',202),('editor',202),('viewer',403)])
def test_role_permissions(jobs, admin_url, role, status):
    with psycopg.connect(admin_url) as conn:
        conn.execute('UPDATE workspace_members SET role=%s WHERE workspace_id=%s AND user_id=%s', (role,jobs[2][0].workspace_id,jobs[2][0].user_id))
    with client_for(jobs) as c:
        assert post(c).status_code == status


def test_no_eligible_notes_and_no_partial_job(jobs, admin_url):
    with psycopg.connect(admin_url) as c:
        c.execute('UPDATE documents SET deleted_at=now() WHERE workspace_id=%s', (jobs[2][0].workspace_id,))
    with client_for(jobs) as c:
        response = post(c)
        assert response.status_code == 422 and response.json()['detail'] == 'no_eligible_context'
    with psycopg.connect(admin_url) as c:
        assert c.execute('SELECT count(*) FROM analysis_jobs').fetchone() == (0,)


def test_idempotency_concurrency_and_snapshot(jobs, admin_url):
    key = uuid4()
    with ThreadPoolExecutor(max_workers=4) as pool:
        responses = list(pool.map(lambda _: start(jobs, key), range(4)))
    assert len({r['id'] for r in responses}) == 1
    run_id = responses[0]['id']
    before = snapshot(admin_url, run_id)
    ItemService(jobs[0].database, jobs[2][0]).create_note(
        title='New', content='New goal: release next week.'
    )
    with psycopg.connect(admin_url) as c:
        c.execute('UPDATE documents SET deleted_at=now() WHERE workspace_id=%s', (jobs[2][0].workspace_id,))
    assert start(jobs, key)['id'] == run_id
    assert snapshot(admin_url, run_id) == before
    assert asyncio.run(AnalysisProcessor(jobs[1], FakeAnalyzer(), AISettings(), WorkerSettings()).process_one()) == 'failed'
    with client_for(jobs) as c:
        response = post(c, key)
        assert response.status_code == 200 and response.json()['error'] == 'source_invalid'
    with psycopg.connect(admin_url) as c:
        assert c.execute('SELECT count(*) FROM analysis_jobs').fetchone() == (1,)
        assert c.execute('SELECT count(*) FROM analysis_runs').fetchone() == (1,)


def test_selection_bounds_determinism_and_isolation(jobs, admin_url):
    ai = replace(AISettings(), max_sources=2)
    notes = ItemService(jobs[0].database, jobs[2][0])
    notes.create_note(title='Huge', content='x' * 5000)
    notes.create_note(title='Goal', content='Our goal is the MVP release. Deadline next week.')
    note = notes.create_note(title='Latest', content='Current project state: analysis is incomplete.')
    a = start(jobs, ai=ai)
    assert a['selectedChunkCount'] == 2
    with psycopg.connect(admin_url) as c:
        rows = c.execute('SELECT c.id,c.content,c.workspace_id FROM analysis_job_sources s JOIN chunks c ON c.id=s.chunk_id JOIN analysis_runs r ON r.analysis_job_id=s.job_id WHERE r.id=%s',(a['id'],)).fetchall()
        assert all(row[2] == jobs[2][0].workspace_id for row in rows)
    from app.ai_engine.analysis import Evidence
    assert request_size_bytes(build_bounded_request([Evidence(source_id=str(r[0]),content=r[1]) for r in rows], ai)) <= ai.max_input_bytes


def test_atomic_transaction_rollback(jobs, admin_url):
    queue, _, users, _ = jobs
    with pytest.raises(RuntimeError):
        with queue.database.workspace_transaction(users[0], write=True) as c:
            AnalysisRuns.start(c, users[0], uuid4(), AISettings(), 'test', 'test', 3)
            raise RuntimeError('abort API transaction')
    with psycopg.connect(admin_url) as c:
        assert c.execute('SELECT count(*) FROM analysis_jobs').fetchone() == (0,)
        assert c.execute('SELECT count(*) FROM analysis_runs').fetchone() == (0,)
        assert c.execute('SELECT count(*) FROM analysis_cycles').fetchone() == (0,)


def test_status_membership_and_stages(jobs, admin_url):
    run = start(jobs)
    with client_for(jobs, 1) as c:
        assert c.get('/analysis-runs/' + run['id']).status_code == 404
    with client_for(jobs) as c:
        assert c.get('/analysis-runs/' + str(uuid4())).status_code == 404
        assert c.get('/analysis-runs/' + run['id']).json()['stage'] == 'analysis'
        claim = jobs[1].claim(uuid4(),120)
        assert c.get('/analysis-runs/' + run['id']).json()['status'] == 'processing'
        jobs[1].finish(claim,result={'observations':[]},metadata={})
        assert c.get('/analysis-runs/' + run['id']).json()['stage'] == 'flare_generation'
        runs = FlareRuns(jobs[1]._database_url)
        generation = runs.claim(uuid4(),120)
        assert c.get('/analysis-runs/' + run['id']).json()['status'] == 'processing'
        runs.finish(generation,error='provider_auth')
        result = c.get('/analysis-runs/' + run['id'])
        assert result.headers['cache-control'] == 'no-store'
        assert result.json()['error'] == 'provider_auth' and result.json()['stage'] == 'failed'
        assert set(result.json()) == {'id','status','stage','selectedChunkCount','flareIds','error'}


@pytest.mark.parametrize('empty', [False,True])
def test_register_notes_analyze_worker_flares_e2e(jobs, admin_url, empty):
    cfg = Settings(database_url=None,cors_origins=['http://testserver'],environment='test')
    with TestClient(create_app(cfg,database=jobs[0].database),headers={'Origin':'http://testserver'}) as c:
        assert c.post('/auth/register',json={'email':f'{uuid4()}@jobs-test.invalid','password':'a-long-test-password','name':'Analyze Test'}).status_code == 201
        me = c.get('/auth/me').json()
        jobs[2].append(WorkspaceIdentity(UUID(me['workspace']['id']),me['user']['id']))
        for text in (TEXT, 'The deadline is this week.', 'We decided to finish the MVP before adding integrations.'):
            assert c.post('/items',json={'type':'note','content':text}).status_code == 201
        # This case exercises the explicit Analyze orchestration. Automatic
        # per-capture jobs have separate API coverage and must not determine
        # which global worker claim advances the run below.
        with psycopg.connect(admin_url) as db:
            db.execute(
                '''DELETE FROM analysis_jobs j
                   WHERE j.workspace_id=%s
                     AND NOT EXISTS (
                         SELECT 1 FROM analysis_runs r WHERE r.analysis_job_id=j.id
                     )''',
                (jobs[2][-1].workspace_id,),
            )
        key=uuid4(); response=post(c,key)
        assert response.status_code == 202, response.text
        run=response.json()
        assert asyncio.run(AnalysisProcessor(jobs[1],FakeAnalyzer(),AISettings(),WorkerSettings()).process_one()) == 'completed'
        assert c.get('/analysis-runs/'+run['id']).json()['stage']=='flare_generation'
        assert asyncio.run(FlareProcessor(FlareRuns(jobs[1]._database_url),Detector(empty=empty),AISettings(),FlareSettings(),WorkerSettings()).process_one())=='completed'
        terminal=c.get('/analysis-runs/'+run['id']).json()
        assert terminal['status']=='completed' and terminal['stage']=='completed'
        flares=c.get('/flares').json()
        assert len(flares)==(0 if empty else 1)
        assert terminal['flareIds']==[f['id'] for f in flares]
        if flares:
            with psycopg.connect(admin_url) as db:
                evidence=db.execute('SELECT chunk_id FROM insight_sources WHERE insight_id=%s',(flares[0]['id'],)).fetchall()
            assert set(evidence).issubset(set(snapshot(admin_url,run['id'])))
        assert post(c,key).status_code==200


def test_terminal_failure_keeps_daily_slot_consumed(jobs):
    first=start(jobs)
    claim=jobs[1].claim(uuid4(),120)
    assert jobs[1].finish(claim,error='invalid_output')=='failed'
    with pytest.raises(DailyLimitReached):
        start(jobs)
    assert jobs[1].claim(uuid4(),120) is None


def test_run_privileges_and_rls(jobs, admin_url):
    run=start(jobs)
    with psycopg.connect(admin_url) as c:
        assert c.execute("SELECT relrowsecurity,relforcerowsecurity FROM pg_class WHERE oid='analysis_runs'::regclass").fetchone()==(True,True)
        for role in ('flare_app','flare_worker'):
            assert not c.execute("SELECT has_table_privilege(%s,'analysis_runs','INSERT,UPDATE,DELETE')",(role,)).fetchone()[0]
        functions=c.execute("SELECT proname,pg_get_userbyid(proowner),proconfig FROM pg_proc WHERE proname IN ('start_analysis_run','read_analysis_run')").fetchall()
        assert len(functions)==2 and all(row[1:]==(executor_role(),['search_path=pg_catalog, public, pg_temp']) for row in functions)
        assert c.execute("""SELECT count(*) FROM pg_proc p,LATERAL aclexplode(coalesce(p.proacl,acldefault('f',p.proowner))) a
            WHERE p.proname IN ('start_analysis_run','read_analysis_run') AND a.grantee=0 AND a.privilege_type='EXECUTE'""").fetchone()==(0,)
    with psycopg.connect(jobs[1]._database_url) as c:
        for sql in ('SELECT * FROM analysis_runs', "SELECT read_analysis_run('%s')" % run['id']):
            with pytest.raises(psycopg.errors.InsufficientPrivilege), c.transaction(): c.execute(sql)
    with jobs[0].database.connection() as c:
        assert c.execute('SELECT * FROM analysis_runs').fetchall()==[]


def test_other_workspace_member_can_read_run(jobs,admin_url):
    run=start(jobs)
    other=jobs[2][1]
    with psycopg.connect(admin_url) as c:
        c.execute("INSERT INTO workspace_members(workspace_id,user_id,role) VALUES(%s,%s,'viewer')",(jobs[2][0].workspace_id,other.user_id))
    identity=WorkspaceIdentity(jobs[2][0].workspace_id,other.user_id)
    assert service(jobs).read_run(identity,UUID(run['id']))['id']==run['id']


def test_cookie_required_even_in_development_mode(jobs):
    identity = jobs[2][0]
    cfg = Settings(database_url=None, cors_origins=['http://testserver'], environment='development',
                   dev_mode=True, dev_workspace_id=identity.workspace_id, dev_user_id=identity.user_id, dev_workspace_name='Test')
    with TestClient(create_app(cfg, database=jobs[0].database)) as c:
        assert post(c).status_code == 401
        assert c.get('/analysis-runs/' + str(uuid4())).status_code == 401


def test_recent_200_and_current_version_snapshot(jobs, admin_url):
    notes = ItemService(jobs[0].database, jobs[2][0])
    for number in range(201):
        notes.create_note(title=f'Note {number}', content=f'Project update {number}.')
    run = start(jobs)
    selected = snapshot(admin_url, run['id'])
    with psycopg.connect(admin_url) as c:
        eligible = c.execute('''SELECT ch.id FROM documents d JOIN chunks ch ON ch.document_version_id=d.current_version_id
            WHERE d.workspace_id=%s ORDER BY d.created_at DESC,d.id DESC LIMIT 200''', (jobs[2][0].workspace_id,)).fetchall()
        assert set(selected).issubset(set(eligible))
        chunk = selected[0][0]
        document, old_version = c.execute('SELECT v.document_id,v.id FROM document_versions v JOIN chunks ch ON ch.document_version_id=v.id WHERE ch.id=%s', (chunk,)).fetchone()
        version = uuid4()
        c.execute("INSERT INTO document_versions(id,workspace_id,document_id,version_number,content_hash,parser_version,state) VALUES(%s,%s,%s,2,%s,'manual-note-v1','processing')", (version,jobs[2][0].workspace_id,document,'f'*64))
        c.execute("INSERT INTO chunks(id,workspace_id,document_version_id,ordinal,content,locator) VALUES(%s,%s,%s,0,'Edited project goal','{}')", (uuid4(),jobs[2][0].workspace_id,version))
        c.execute("UPDATE document_versions SET state='ready' WHERE id=%s", (version,))
        c.execute('UPDATE documents SET current_version_id=%s WHERE id=%s', (version,document))
    assert snapshot(admin_url,run['id']) == selected
    with pytest.raises(DailyLimitReached):
        start(jobs)


def test_safe_database_failure(jobs, monkeypatch):
    def unavailable(*args, **kwargs):
        raise psycopg.OperationalError('private connection details must not escape')
    monkeypatch.setattr(AnalysisRuns, 'start', unavailable)
    with client_for(jobs) as c:
        response = post(c)
        assert response.status_code == 503
        assert response.json() == {'detail': 'database_unavailable'}
