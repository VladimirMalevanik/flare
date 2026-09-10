"""Real PostgreSQL stage, race, RLS and atomicity acceptance tests."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from uuid import uuid4

import psycopg
import pytest
from app.ai_engine.analysis import AnalysisMetadata
from app.ai_engine.flare_config import FlareSettings
from app.ai_engine.flare_prompts import PROMPT_VERSION, SCHEMA_VERSION
from app.ai_engine.flares import FlareResult, FlareCandidates, candidate_fingerprint
from app.ai_engine.errors import AnalysisError
from app.config import AISettings
from app.models.flare_runs import FlareRuns
from app.services.flare_generation import FlareProcessor
from app.services.item_service import ItemService
from app.workers.config import WorkerSettings
from test_analysis_jobs import jobs, admin_url, invalidate, executor_role

pytestmark=pytest.mark.integration
TEXT='Our goal is to ship the MVP this week, but the core analysis flow is unfinished.'


def metadata():
    return AnalysisMetadata(configured_model=AISettings().model,returned_model=AISettings().model,
        prompt_version=PROMPT_VERSION,schema_version=SCHEMA_VERSION,validation_outcome='valid',
        finish_reason='stop',input_tokens=100,completion_tokens=90)


class Detector:
    def __init__(self,error=None,empty=False): self.calls=0; self.error=error; self.empty=empty
    async def detect(self,analysis,evidence):
        self.calls+=1
        if self.error: raise self.error
        c={'type':'Recommendation','title':'Finish the core flow',
           'statement':'The release target is at risk while the central analysis path remains unfinished.',
           'action':'Complete analysis and evidence display before taking on integrations.',
           'reason':'The stated deadline leaves only this week for the core implementation.',
           'evidence':[{'source_id':evidence[0].source_id,'quote':evidence[0].content,'supports':['goal','state']}]}
        return FlareResult(FlareCandidates(flares=[] if self.empty else [c]),metadata())


@pytest.fixture
def stage(jobs):
    queue,worker,users,_=jobs
    note=ItemService(queue.database,users[0]).create_note(title='Goal',content=TEXT)
    with queue.database.workspace_transaction(users[0]) as conn:
        chunk=conn.execute('SELECT c.id FROM chunks c JOIN document_versions v ON v.id=c.document_version_id WHERE v.document_id=%s',(note.id,)).fetchone()['id']
    parent=queue.enqueue(users[0],(chunk,),'test-stage1')
    claim=worker.claim(uuid4(),120)
    assert claim.job_id==parent
    assert worker.finish(claim,result={'observations':[]},metadata={})=='completed'
    runs=FlareRuns(worker._database_url)
    return runs,parent,chunk,users[0]


def processor(stage,detector):
    return FlareProcessor(stage[0],detector,AISettings(),FlareSettings(),WorkerSettings())


def test_handoff_and_success(stage,admin_url):
    runs,parent,chunk,user=stage
    with psycopg.connect(admin_url) as c:
        row=c.execute('SELECT id,generation_revision FROM flare_generation_runs WHERE analysis_job_id=%s',(parent,)).fetchone()
        assert row and row[1]==FlareSettings().revision(AISettings())
    assert runs.enqueue(parent,row[1])==row[0]
    fake=Detector()
    assert asyncio.run(processor(stage,fake).process_one())=='completed'
    assert asyncio.run(processor(stage,fake).process_one()) is None
    with psycopg.connect(admin_url) as c:
        flare=c.execute('SELECT id,candidate_fingerprint FROM insights WHERE source_analysis_job_id=%s',(parent,)).fetchone()
        candidate=asyncio.run(Detector().detect(None,[type('E',(),{'source_id':str(chunk),'content':TEXT})()])).candidates.flares[0]
        assert flare[1]==candidate_fingerprint(user.workspace_id,row[1],candidate)
        assert c.execute('SELECT quote,ordinal FROM insight_sources WHERE insight_id=%s',(flare[0],)).fetchone()==(TEXT,0)
        assert c.execute('SELECT flare_ids,status FROM flare_generation_runs WHERE id=%s',(row[0],)).fetchone()==([flare[0]],'completed')
        saved = c.execute('SELECT metadata FROM flare_generation_runs WHERE id=%s', (row[0],)).fetchone()[0]
        assert set(saved) == {'configured_model','returned_model','prompt_version','schema_version',
                              'request_id','completion_id','finish_reason','validation_outcome',
                              'input_tokens','completion_tokens','latency_ms'}
    assert fake.calls==1


def test_retry_only_stage2(stage,admin_url):
    detector=Detector(AnalysisError('rate_limited',retryable=True,retry_after_seconds=90))
    p=processor(stage,detector)
    assert asyncio.run(p.process_one())=='pending'
    with psycopg.connect(admin_url) as c:
        before=c.execute('SELECT result,attempts FROM analysis_jobs WHERE id=%s',(stage[1],)).fetchone()
        assert before==({'observations':[]},1)
        assert c.execute("SELECT available_at>now()+interval '85 seconds' FROM flare_generation_runs WHERE analysis_job_id=%s",(stage[1],)).fetchone()[0]
        c.execute('UPDATE flare_generation_runs SET available_at=now() WHERE analysis_job_id=%s',(stage[1],))
    detector.error=None
    assert asyncio.run(p.process_one())=='completed'
    with psycopg.connect(admin_url) as c:
        assert c.execute('SELECT result,attempts FROM analysis_jobs WHERE id=%s',(stage[1],)).fetchone()==before
        assert c.execute('SELECT attempts FROM flare_generation_runs WHERE analysis_job_id=%s',(stage[1],)).fetchone()==(2,)


def test_no_connection_during_detector(stage,admin_url):
    async def run():
        started,release=asyncio.Event(),asyncio.Event()
        class Blocked(Detector):
            async def detect(self,a,e):
                started.set(); await release.wait(); return await super().detect(a,e)
        task=asyncio.create_task(processor(stage,Blocked()).process_one())
        await asyncio.wait_for(started.wait(),3)
        try:
            with psycopg.connect(admin_url) as c:
                assert c.execute("SELECT count(*) FROM pg_stat_activity WHERE application_name='flare-analysis-worker'").fetchone()==(0,)
        finally: release.set()
        assert await task=='completed'
    asyncio.run(run())


@pytest.mark.parametrize('change',['revoke','disable','reader','delete'])
@pytest.mark.parametrize('during',[False,True])
def test_invalidation(stage,admin_url,change,during):
    class Invalidating(Detector):
        async def detect(self,a,e):
            if during: invalidate(admin_url,stage[3],change)
            return await super().detect(a,e)
    fake=Invalidating()
    if not during: invalidate(admin_url,stage[3],change)
    assert asyncio.run(processor(stage,fake).process_one())=='failed'
    assert fake.calls==int(during)
    with psycopg.connect(admin_url) as c:
        assert c.execute('SELECT count(*) FROM insights WHERE source_analysis_job_id=%s',(stage[1],)).fetchone()==(0,)


def test_claim_expiry_and_fencing(stage,admin_url):
    runs=stage[0]
    with ThreadPoolExecutor(max_workers=2) as pool:
        values=list(pool.map(lambda _:runs.claim(uuid4(),120),range(2)))
    first=next(v for v in values if v)
    assert sum(v is not None for v in values)==1
    with psycopg.connect(admin_url) as c:
        c.execute("UPDATE flare_generation_runs SET lease_expires_at=now()-interval '1 second' WHERE id=%s",(first['id'],))
    second=runs.claim(uuid4(),120)
    assert second['id']==first['id'] and second['attempts']==2 and second['lease_token']!=first['lease_token']
    assert runs.finish(first,error='internal_error')=='lease_lost'


def test_atomic_persistence_rollback(stage,admin_url):
    from dataclasses import asdict
    runs=stage[0]; claim=runs.claim(uuid4(),120)
    loaded=runs.load(claim,5,4000)
    from app.ai_engine.analysis import Evidence
    result=asyncio.run(Detector().detect(None,[Evidence.model_validate(e) for e in loaded['evidence']]))
    good=result.candidates.flares[0].model_dump()
    bad={**good,'title':'Another candidate','evidence':[{'source_id':str(uuid4()),'quote':'invented','supports':['state']}]}
    with pytest.raises(psycopg.errors.InvalidParameterValue):
        runs.finish(claim,flares=[good,bad],metadata=asdict(metadata()))
    with psycopg.connect(admin_url) as c:
        assert c.execute('SELECT count(*) FROM insights WHERE source_analysis_job_id=%s',(stage[1],)).fetchone()==(0,)
        assert c.execute('SELECT status FROM flare_generation_runs WHERE id=%s',(claim['id'],)).fetchone()==('processing',)
    assert runs.finish(claim,flares=[good],metadata=asdict(metadata()))=='completed'


def test_empty_result_and_new_revision(stage,admin_url):
    assert asyncio.run(processor(stage,Detector(empty=True)).process_one())=='completed'
    old=FlareSettings().revision(AISettings())
    new=FlareSettings(max_completion_tokens=1025)
    assert stage[0].enqueue(stage[1],old)!=stage[0].enqueue(stage[1],new.revision(AISettings()))
    p=FlareProcessor(stage[0],Detector(),AISettings(),new,WorkerSettings())
    assert asyncio.run(p.process_one())=='completed'


def test_atomic_stage1_rollback(jobs,admin_url):
    queue,worker,users,chunks=jobs
    parent=queue.enqueue(users[0],(chunks[0],),'test')
    claim=worker.claim(uuid4(),120)
    with psycopg.connect(admin_url) as c:
        c.execute('SET LOCAL ROLE flare_worker')
        c.execute("SELECT public.finish_analysis_job(%s,%s,'{\"observations\":[]}','{}',NULL,NULL)",(parent,claim.lease_token))
        c.execute('RESET ROLE')
        assert c.execute('SELECT count(*) FROM flare_generation_runs WHERE analysis_job_id=%s',(parent,)).fetchone()==(1,)
        c.rollback()
    with psycopg.connect(admin_url) as c:
        assert c.execute('SELECT status FROM analysis_jobs WHERE id=%s',(parent,)).fetchone()==('processing',)
        assert c.execute('SELECT count(*) FROM flare_generation_runs WHERE analysis_job_id=%s',(parent,)).fetchone()==(0,)


def test_semantic_order_not_uuid(jobs,admin_url):
    queue,_,users,_=jobs
    ItemService(queue.database,users[0]).create_note(title='Other',content='Other note')
    with queue.database.workspace_transaction(users[0]) as c:
        rows=c.execute('SELECT c.id,v.document_id FROM chunks c JOIN document_versions v ON v.id=c.document_version_id ORDER BY c.id').fetchall()
    with psycopg.connect(admin_url) as c:
        c.execute("UPDATE documents SET created_at='2020-01-01' WHERE id=%s",(rows[1]['document_id'],))
        c.execute("UPDATE documents SET created_at='2021-01-01' WHERE id=%s",(rows[0]['document_id'],))
    ids=tuple(r['id'] for r in rows)
    parent=queue.enqueue(users[0],ids,'order')
    assert parent==queue.enqueue(users[0],tuple(reversed(ids)),'order')
    with queue.database.workspace_transaction(users[0]) as c:
        assert [r['chunk_id'] for r in c.execute('SELECT chunk_id FROM analysis_job_sources WHERE job_id=%s ORDER BY ordinal',(parent,))]==list(reversed(ids))


def test_grants_and_function_security(admin_url):
    with psycopg.connect(admin_url) as c:
        for table in ('insights','insight_sources'):
            assert not c.execute("SELECT has_table_privilege('flare_app',%s,'INSERT,UPDATE,DELETE')",(table,)).fetchone()[0]
        for table in ('insights','insight_sources','flare_generation_runs'):
            assert not c.execute("SELECT has_table_privilege('flare_worker',%s,'SELECT,INSERT,UPDATE,DELETE')",(table,)).fetchone()[0]
            assert c.execute('SELECT relrowsecurity,relforcerowsecurity FROM pg_class WHERE oid=%s::regclass',(table,)).fetchone()==(True,True)
        funcs=c.execute("SELECT p.proname,p.proconfig,r.rolname,r.rolcanlogin,r.rolsuper,r.rolbypassrls,r.rolcreatedb,r.rolcreaterole FROM pg_proc p JOIN pg_roles r ON r.oid=p.proowner WHERE p.prosecdef AND p.proname LIKE '%flare_generation%'").fetchall()
        assert len(funcs)==5
        owner = executor_role()
        assert all(row[1:]==(['search_path=pg_catalog, public, pg_temp'],owner,owner == 'flare_owner',False,False,False,False) for row in funcs)
        assert not c.execute("SELECT has_function_privilege('flare_app','public.finish_flare_generation(uuid,uuid,jsonb,jsonb,text,double precision)','EXECUTE')").fetchone()[0]


@pytest.mark.parametrize('code', ['configuration','provider_auth','invalid_request','invalid_output'])
def test_permanent_error_stops_stage2(stage, admin_url, code):
    fake = Detector(AnalysisError(code, retryable=True))
    assert asyncio.run(processor(stage, fake).process_one()) == 'failed'
    assert asyncio.run(processor(stage, fake).process_one()) is None
    with psycopg.connect(admin_url) as c:
        assert c.execute('SELECT status,last_error_code,attempts FROM flare_generation_runs WHERE analysis_job_id=%s',
                         (stage[1],)).fetchone() == ('failed', code, 1)


@pytest.mark.parametrize('crash', [False, True])
def test_stage2_attempt_limit(stage, admin_url, crash):
    with psycopg.connect(admin_url) as c:
        c.execute('UPDATE flare_generation_runs SET max_attempts=1 WHERE analysis_job_id=%s', (stage[1],))
    if crash:
        claim = stage[0].claim(uuid4(), 120)
        with psycopg.connect(admin_url) as c:
            c.execute("UPDATE flare_generation_runs SET lease_expires_at=now()-interval '1 second' WHERE id=%s", (claim['id'],))
        assert stage[0].claim(uuid4(), 120) is None
    else:
        assert asyncio.run(processor(stage, Detector(AnalysisError('network', retryable=True))).process_one()) == 'failed'
    with psycopg.connect(admin_url) as c:
        assert c.execute('SELECT status,attempts,lease_token FROM flare_generation_runs WHERE analysis_job_id=%s',
                         (stage[1],)).fetchone() == ('failed', 1, None)


def test_concurrent_parents_dedupe_same_candidate(stage, jobs, admin_url):
    queue, worker, users, _ = jobs
    other = queue.enqueue(users[0], (stage[2],), 'other-extraction-revision')
    claim = worker.claim(uuid4(), 120)
    assert claim.job_id == other
    assert worker.finish(claim, result={'observations':[]}, metadata={}) == 'completed'
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: asyncio.run(processor(stage, Detector()).process_one()), range(2)))
    assert results == ['completed', 'completed']
    with psycopg.connect(admin_url) as c:
        rows = c.execute('SELECT flare_ids FROM flare_generation_runs WHERE analysis_job_id=ANY(%s)',
                         ([stage[1],other],)).fetchall()
        assert len(rows) == 2 and len(rows[0][0]) == 1 and rows[0] == rows[1]
        assert c.execute('SELECT count(*) FROM insights WHERE workspace_id=%s', (users[0].workspace_id,)).fetchone() == (1,)


def test_foreign_chunk_with_exact_quote_rejected(stage, jobs, admin_url):
    from dataclasses import asdict
    from app.ai_engine.analysis import Evidence
    runs = stage[0]
    claim = runs.claim(uuid4(), 120)
    result = asyncio.run(Detector().detect(None, [Evidence(source_id=str(stage[2]), content=TEXT)]))
    candidate = result.candidates.flares[0].model_dump()
    with psycopg.connect(admin_url) as c:
        foreign = c.execute('SELECT id,content FROM chunks WHERE workspace_id=%s LIMIT 1', (jobs[2][1].workspace_id,)).fetchone()
    candidate['evidence'] = [{'source_id':str(foreign[0]), 'quote':foreign[1], 'supports':['goal','state']}]
    with pytest.raises(psycopg.errors.InvalidParameterValue):
        runs.finish(claim, flares=[candidate], metadata=asdict(metadata()))
    with psycopg.connect(admin_url) as c:
        assert c.execute('SELECT count(*) FROM insights WHERE source_analysis_job_id=%s', (stage[1],)).fetchone() == (0,)


def test_lease_expiry_during_persistence_rolls_back(stage, admin_url):
    from dataclasses import asdict
    from app.ai_engine.analysis import Evidence
    runs = stage[0]
    claim = runs.claim(uuid4(), 1)
    result = asyncio.run(Detector().detect(None, [Evidence(source_id=str(stage[2]), content=TEXT)]))
    # Test-only delay after the first insert, scoped to this run's workspace.
    with psycopg.connect(admin_url) as c:
        c.execute("""CREATE FUNCTION public.test_flare_insert_delay() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN IF NEW.workspace_id::text=current_setting('test.flare_workspace',true) THEN
                PERFORM pg_sleep(1.1); END IF; RETURN NEW; END $$""")
        c.execute('CREATE TRIGGER test_flare_insert_delay AFTER INSERT ON public.insights FOR EACH ROW EXECUTE FUNCTION public.test_flare_insert_delay()')
    try:
        with psycopg.connect(admin_url) as c:
            c.execute("SELECT set_config('test.flare_workspace',%s,true)", (str(stage[3].workspace_id),))
            c.execute('SET LOCAL ROLE flare_worker')
            from psycopg.types.json import Jsonb
            with pytest.raises(psycopg.errors.SerializationFailure):
                c.execute('SELECT public.finish_flare_generation(%s,%s,%s,%s,NULL,NULL)',
                          (claim['id'], claim['lease_token'], Jsonb([result.candidates.flares[0].model_dump()]), Jsonb(asdict(metadata()))))
        with psycopg.connect(admin_url) as c:
            assert c.execute('SELECT count(*) FROM insights WHERE source_analysis_job_id=%s', (stage[1],)).fetchone() == (0,)
            assert c.execute('SELECT status FROM flare_generation_runs WHERE id=%s', (claim['id'],)).fetchone() == ('processing',)
        recovered = runs.claim(uuid4(), 120)
        assert recovered['id'] == claim['id'] and recovered['attempts'] == 2
    finally:
        with psycopg.connect(admin_url) as c:
            c.execute('DROP TRIGGER test_flare_insert_delay ON public.insights')
            c.execute('DROP FUNCTION public.test_flare_insert_delay()')


def test_effective_privileges_include_columns_and_public(admin_url):
    from app.models.database import TENANT_TABLES
    with psycopg.connect(admin_url) as c:
        for table in TENANT_TABLES:
            for privilege in ('SELECT', 'INSERT', 'UPDATE', 'DELETE', 'TRUNCATE', 'REFERENCES', 'TRIGGER'):
                assert not c.execute('SELECT has_table_privilege(%s,%s,%s)', ('flare_worker', table, privilege)).fetchone()[0]
            for privilege in ('SELECT', 'INSERT', 'UPDATE', 'REFERENCES'):
                assert not c.execute('SELECT has_any_column_privilege(%s,%s,%s)', ('flare_worker', table, privilege)).fetchone()[0]
        for table in ('insights', 'insight_sources', 'flare_generation_runs'):
            for privilege in ('INSERT', 'UPDATE', 'DELETE'):
                assert not c.execute('SELECT has_table_privilege(%s,%s,%s)', ('flare_app', table, privilege)).fetchone()[0]
            for privilege in ('INSERT', 'UPDATE'):
                assert not c.execute('SELECT has_any_column_privilege(%s,%s,%s)', ('flare_app', table, privilege)).fetchone()[0]
        assert c.execute("""SELECT count(*) FROM pg_proc p,
            LATERAL aclexplode(coalesce(p.proacl,acldefault('f',p.proowner))) a
            WHERE p.pronamespace='public'::regnamespace AND p.proname LIKE '%flare_generation%'
              AND a.grantee=0 AND a.privilege_type='EXECUTE'""").fetchone() == (0,)
        owner = executor_role()
        assert c.execute("SELECT rolcanlogin,rolsuper,rolbypassrls,rolcreatedb,rolcreaterole FROM pg_roles WHERE rolname=%s", (owner,)).fetchone() == (owner == 'flare_owner', False, False, False, False)
        assert c.execute("SELECT count(*) FROM pg_auth_members WHERE roleid=%s::regrole OR member=%s::regrole", (owner, owner)).fetchone() == (0,)
        if owner == 'flare_owner':
            assert c.execute("SELECT count(*) FROM pg_roles WHERE rolname='flare_job_executor'").fetchone() == (0,)
        for role in ('flare_worker', 'flare_app'):
            assert c.execute("SELECT rolsuper,rolbypassrls,rolcreatedb,rolcreaterole FROM pg_roles WHERE rolname=%s", (role,)).fetchone() == (False, False, False, False)
            assert c.execute("SELECT count(*) FROM pg_auth_members WHERE member=%s::regrole", (role,)).fetchone() == (0,)


def test_ordering_timestamp_ties_versions_and_chunks(jobs, admin_url):
    queue, _, users, _ = jobs
    from test_database import add_version
    docs = sorted([uuid4(), uuid4()])
    expected = []
    with psycopg.connect(admin_url) as c:
        for doc in docs:
            c.execute("INSERT INTO documents(id,workspace_id,title,source_type,created_at) VALUES(%s,%s,'Ordering','note','2020-01-01')", (doc, users[0].workspace_id))
            for version_number in (1, 2):
                version, first = add_version(c, users[0].workspace_id, doc, version_number, ready=False)
                second = uuid4()
                c.execute("INSERT INTO chunks(id,workspace_id,document_version_id,ordinal,content,locator) VALUES(%s,%s,%s,1,'Second chunk','{}')", (second, users[0].workspace_id, version))
                c.execute("UPDATE document_versions SET state='ready' WHERE id=%s", (version,))
                expected.extend([first, second])
    parent = queue.enqueue(users[0], tuple(reversed(expected)), 'ordering-ties')
    with queue.database.workspace_transaction(users[0]) as c:
        actual = [r['chunk_id'] for r in c.execute('SELECT chunk_id FROM analysis_job_sources WHERE job_id=%s ORDER BY ordinal', (parent,))]
    assert actual == expected
    assert queue.enqueue(users[0], tuple(sorted(expected)), 'ordering-ties') == parent
    with queue.database.workspace_transaction(users[0]) as c:
        assert [r['chunk_id'] for r in c.execute('SELECT chunk_id FROM analysis_job_sources WHERE job_id=%s ORDER BY ordinal', (parent,))] == expected


def test_runtime_connections_cannot_bypass_flare_capabilities(jobs):
    """Actual login roles, not admin sessions whose privileges could mask failures."""
    import os
    queue, worker, _, _ = jobs
    for role, url in [('flare_app', os.environ['DATABASE_URL']),
                      ('flare_worker', worker._database_url)]:
        with psycopg.connect(url) as c:
            assert c.execute('SELECT session_user,current_user').fetchone() == (role, role)
            for table in ('insights', 'insight_sources', 'flare_generation_runs'):
                for statement in (f'INSERT INTO public.{table} DEFAULT VALUES',
                                  f'UPDATE public.{table} SET workspace_id=workspace_id WHERE false',
                                  f'DELETE FROM public.{table} WHERE false'):
                    with pytest.raises(psycopg.errors.InsufficientPrivilege), c.transaction():
                        c.execute(statement)
            functions = c.execute("""SELECT p.proname,
                has_function_privilege(current_user,p.oid,'EXECUTE')
                FROM pg_proc p WHERE p.pronamespace='public'::regnamespace
                AND (p.proname LIKE '%flare_generation%' OR p.proname='flare_normalize')""").fetchall()
            assert len(functions) == 6
            allowed = {'enqueue_flare_generation', 'claim_flare_generation',
                       'load_flare_generation', 'finish_flare_generation'} if role == 'flare_worker' else set()
            assert {name for name, executable in functions if executable} == allowed
