"""Real PostgreSQL tenant, job fencing and immutable source publication checks."""
import os
from uuid import uuid4
import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb
import pytest
from app.integrations.sources.contracts import SourceDocument
from app.services.source_sync import SourceProcessor

pytestmark=pytest.mark.integration


@pytest.fixture
def db():
    url=os.getenv('TEST_DATABASE_URL')
    if not url: pytest.skip('Disposable database required')
    with psycopg.connect(url,row_factory=dict_row) as connection:
        try: yield connection
        finally: connection.rollback()


def tenant(db):
    w,u=uuid4(),'source-test|'+uuid4().hex
    db.execute('RESET ROLE')
    db.execute("INSERT INTO workspaces(id,name) VALUES(%s,'Source test')",(w,))
    db.execute("INSERT INTO auth_users(id,email,name,password_hash,initial_workspace_id) VALUES(%s,%s,'Test','test',%s)",(u,u+'@example.invalid',w))
    db.execute("INSERT INTO workspace_members(workspace_id,user_id,role) VALUES(%s,%s,'owner')",(w,u))
    return w,u


def actor(db,w,u,role='flare_app'):
    db.execute('RESET ROLE'); db.execute('SET LOCAL ROLE '+role)
    db.execute("SELECT set_config('app.workspace_id',%s,true),set_config('app.user_id',%s,true)",(str(w),u))


def api(db,action,id=None,**payload):
    return db.execute('SELECT source_api(%s,%s,%s) AS value',(action,id,Jsonb(payload))).fetchone()['value']


def connected(db,w,u):
    actor(db,w,u); result=api(db,'reserve',uuid4(),provider='gmail'); id=result['id']
    assert api(db,'complete',id,expectedRevision=result['scopeRevision'],credentialBlob='test-encrypted',accountLabel='private@example.invalid',policy={'workspaceBytes':500000000})=={'ok':True}
    assert api(db,'select',id,expectedRevision=2,resources=[{'id':'label','name':'Support','kind':'label'}],shareWithWorkspace=True)=={'ok':True}
    actor(db,w,u,'flare_worker'); job=db.execute("SELECT claim_source_job(ARRAY['gmail'],1) AS value").fetchone()['value']
    assert job and job['connection_id']==id
    return id,job


def step(db,job,action,**payload):
    db.execute('RESET ROLE'); db.execute('SET LOCAL ROLE flare_worker')
    return db.execute('SELECT source_worker_step(%s,%s,%s,%s,%s) AS value',(job['id'],job['lease_token'],job['generation'],action,Jsonb(payload))).fetchone()['value']


def document(job,body='Feedback',title='Inbox'):
    return SourceProcessor.prepare(SourceDocument('account:message',title,body,'https://mail.google.com/mail/u/0/#all/message'),job)


def next_job(db,w,u,id):
    actor(db,w,u); assert 'error' not in api(db,'enqueue',id)
    actor(db,w,u,'flare_worker'); job=db.execute("SELECT claim_source_job(ARRAY['gmail'],1) AS value").fetchone()['value']; assert job; return job


def test_publication_dedupes_versions_preserves_local_changes_and_never_enqueues_ai(db):
    w,u=tenant(db); id,job=connected(db,w,u)
    first=step(db,job,'publish',documents=[document(job)],skipped=0)
    assert first['added']==1
    db.execute('RESET ROLE')
    row=db.execute('SELECT * FROM source_items WHERE connection_id=%s',(id,)).fetchone()
    assert db.execute('SELECT count(*) AS n FROM analysis_jobs WHERE workspace_id=%s',(w,)).fetchone()['n']==0
    job=next_job(db,w,u,id)
    assert step(db,job,'publish',documents=[document(job)])['unchanged']==1
    job=next_job(db,w,u,id)
    assert step(db,job,'publish',documents=[document(job,'Updated feedback')])['updated']==1
    db.execute('RESET ROLE')
    assert db.execute('SELECT count(*) AS n FROM document_versions WHERE document_id=%s',(row['document_id'],)).fetchone()['n']==2
    # A manual deletion must never be undone by future remote snapshots.
    db.execute('UPDATE documents SET deleted_at=now() WHERE id=%s',(row['document_id'],))
    job=next_job(db,w,u,id)
    assert step(db,job,'publish',documents=[document(job,'Another update')])['conflicts']==1


def test_cancel_disconnect_scope_change_and_expired_leases_fence_late_writes(db):
    w,u=tenant(db); id,job=connected(db,w,u)
    actor(db,w,u); assert api(db,'cancel',id)=={'ok':True}
    assert step(db,job,'publish',documents=[document(job)])['error']=='lease_lost'
    job=next_job(db,w,u,id)
    actor(db,w,u); assert api(db,'disconnect',id)=={'ok':True}
    assert step(db,job,'publish',documents=[document(job)])['error']=='lease_lost'
    actor(db,w,u); public=api(db,'list')[0]
    assert public['status']=='disabled' and not public['resources']
    db.execute('RESET ROLE'); assert db.execute('SELECT credential_blob FROM source_connections WHERE id=%s',(id,)).fetchone()['credential_blob'] is None


def test_credentials_other_tenant_and_viewer_cannot_browse_or_publish(db):
    w,u=tenant(db); id,job=connected(db,w,u)
    other,other_u=tenant(db); actor(db,other,other_u)
    assert api(db,'list')==[] and api(db,'credentials',id)['error']=='source_not_found'
    db.execute('RESET ROLE'); db.execute("UPDATE workspace_members SET role='viewer' WHERE workspace_id=%s AND user_id=%s",(w,u))
    actor(db,w,u)
    assert api(db,'credentials',id)['error']=='forbidden'
    assert step(db,job,'publish',documents=[document(job)])['error']=='authorization_lost'
    actor(db,w,u); assert api(db,'disconnect',id)=={'ok':True}


def test_app_worker_raw_secrets_and_procedure_privileges_are_restricted(db):
    w,u=tenant(db); id,job=connected(db,w,u)
    actor(db,w,u)
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with db.transaction(): db.execute('SELECT credential_blob FROM source_connections')
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with db.transaction(): db.execute("SELECT claim_source_job(ARRAY['gmail'],1)")
    actor(db,w,u,'flare_worker')
    with pytest.raises(psycopg.errors.InsufficientPrivilege):
        with db.transaction(): db.execute('SELECT * FROM source_jobs')


def test_shared_consent_revision_owner_and_worker_health(db):
    w,u=tenant(db); actor(db,w,u); value=api(db,'reserve',uuid4(),provider='gmail'); id=value['id']
    api(db,'complete',id,expectedRevision=1,credentialBlob='test',accountLabel='test',policy={})
    assert api(db,'select',id,expectedRevision=2,resources=[{'id':'x'}],shareWithWorkspace=False)['error']=='selection_consent_required'
    assert api(db,'select',id,expectedRevision=1,resources=[],shareWithWorkspace=True)['error']=='selection_changed'
    api(db,'select',id,expectedRevision=2,resources=[{'id':'x'}],shareWithWorkspace=True)
    db.execute('RESET ROLE'); db.execute("UPDATE source_worker_health SET last_seen_at=now()-interval '1 day'"); actor(db,w,u)
    assert api(db,'enqueue',id)['error']=='source_worker_unavailable'
    db.execute('RESET ROLE'); second='source-test|'+uuid4().hex
    db.execute("INSERT INTO auth_users(id,email,name,password_hash,initial_workspace_id) VALUES(%s,%s,'Test','test',%s)",(second,second+'@example.invalid',w))
    db.execute("INSERT INTO workspace_members(workspace_id,user_id,role) VALUES(%s,%s,'editor')",(w,second))
    actor(db,w,second)
    assert api(db,'credentials',id)['error']=='connection_owned_by_another_user'
    assert api(db,'reserve',uuid4(),provider='gmail')['error']=='connection_owned_by_another_user'


def test_rate_limit_never_retries_early_and_storage_failure_rolls_back_page(db):
    w,u=tenant(db); id,job=connected(db,w,u)
    step(db,job,'error',code='rate_limited',delay=121)
    actor(db,w,u); assert api(db,'enqueue',id)['error']=='rate_limited'
    db.execute('RESET ROLE'); db.execute("UPDATE source_jobs SET available_at=now() WHERE id=%s",(job['id'],))
    actor(db,w,u,'flare_worker'); job=db.execute("SELECT claim_source_job(ARRAY['gmail'],1) AS value").fetchone()['value']; assert job
    db.execute('RESET ROLE'); db.execute("UPDATE source_connections SET policy='{"+'"workspaceBytes":1'+"}' WHERE id=%s",(id,))
    with pytest.raises(psycopg.errors.ProgramLimitExceeded):
        with db.transaction(): step(db,job,'publish',documents=[document(job)])
    db.execute('RESET ROLE'); assert db.execute('SELECT count(*) AS n FROM documents WHERE workspace_id=%s',(w,)).fetchone()['n']==0
