import asyncio
from contextlib import contextmanager
from uuid import uuid4

from fastapi.testclient import TestClient
import psycopg
import pytest
from app.config import Settings
from app.main import create_app
from app.services.auth_service import AuthService
from test_flare_runs import stage, jobs, admin_url, processor, Detector

pytestmark=pytest.mark.integration


@contextmanager
def client_for(jobs,index=0):
    queue,_,users,_=jobs
    auth=AuthService(queue.database)
    with queue.database.connection() as c:
        email=c.execute('SELECT email FROM auth_users WHERE id=%s',(users[index].user_id,)).fetchone()['email']
    token=auth.login(email,'a-long-test-password')
    cfg=Settings(database_url=None,cors_origins=['http://testserver'],environment='test')
    with TestClient(create_app(cfg,database=queue.database)) as client:
        client.cookies.set('flare_session',token)
        yield client


def test_real_flare_reads_auth_isolation_and_deletion(stage,jobs,admin_url):
    assert asyncio.run(processor(stage,Detector()).process_one())=='completed'
    with client_for(jobs) as client:
        response=client.get('/flares')
        assert response.status_code==200 and response.headers['cache-control']=='no-store'
        rows=response.json(); assert len(rows)==1
        f=rows[0]
        assert f['type']=='Recommendation' and f['action'] and f['evidence'][0]['excerpt']
        assert set(f)=={'id','type','title','statement','action','reason','createdAt','evidence'}
        assert client.get('/flares/'+f['id']).json()==f
        assert client.get('/items/'+f['evidence'][0]['itemId']).status_code==200
        for limit in (0,101): assert client.get('/flares',params={'limit':limit}).status_code==422
        assert client.post('/flares',headers={'Origin':'http://testserver'},json={}).status_code==405
        assert client.post('/analyze',headers={'Origin':'http://testserver'},json={}).status_code==422
        client.cookies.clear()
        assert client.get('/flares').status_code==401
        assert client.get('/flares/'+f['id']).status_code==401
    with client_for(jobs,1) as client:
        assert client.get('/flares').json()==[]
        foreign=client.get('/flares/'+f['id'])
        missing=client.get('/flares/'+str(uuid4()))
        assert foreign.status_code==missing.status_code==404 and foreign.json()==missing.json()
    with client_for(jobs) as client:
        assert client.delete('/items/'+f['evidence'][0]['itemId'],headers={'Origin':'http://testserver'}).status_code==204
        assert client.get('/flares').json()==[]
        assert client.get('/flares/'+f['id']).status_code==404
    with psycopg.connect(admin_url) as c:
        assert c.execute('SELECT count(*) FROM insights WHERE id=%s',(f['id'],)).fetchone()==(1,)


def test_legacy_hidden_and_order_stable(stage,jobs,admin_url):
    from app.ai_engine.flare_config import FlareSettings
    from app.config import AISettings
    from app.services.flare_generation import FlareProcessor
    from app.workers.config import WorkerSettings
    assert asyncio.run(processor(stage,Detector()).process_one())=='completed'
    new = FlareSettings(max_completion_tokens=1025)
    stage[0].enqueue(stage[1], new.revision(AISettings()))
    assert asyncio.run(FlareProcessor(stage[0], Detector(), AISettings(), new, WorkerSettings()).process_one()) == 'completed'
    with psycopg.connect(admin_url) as c:
        c.execute("INSERT INTO insights(workspace_id,title,summary,body,model,prompt_version) VALUES(%s,'Legacy','Legacy','Legacy','old','old')",(stage[3].workspace_id,))
        c.execute("UPDATE insights SET created_at='2026-01-01' WHERE workspace_id=%s", (stage[3].workspace_id,))
        expected = [str(r[0]) for r in c.execute('SELECT id FROM insights WHERE workspace_id=%s AND flare_type IS NOT NULL ORDER BY created_at DESC,id DESC', (stage[3].workspace_id,))]
    with client_for(jobs) as client:
        assert [f['id'] for f in client.get('/flares').json()] == expected
        assert [f['id'] for f in client.get('/flares?limit=1').json()] == expected[:1]


def test_one_deleted_support_hides_multi_document_flare(stage, jobs, admin_url):
    from dataclasses import asdict
    from app.services.item_service import ItemService
    from test_flare_runs import metadata, TEXT
    queue, worker, users, _ = jobs
    note = ItemService(queue.database, users[0], enqueue_analysis=False).create_note(
        title='Second support', content=TEXT
    )
    with queue.database.workspace_transaction(users[0]) as c:
        chunk = c.execute('SELECT c.id FROM chunks c JOIN document_versions v ON v.id=c.document_version_id WHERE v.document_id=%s', (note.id,)).fetchone()['id']
    parent = queue.enqueue(users[0], (stage[2], chunk), 'two-supports')
    claim = worker.claim(uuid4(), 120)
    assert claim.job_id == parent
    worker.finish(claim, result={'observations': []}, metadata={})
    runs = stage[0]
    # Complete the fixture's earlier run first, leaving only our two-source run.
    assert asyncio.run(processor(stage, Detector(empty=True)).process_one()) == 'completed'
    run = runs.claim(uuid4(), 120)
    loaded = runs.load(run, 5, 4000)
    from app.ai_engine.analysis import Evidence
    result = asyncio.run(Detector().detect(None, [Evidence.model_validate(e) for e in loaded['evidence']]))
    candidate = result.candidates.flares[0].model_dump()
    candidate['evidence'] = [dict(source_id=str(s), quote=TEXT, supports=['goal', 'state']) for s in (stage[2], chunk)]
    assert runs.finish(run, flares=[candidate], metadata=asdict(metadata())) == 'completed'
    with client_for(jobs) as client:
        flare = client.get('/flares').json()[0]
        assert len(flare['evidence']) == 2
        assert client.delete('/items/' + str(note.id), headers={'Origin': 'http://testserver'}).status_code == 204
        assert client.get('/flares').json() == []
        missing = client.get('/flares/' + str(uuid4()))
        deleted = client.get('/flares/' + flare['id'])
        assert deleted.status_code == missing.status_code == 404
        assert deleted.json() == missing.json()
        live = next(e['itemId'] for e in flare['evidence'] if e['itemId'] != str(note.id))
        assert client.get('/items/' + live).status_code == 200


def test_worker_generation_and_api_reads_with_separate_process_secrets(stage, jobs, tmp_path):
    """Only restricted login DSNs cross into runtime subprocesses; no migration DSN."""
    import json
    import os
    from pathlib import Path
    import subprocess
    import sys

    backend = Path(__file__).resolve().parents[1]
    worker_file = tmp_path / 'worker.env'
    worker_file.write_text(
        'FLARE_PROCESS_ROLE=worker\nFLARE_ENV=test\n'
        f'WORKER_DATABASE_URL={jobs[1]._database_url}\nGROQ_API_KEY=test-only-no-network\n'
    )
    worker_file.chmod(0o600)
    # Inherit only runtime basics; intentionally exclude all ambient DB/key variables.
    env = {key: value for key, value in os.environ.items() if key in ('PATH', 'SYSTEMROOT', 'LANG')}
    env['PYTHONPATH'] = os.pathsep.join((str(backend), str(backend / 'tests')))
    env['FLARE_DOTENV_PATH'] = str(worker_file)
    worker_code = '''
import asyncio
import os
from app.workers.config import load_worker_settings
from app.config import load_ai_settings, settings
from app.ai_engine.flare_config import load_flare_settings
from app.services.flare_generation import FlareProcessor
from app.models.flare_runs import FlareRuns
from test_flare_runs import Detector
assert settings.database_url is None
assert 'DATABASE_URL' not in os.environ
assert 'MIGRATION_DATABASE_URL' not in os.environ
config = load_worker_settings()
processor = FlareProcessor(FlareRuns(config.database_url), Detector(),
                           load_ai_settings(), load_flare_settings(), config)
assert asyncio.run(processor.process_one()) == 'completed'
'''
    subprocess.run([sys.executable, '-c', worker_code], env=env, check=True, timeout=30)

    api_file = tmp_path / 'api.env'
    api_file.write_text('FLARE_PROCESS_ROLE=api\nFLARE_ENV=test\n'
                        f'DATABASE_URL={os.environ["DATABASE_URL"]}\nCORS_ORIGINS=http://testserver\n')
    api_file.chmod(0o600)
    env['FLARE_DOTENV_PATH'] = str(api_file)
    with jobs[0].database.connection() as c:
        email = c.execute('SELECT email FROM auth_users WHERE id=%s', (stage[3].user_id,)).fetchone()['email']
    api_code = '''
import json
import os
import sys
from fastapi.testclient import TestClient
from app.main import create_app
from app.services.auth_service import AuthService
assert all(name not in os.environ for name in ('WORKER_DATABASE_URL','GROQ_API_KEY','MIGRATION_DATABASE_URL'))
app = create_app()
with TestClient(app) as client:
    token = AuthService(app.state.database).login(json.load(sys.stdin)['email'], 'a-long-test-password')
    client.cookies.set('flare_session', token)
    response = client.get('/flares')
    assert response.status_code == 200 and len(response.json()) == 1
    flare = response.json()[0]
    assert client.get('/flares/' + flare['id']).json() == flare
    assert flare['evidence']
'''
    subprocess.run([sys.executable, '-c', api_code], env=env,
                   input=json.dumps({'email': email}), text=True, check=True, timeout=30)
