"""Replacing a disconnected teammate binding never reuses their private namespace."""
from uuid import uuid4

import psycopg
import pytest
from test_source_sync import db, tenant, actor, api, connected, document, next_job, step
from test_source_creators import member, legacy, persisted
from app.models.tables import ItemRepository

pytestmark = pytest.mark.integration


def test_owner_reconnect_archives_binding_keeps_notes_and_fences_old_oauth_and_worker(db):
    w,u=tenant(db); old,job=connected(db,w,u)
    assert step(db,job,'publish',documents=[document(job)])['added']==1
    db.execute('RESET ROLE')
    original_doc=db.execute('SELECT document_id FROM source_items WHERE connection_id=%s',(old,)).fetchone()['document_id']
    legacy(db,original_doc); before=persisted(db,original_doc)
    owner=member(db,w,'owner','New owner')
    db.execute("UPDATE workspace_members SET role='editor' WHERE workspace_id=%s AND user_id=%s",(w,u))
    late_job=next_job(db,w,u,old)
    actor(db,w,u)
    assert api(db,'state',old,expectedRevision=3,stateHash='f'*64,pendingBlob='private-state')=={'ok':True}
    consumed=api(db,'consume_state',stateHash='f'*64,provider='gmail')
    assert consumed['id']==old
    actor(db,w,owner)
    assert api(db,'list')[0]['accountLabel'] is None
    assert api(db,'list')[0]['canReconnect'] is False
    assert api(db,'reserve',uuid4(),provider='gmail')['error']=='connection_owned_by_another_user'
    assert api(db,'disconnect',old)=={'ok':True}
    assert api(db,'list')[0]['canReconnect'] is True
    fresh=api(db,'reserve',uuid4(),provider='gmail'); new=fresh['id']
    assert new!=old and fresh['scopeRevision']==1
    current=api(db,'list'); assert len(current)==1 and current[0]['id']==new
    assert current[0]['accountLabel'] is None and current[0]['resources']==[] and not current[0]['enabled']
    assert api(db,'reserve',uuid4(),provider='gmail')['id']==new  # Same-owner retries are idempotent.
    assert api(db,'creators',connectionIds=[old])==[{'id':old,'createdBy':u,'createdByName':'Test'}]
    actor(db,w,u)
    assert api(db,'complete',old,expectedRevision=consumed['scopeRevision'],credentialBlob='late-secret',accountLabel='Late',policy={})['error']=='source_not_found'
    assert api(db,'credentials',old)['error']=='source_not_found'
    assert step(db,late_job,'publish',documents=[document(late_job,'Late overwrite')])['error']=='lease_lost'
    actor(db,w,owner)
    assert api(db,'complete',new,expectedRevision=1,credentialBlob='new-secret',accountLabel='new@example.invalid',policy={})=={'ok':True}
    assert api(db,'select',new,expectedRevision=2,resources=[{'id':'label','name':'Support','kind':'label'}],shareWithWorkspace=True)=={'ok':True}
    actor(db,w,owner,'flare_worker')
    new_job=db.execute("SELECT claim_source_job(ARRAY['gmail'],1) AS value").fetchone()['value']
    assert new_job['connection_id']==new
    assert step(db,new_job,'publish',documents=[document(new_job,'New account, same external ID')])['added']==1
    actor(db,w,owner)
    notes=ItemRepository(db).list_active(query=None,item_type=None,limit=100)
    assert len(notes)==2 and {n.metadata['createdBy'] for n in notes}=={u,owner}
    assert persisted(db,original_doc)==before
    archived=db.execute('SELECT * FROM source_connections WHERE id=%s',(old,)).fetchone()
    assert archived['retired_at'] and archived['owner_user_id']==u
    assert archived['credential_blob'] is None and archived['cursor_blob'] is None
    assert archived['account_label'] is None and archived['resources']==[]
    assert db.execute('SELECT count(*) AS n FROM source_items WHERE workspace_id=%s',(w,)).fetchone()['n']==2
    with pytest.raises(psycopg.errors.UniqueViolation):
        with db.transaction():
            db.execute("INSERT INTO source_connections(workspace_id,provider,owner_user_id) VALUES(%s,'gmail',%s)",(w,owner))


@pytest.mark.parametrize('role',['editor','viewer'])
def test_only_project_owner_may_reclaim_foreign_disabled_binding(db,role):
    w,u=tenant(db); old,job=connected(db,w,u)
    actor(db,w,u); assert api(db,'disconnect',old)=={'ok':True}
    user=member(db,w,role)
    actor(db,w,user)
    assert api(db,'list')[0]['canReconnect'] is False
    assert api(db,'reserve',uuid4(),provider='gmail')['error'] in ('forbidden','connection_owned_by_another_user')
    assert api(db,'disconnect',old)['error']=='forbidden'
    db.execute('RESET ROLE')
    assert db.execute('SELECT count(*) AS n FROM source_connections WHERE workspace_id=%s',(w,)).fetchone()['n']==1
